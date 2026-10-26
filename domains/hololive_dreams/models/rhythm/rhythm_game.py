"""Visual-first six-lane rhythm controller for hololive Dreams.

Dry-run is the default. The timing grid is only a stabilizer; visual arrival
estimates remain authoritative. This module intentionally does not guess the
semantics of unknown special notes.
"""
from __future__ import annotations
from dataclasses import dataclass
from collections import deque
import argparse, json, math, time
import threading
from pathlib import Path
import cv2
import numpy as np

from modular_agent.computer import ActionComputer
from modular_agent.core import Action, Outcome
from modular_agent.realtime.rhythm_capture import create_capture


@dataclass
class Note:
    lane: int
    kind: str
    center: tuple[float, float]
    width: float
    height: float
    confidence: float
    color: str = 'blue'
    tail: tuple = ()
    appearance_score: float | None = None
    raw_kind: str | None = None


def field_edges(config,y):
    """Playable six-lane grid, excluding the decorative outer highway."""
    g=config.get('geometry',dict(top_y=13/711,top_left=592/1264,top_right=672/1264,
                               hit_left=122/1264,hit_right=1142/1264))
    f=(y-g['top_y'])/(config['hit_line_y']-g['top_y'])
    return (g['top_left']+(g['hit_left']-g['top_left'])*f,
            g['top_right']+(g['hit_right']-g['top_right'])*f)


def discrete_span(config,x,y,width):
    """Quantize trustworthy note edges to the twelve chart-cell boundaries."""
    left,right=field_edges(config,y)
    scale=12/max(right-left,1e-6)
    a=(x-width/2-left)*scale;b=(x+width/2-left)*scale
    start=round(a);end=round(b)
    if abs(a-start)>.28 or abs(b-end)>.28:return None
    start=max(0,min(12,start));end=max(0,min(12,end))
    return (start,end) if end>start else None


class BeatGrid:
    """Learn a time lattice, not a claimed musical BPM. Never creates notes."""
    def __init__(self, subdivision=16, bpm=None, snap_ms=3):
        self.subdivision, self.bpm, self.phase = subdivision, bpm, None
        if isinstance(snap_ms,bool) or not isinstance(snap_ms,(int,float)) or not math.isfinite(snap_ms) or not 0<=snap_ms<=25:
            raise ValueError('grid_snap_ms must be 0..25 ms')
        self.snap_ms=float(snap_ms)
        if bpm is not None and (not math.isfinite(bpm) or bpm<=0):raise ValueError('BPM must be positive')
        self.fixed=bpm is not None;self.arrivals=deque(maxlen=48);self.candidate=None;self.stable=0;self.onsets=0
        self._period=None if bpm is None else 60/bpm*4/subdivision
        self.locked=False;self.confidence=0.;self.error_ms=None;self.candidates=[];self.bad=0
        self.state='collecting';self.cooldown=0

    @property
    def period(self):
        return self._period

    def status(self):
        return dict(state=self.state,locked=self.locked,period_ms=None if self.period is None else self.period*1000,
                    snap_ms=self.snap_ms,snap_limit_ms=self.snap_ms if self.period is None else min(self.snap_ms,self.period*490),
                    phase=self.phase,confidence=self.confidence,error_ms=self.error_ms,
                    candidate_bpm_16th=None if self.period is None else 15/self.period,
                    candidate_bpm_8th=None if self.period is None else 30/self.period,
                    bpm_confirmed=self.fixed,candidates=self.candidates,observations=len(self.arrivals))

    @staticmethod
    def fit(values,periods):
        # Joint circular phase estimation, robust refinement, relative times
        # avoid loss of precision with absolute perf_counter timestamps.
        delta=np.asarray(values)-values[0];periods=np.asarray(periods)
        angles=2*np.pi*delta[None,:]/periods[:,None]
        phase=np.arctan2(np.sin(angles).sum(axis=1),np.cos(angles).sum(axis=1))*periods/(2*np.pi)
        for _ in range(2):
            residual=delta[None,:]-phase[:,None]
            residual-=np.round(residual/periods[:,None])*periods[:,None]
            phase+=np.median(residual,axis=1)
        residual=delta[None,:]-phase[:,None]
        residual-=np.round(residual/periods[:,None])*periods[:,None]
        errors=np.abs(residual)
        return np.mean(np.minimum(errors,.020),axis=1),phase+values[0],np.mean(errors<.012,axis=1)

    def observe(self, visual_time, prior_time=None):
        # One observed onset per chord, never screenshot/frame intervals.
        if not math.isfinite(visual_time):return
        if any(abs(visual_time-t)<.025 for t in self.arrivals):return
        self.arrivals.append(visual_time)
        self.onsets+=1
        if self.locked:
            residual=visual_time-(self.phase+round((visual_time-self.phase)/self.period)*self.period)
            self.bad=self.bad+1 if abs(residual)>.015 else 0
            if self.bad>=3:
                self.locked=False;self.confidence=0.;self.state='relearning';self.stable=0;self.candidate=None
                if self.fixed:self.cooldown=4
                # Do not let an old song dominate the new window.
                recent=list(self.arrivals)[-12:];self.arrivals.clear();self.arrivals.extend(recent)
            elif abs(residual)<.012:
                self.phase+=.05*residual
        if self.fixed:
            if self.cooldown:
                self.cooldown-=1
                return
            if self.phase is None:self.phase=visual_time
            if not self.locked and len(self.arrivals)>=4:
                score,phase,support=self.fit(sorted(self.arrivals),[self.period])
                self.locked=bool(score[0]<.008 and support[0]>=.7)
                if self.locked:self.phase=float(phase[0])
            # Explicit BPM starts usable immediately; contrary evidence disables it.
            if len(self.arrivals)==1:self.locked=True
            self.confidence=1. if self.locked else 0.;self.state='fixed' if self.locked else 'relearning'
            return
        if not self.fixed and len(self.arrivals)>=12 and self.onsets%4==0:
            values=np.sort(np.array(self.arrivals))
            coarse=np.arange(.045,.25001,.00025)
            scores,phases,support=self.fit(values,coarse)
            selected=[]
            for index in np.argsort(scores):
                if all(abs(coarse[index]-coarse[j])>.002 for j in selected):selected.append(int(index))
                if len(selected)==4:break
            fine=np.unique(np.concatenate([np.arange(max(.045,coarse[i]-.00025),min(.250,coarse[i]+.00025)+.000005,.00001) for i in selected]))
            scores,phases,support=self.fit(values,fine)
            # Prefer the coarsest equally good lattice; sparse notes cannot
            # prove subdivisions. Keep alternative candidates visible.
            best=int(np.argmin(scores));ratio=fine/fine[best]
            eligible=np.flatnonzero((scores<=scores[best]+.00035)&(ratio>1.5)&(np.abs(ratio-np.round(ratio))<.015))
            # Prefer genuine harmonic alternatives, not a slightly longer
            # neighbouring search bin (which would introduce phase drift).
            if len(eligible):best=int(eligible[np.argmax(fine[eligible])])
            period=float(fine[best])
            alternatives=[]
            for i in np.argsort(scores):
                if all(abs(fine[i]*1000-c['period_ms'])>2 for c in alternatives):
                    alternatives.append(dict(period_ms=float(fine[i]*1000),bpm_16th=float(15/fine[i]),error_ms=float(scores[i]*1000)))
                if len(alternatives)==4:break
            self.candidates=alternatives;self.error_ms=float(scores[best]*1000)
            stable=self.candidate is not None and abs(period-self.candidate)<max(.0004,period*.008)
            if stable and self.phase is not None:
                stable=abs(float(phases[best])-self.phase-round((float(phases[best])-self.phase)/period)*period)<.008
            self.stable=self.stable+1 if stable else 1;self.candidate=period
            good=bool(scores[best]<.008 and support[best]>=.7)
            self.confidence=float(support[best]*min(1.,self.stable/3)) if good else 0.
            self.locked=good and self.stable>=3
            self._period=period;self.phase=float(phases[best]);self.state='locked' if self.locked else 'candidate'

    def nearest(self, value):
        if self.snap_ms==0 or not self.locked or self.period is None or self.phase is None: return value
        n = round((value-self.phase)/self.period)
        snapped = self.phase+n*self.period
        # Keep the configurable acceptance window below half a grid cell so
        # increasing it cannot pull observations across an ambiguous midpoint.
        return snapped if abs(snapped-value) <= min(self.snap_ms/1000,self.period*.49) else value


class RhythmVision:
    """Detect colored note bodies inside the perspective playfield."""
    def __init__(self, config):
        self.c = config
        self.previous = []
        self.previous_time = None
        self.hold_paths=[]
        self._field=None;self._rows={}
        template=Path(__file__).resolve().parents[2]/'data/rhythm_samples/pink_note_face.png'
        self.pink_template=cv2.imdecode(np.fromfile(template,np.uint8),cv2.IMREAD_COLOR) if template.exists() else None

    def ribbon(self, mask, x, y, direction=-1, limit=.45):
        """Follow contiguous same-color horizontal runs, allowing gradual bends."""
        h,w=mask.shape; points=[]; last=x; misses=0
        for row in range(round(y*h),max(0,round((y-limit)*h)) if direction<0 else min(h,round((y+limit)*h)),direction*max(2,round(h*.006))):
            cache_key=(id(mask),row)
            if cache_key not in self._rows:
                indices=np.flatnonzero(mask[row]);all_runs=[]
                for segment in np.split(indices,np.where(np.diff(indices)>1)[0]+1):
                    if len(segment)>=max(5,w*.012):all_runs.append((float((segment[0]+segment[-1])/2/w),len(segment)/w))
                self._rows[cache_key]=all_runs
            runs=[r for r in self._rows[cache_key] if abs(r[0]-last)<.075]
            if not runs:
                misses+=1
                if misses>=2: break
                continue
            center,width=min(runs,key=lambda a:abs(a[0]-last))
            points.append((center,row/h,width));last=center;misses=0
        return tuple(points)

    def reset(self):
        self.previous, self.previous_time = [], None

    @staticmethod
    def side_depth(height,face_height):
        return max(6,min(round(height*.025),round(face_height*.5)))

    def side_colour(self,mask,x,y,bw,bh,direction):
        """Colour occupancy beside a face; no ribbon-shape assumptions."""
        h,w=mask.shape;depth=self.side_depth(h,bh)
        start=y+bh+2 if direction>0 else y-2-depth
        end=start+depth
        if start<0 or end>h:return False
        # Stay mainly within the bar's width. Zigzags, splits and curves all
        # count as coloured background; isolated sparkles have little area.
        inset=round(bw*.1);patch=mask[start:end,max(0,x+inset):min(w,x+bw-inset)]
        if not patch.size:return False
        coverage=np.mean(patch>0,axis=1)
        if direction>0:
            # A genuine endpoint has colour immediately underneath it.
            # Distant judgement glow must not supply the missing connection.
            near=coverage[:max(2,round(depth*.3))]
            return bool(np.mean(coverage)>=.25 and np.mean(coverage>=.30)>=.6
                        and np.mean(near)>=.20)
        return bool(np.mean(coverage)>=.12 and np.mean(coverage>=.30)>=.3)

    def lane_for(self, x, y, width=None):
        left,right=field_edges(self.c,y)
        if width is not None:
            span=discrete_span(self.c,x,y,width)
            if span is not None:
                # An exact F/J centre boundary deterministically uses F;
                # pixel rounding must not toggle a note's identity/key.
                return min(5,max(0,int(math.floor((span[0]+span[1])/4-1e-6))))
        lane = int(math.floor((x-left)/max(right-left, 1e-6)*6))
        return lane if 0 <= lane < 6 else None

    def coloured_face_box(self,contour,h,w,cutoff):
        """Shared validation: only real face candidates can veto supplements."""
        x,y,bw,bh=cv2.boundingRect(contour);cx,cy=(x+bw/2)/w,(y+bh/2)/h
        if y+bh>=cutoff:return None
        if not self.c.get('detection_start_y',.06)<=cy<=min(.769,self.c['hit_line_y']-.035):return None
        if bw/max(bh,1)<2.5 or bw<7 or bh<2 or bh>max(10,h*.065):return None
        left,right=field_edges(self.c,cy);field_width=(right-left)*w
        if not .065*field_width<=bw<=1.05*field_width:return None
        if bh<(.022 if cy>.35 else .016)*field_width:return None
        if cv2.contourArea(contour)/max(1,bw*bh)<.55:return None
        if self.lane_for(cx,cy,bw/w) is None:return None
        return x,y,bw,bh

    @staticmethod
    def same_face_area(a,b):
        """Overlap over the smaller box catches a chord-spanning duplicate.

        Vertical overlap (not just proximity) preserves adjacent rapid heads.
        """
        x,y,w,h=a;xx,yy,ww,hh=b
        return (min(x+w,xx+ww)-max(x,xx)>.5*min(w,ww) and
                min(y+h,yy+hh)-max(y,yy)>.5*min(h,hh))

    def face_edges(self, image, field):
        """Horizontal border pairs survive a face connected to a bright ribbon.

        This supplies candidates only; colour, perspective thickness, ROI and
        duplicate checks remain mandatory. No ribbon silhouette is assumed.
        """
        h,w=image.shape[:2]
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        delta=np.zeros_like(gray)
        delta[1:]=cv2.absdiff(gray[1:],gray[:-1])
        edges=cv2.inRange(delta,16,255)&field
        edges=cv2.morphologyEx(edges,cv2.MORPH_CLOSE,np.ones((1,5),np.uint8))
        edges=cv2.morphologyEx(edges,cv2.MORPH_OPEN,np.ones((1,max(9,round(w*.026))),np.uint8))
        lines=sorted((cv2.boundingRect(c) for c in cv2.findContours(edges,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]),key=lambda b:b[1])
        result=[]
        for i,(x,y,bw,bh) in enumerate(lines):
            if bh>max(4,round(h*.012)):continue
            for xx,yy,ww,hh in lines[i+1:]:
                depth=yy-y
                if depth>max(10,h*.065):break
                left,right=field_edges(self.c,(y+yy)/2/h)
                minimum=max(3,(.022 if (y+yy)/2/h>.35 else .016)*(right-left)*w)
                if depth<minimum or hh>max(4,round(h*.012)):continue
                overlap=min(x+bw,xx+ww)-max(x,xx)
                if overlap<.8*max(bw,ww):continue
                # The lower border is slightly wider under perspective.
                bx=max(x,xx);end=min(x+bw,xx+ww)
                box=(bx,y+1,end-bx,yy-y)
                if box[2]<2.5*box[3]:continue
                if any(abs(box[1]-b[1])<4 and abs(box[3]-b[3])<5 and
                       abs(box[0]-b[0])<5 for b in result):continue
                result.append(box)
        return result

    def detect(self, image, timestamp):
        h, w = image.shape[:2]
        self._rows={}
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        # Fixed client geometry: exclude scenery BEFORE finding components.
        cutoff=round(h*self.c.get('recognition_end_y',self.c.get('prediction_zone',[.26,.62])[1]))
        if self._field is None or self._field.shape!=(h,w) or getattr(self,'_field_cutoff',None)!=cutoff:
            self._field=np.zeros((h,w),np.uint8)
            top=self.c.get('geometry',{}).get('top_y',13/711)
            a,b=field_edges(self.c,top);left,right=field_edges(self.c,.825)
            polygon=np.array([[a*w,top*h],[b*w,top*h],
                              [right*w,.825*h],[left*w,.825*h]],np.int32)
            cv2.fillConvexPoly(self._field,polygon,255)
            self._field[cutoff:]=0;self._field_cutoff=cutoff
        field=self._field
        # Old V>=100 included dark blue background text and towers. Actual
        # note faces are bright cyan with a wide, near-horizontal silhouette.
        combined=cv2.inRange(hsv,np.array([85,65,220],np.uint8),np.array([110,255,255],np.uint8))
        combined=cv2.bitwise_and(combined,field)
        combined=cv2.morphologyEx(combined,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
        # Chord decorations are one/two-pixel horizontal lines touching the
        # faces. Remove them vertically before extracting face contours.
        thick=cv2.morphologyEx(combined,cv2.MORPH_OPEN,np.ones((3,1),np.uint8))
        far=round(h*.16)
        thick[:far]=combined[:far]  # Keep genuine two-pixel distant faces.
        combined=thick
        combined=cv2.morphologyEx(combined,cv2.MORPH_OPEN,np.ones((1,5),np.uint8))
        notes=[]
        for contour in cv2.findContours(combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]:
            area=cv2.contourArea(contour)
            if not self.c["min_area"] <= area <= self.c["max_area"]: continue
            x,y,bw,bh=cv2.boundingRect(contour); cx=(x+bw/2)/w; cy=(y+bh/2)/h
            if y+bh>=cutoff:continue  # Never fit a face clipped by protection ROI.
            # Observe above the judgement glow; the tracker predicts the final
            # short gap instead of treating illuminated lane segments as bars.
            if not self.c.get('detection_start_y',.06) <= cy <= min(.769,self.c['hit_line_y']-.035): continue
            # Bars may span several lanes or the whole field. Width is not
            # duration; keep the lower aspect bound and check thickness below.
            if bw/max(bh,1)<3.0: continue
            if bw<7 or bh<2: continue
            # The note size grows with distance from the vanishing point.
            left,right=field_edges(self.c,cy);field_width=(right-left)*w
            if not .065*field_width<=bw<=1.05*field_width: continue
            # Perspective scales thickness too; thin lane-light reflections
            # must not become bars when cropped by the corrected field mask.
            if bh<(.028 if cy>.35 else .016)*field_width:continue
            if bh>max(10,h*.065): continue
            if area/(bw*bh)<.42: continue
            patch=hsv[y:y+bh,x:x+bw]
            if np.mean(patch[:,:,2]>=220)<.65: continue
            lane=self.lane_for(cx,cy,bw/w)
            if lane is None: continue
            kind='tap'
            notes.append(Note(lane,kind,(cx,cy),bw/w,bh/h,min(1.,area/400.)))
        self.hold_paths=[]
        edge_faces=self.face_edges(image,field)
        all_ribbons=(cv2.inRange(hsv,np.array([38,55,110],np.uint8),np.array([85,255,255],np.uint8)) |
                     cv2.inRange(hsv,np.array([18,65,130],np.uint8),np.array([38,255,255],np.uint8))) & field
        for color,lo,hi in [('green',[38,55,110],[85,255,255]),('yellow',[18,65,130],[38,255,255])]:
            ribbon=cv2.inRange(hsv,np.array(lo,np.uint8),np.array(hi,np.uint8)) & field
            bright=cv2.inRange(hsv,np.array([lo[0],80,220],np.uint8),np.array(hi,np.uint8)) & field
            # Repair local face holes without bridging distinct chord heads.
            # The old 17px-wide close joined real ~12px gaps at width 960,
            # then a ribbon under one face suppressed both as a slide end.
            bright=cv2.morphologyEx(bright,cv2.MORPH_CLOSE,np.ones((3,3),np.uint8))
            # Bright faces are thin; the translucent ribbon is not a bar.
            bright=cv2.morphologyEx(bright,cv2.MORPH_OPEN,np.ones((2,5),np.uint8))
            contours=list(cv2.findContours(bright,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0])
            ordinary_boxes=[box for c in contours if (box:=self.coloured_face_box(c,h,w,cutoff)) is not None]
            supplemental_boxes=[]
            for x,y,bw,bh in edge_faces:
                # Both colour/brightness support and both horizontal borders
                # are needed; edges alone (sparkles/chord links) are not notes.
                region=bright[y:y+bh,x:x+bw]
                if region.size==0 or np.mean(region>0)<.75:continue
                candidate=np.array([[[x,y]],[[x+bw-1,y]],[[x+bw-1,y+bh-1]],[[x,y+bh-1]]],np.int32)
                if self.coloured_face_box(candidate,h,w,cutoff) is None:continue
                # A supplementary face may fill a missing observation, never
                # create a super-face over one/two existing independent heads.
                # Invalid tall ribbon components must NOT veto true recovery.
                if any(self.same_face_area((x,y,bw,bh),box) for box in ordinary_boxes+supplemental_boxes):continue
                contours.append(candidate);supplemental_boxes.append((x,y,bw,bh))
            for contour in contours:
                box=self.coloured_face_box(contour,h,w,cutoff)
                if box is None:continue
                x,y,bw,bh=box;cx,cy=(x+bw/2)/w,(y+bh/2)/h
                left,right=field_edges(self.c,cy)
                lane=self.lane_for(cx,cy,bw/w)
                raw_path=self.ribbon(ribbon,cx,(y-2)/h);path=[];misses=0
                previous_lane=(cx-left)/(right-left)*6;head_width=(bw/w)/(right-left)
                for px,py,pw in raw_path:
                    a,b=field_edges(self.c,py);position=(px-a)/(b-a)*6
                    if .45<=pw/(b-a)/head_width<=1.7 and abs(position-previous_lane)<.35:
                        path.append((px,py,pw));previous_lane=position;misses=0
                    else:
                        misses+=1
                        if misses>=2:break
                path=tuple(path)
                has_tail=len(path)>=4 and (path[0][1]-path[-1][1])>=.025
                # A change/crossing of ribbon colour above is not an end.
                above_colour=self.side_colour(all_ribbons,x,y,bw,bh,-1)
                below_colour=self.side_colour(ribbon,x,y,bw,bh,1)
                # End judgement depends on colour presence, not a fixed path.
                end_only=(not above_colour and below_colour
                    and y/h>=self.c.get('detection_start_y',.06)+.03
                    and y+bh+2+self.side_depth(h,bh)<cutoff)
                kind='slide_end' if end_only else 'hold' if has_tail else 'tap'
                notes.append(Note(lane,kind,(cx,cy),bw/w,bh/h,1.,color,path if has_tail and not end_only else ()))
            # A short lookahead above the judgement glow supplies curved-ribbon
            # handoffs. Only an already active hold may use these observations.
            row=round((self.c['hit_line_y']-.03)*h)
            if row>=cutoff:continue  # No lower-zone paths, even for active holds.
            indices=np.flatnonzero(ribbon[row])
            for segment in np.split(indices,np.where(np.diff(indices)>1)[0]+1):
                if len(segment)<max(6,w*.018): continue
                cx=float((segment[0]+segment[-1])/2/w);cy=row/h
                lane=self.lane_for(cx,cy)
                if lane is None: continue
                path=self.ribbon(ribbon,cx,cy)
                if len(path)>=4:self.hold_paths.append(dict(color=color,lane=lane,x=cx,path=path))
        # A chevron can have the same aspect ratio as a short bar. Require
        # several full horizontal rows instead of relying on aspect alone.
        pink=cv2.inRange(hsv,np.array([135,55,180],np.uint8),np.array([179,255,255],np.uint8)) & field
        pink=cv2.morphologyEx(pink,cv2.MORPH_CLOSE,np.ones((3,5),np.uint8))
        ribbon_mask=(cv2.inRange(hsv,np.array([38,55,110],np.uint8),np.array([85,255,255],np.uint8)) |
                     cv2.inRange(hsv,np.array([18,65,130],np.uint8),np.array([38,255,255],np.uint8))) & field
        for contour in cv2.findContours(pink,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)[0]:
            x,y,bw,bh=cv2.boundingRect(contour);cx,cy=(x+bw/2)/w,(y+bh/2)/h
            if y+bh>=cutoff:continue
            if not self.c.get('detection_start_y',.06)<=cy<=min(.769,self.c['hit_line_y']-.035):continue
            left,right=field_edges(self.c,cy);field_width=(right-left)*w
            if bw<max(7,.065*field_width) or bw>1.05*field_width or bh<2 or bw/bh<3:continue
            if bh>max(10,h*.065) or cv2.contourArea(contour)/max(1,bw*bh)<.4:continue
            if bh<.018*field_width:continue
            row_coverage=np.mean(pink[y:y+bh,x:x+bw]>0,axis=1)
            if np.mean(row_coverage>.65)<.70:continue
            lane=self.lane_for(cx,cy,bw/w)
            if lane is None:continue
            score=None
            if self.pink_template is not None:
                template=cv2.resize(self.pink_template,(bw,bh));patch=image[y:y+bh,x:x+bw]
                score=float(cv2.matchTemplate(cv2.cvtColor(patch,cv2.COLOR_BGR2GRAY),cv2.cvtColor(template,cv2.COLOR_BGR2GRAY),cv2.TM_CCOEFF_NORMED)[0,0])
                if not math.isfinite(score):score=None
            # A pink flick face can terminate a green/yellow ribbon. The
            # chevron above it is not evidence of an upstream ribbon.
            end_only=(self.side_colour(ribbon_mask,x,y,bw,bh,1) and
                not self.side_colour(ribbon_mask,x,y,bw,bh,-1) and
                y/h>=self.c.get('detection_start_y',.06)+.03 and
                y+bh+2+self.side_depth(h,bh)<cutoff)
            notes.append(Note(lane,'slide_end' if end_only else 'pink_trial',(cx,cy),bw/w,bh/h,.8,'pink',(),score))
        # A glare can leave a small end fragment next to a recovered wide
        # face. Merge only overlapping horizontal extents, never a real gap
        # between chord notes; do not group nearby arrival times.
        merged=[]
        for note in sorted(notes,key=lambda n:n.width,reverse=True):
            match=None
            for other in merged:
                if note.color not in ('green','yellow') or note.color!=other.color:continue
                nx,ny=note.center;ox,oy=other.center
                overlap=min(nx+note.width/2,ox+other.width/2)-max(nx-note.width/2,ox-other.width/2)
                vertical=min(ny+note.height/2,oy+other.height/2)-max(ny-note.height/2,oy-other.height/2)
                if overlap>0 and vertical>.6*min(note.height,other.height):match=other;break
            if match is None:merged.append(note);continue
            x0=min(note.center[0]-note.width/2,match.center[0]-match.width/2)
            x1=max(note.center[0]+note.width/2,match.center[0]+match.width/2)
            y0=min(note.center[1]-note.height/2,match.center[1]-match.height/2)
            y1=max(note.center[1]+note.height/2,match.center[1]+match.height/2)
            match.center=((x0+x1)/2,(y0+y1)/2);match.width=x1-x0;match.height=y1-y0
            match.lane=self.lane_for(*match.center,match.width)
            if match.kind=='slide_end' and note.kind!='slide_end':match.kind=note.kind
        notes=merged
        notes.sort(key=lambda n:n.center[1], reverse=True)
        self.previous, self.previous_time = notes, timestamp
        return notes


class KeyState:
    def __init__(self, computer, live, keys, on_send=None):
        self.computer,self.live,self.keys,self.down=computer,live,keys,set();self.on_send=on_send
    def update(self, desired):
        for key in sorted(desired-self.down):
            self.send("key_down",key);self.down.add(key)
        # Make-before-break for cross-lane hold handoffs.
        for key in sorted(self.down-desired):
            self.send("key_up",key);self.down.remove(key)
    def send(self, name, key):
        if self.live:
            begin=time.perf_counter()
            try:result=self.computer.perform(Action(name,arguments={"key":key}))
            except Exception as error:
                if self.on_send:self.on_send(dict(time=time.perf_counter(),begin=begin,key=key,down=name=='key_down',success=False,message=str(error)))
                raise
            if self.on_send:self.on_send(dict(time=time.perf_counter(),begin=begin,key=key,down=name=='key_down',success=result.outcome==Outcome.SUCCESS,message=result.message))
            if result.outcome != Outcome.SUCCESS: raise RuntimeError(result.message)
    def release(self):
        if self.live and getattr(self.computer,'stopped',False):
            # Dedicated cleanup is allowed after stop; perform(key_up) is not.
            begin=time.perf_counter();self.computer.release_all();end=time.perf_counter()
            released=list(self.down);self.down.clear()
            if self.on_send:
                for key in released:self.on_send(dict(time=end,begin=begin,key=key,down=False,success=True,cleanup_confirmation=True,message='release_all confirmed; exact per-key release time unavailable'))
            return
        failure=None
        for key in sorted(self.down):
            try:self.send('key_up',key);self.down.remove(key)
            except Exception as error:failure=error
        if failure:raise failure


class MotionCurve:
    """Learned spatial phase; speed in phase units is fitted per note.

    Power=1 is the legacy screen-linear model. The game profile is trained
    offline, never changed by live sparkles or frame intervals.
    """
    def __init__(self, config):
        profile=config.get('motion_curve',{})
        self.power=float(profile.get('power',1.));self.offset=float(profile.get('offset',0.))
        if not math.isfinite(self.power) or not math.isfinite(self.offset) or self.offset<0:
            raise ValueError('Invalid motion_curve profile')
    def phase(self,y):
        z=np.maximum(np.asarray(y)+self.offset,1e-6)
        return np.log(z) if abs(self.power)<1e-8 else (z**self.power-1)/self.power
    def position(self,phase):
        if abs(self.power)<1e-8:return np.exp(np.clip(phase,-20,20))-self.offset
        return np.maximum(1+self.power*np.asarray(phase),1e-6)**(1/self.power)-self.offset
    def derivative(self,y):return max(y+self.offset,1e-6)**(self.power-1)
    def predict(self,track,now):
        elapsed=max(0.,now-track['last'])
        if track.get('phase_rate') is None:return track['y']+track.get('velocity',0)*elapsed
        return float(self.position(self.phase(track['y'])+track['phase_rate']*elapsed))


class GlobalFlow:
    """Experimental multi-note phase speed, independent of musical BPM."""
    def __init__(self,config,motion):
        self.c=config;self.motion=motion;self.previous=[];self.stamp=None
        self.rate=None;self.base=None;self.votes=[];self.last_observation=None
    def observe(self,notes,now):
        current=[n for n in notes if .15<=n.center[1]<=self.c.get('prediction_zone',[.22,.54])[1]
                 and n.color=='blue' and n.kind=='tap']
        rates=[];used=set();old=self.previous;dt=None if self.stamp is None else now-self.stamp
        if dt is not None and .008<=dt<=.06:
            for n in current:
                candidates=[(i,p) for i,p in enumerate(old) if i not in used and p.lane==n.lane
                    and -.004<=n.center[1]-p.center[1]<=.10
                    and .6<=n.width/max(p.width,1e-6)<=1.7]
                if not candidates:continue
                i,p=min(candidates,key=lambda pair:abs(pair[1].center[1]-n.center[1]))
                used.add(i)
                rates.append(float((self.motion.phase(n.center[1])-self.motion.phase(p.center[1]))/dt))
        self.previous=current;self.stamp=now
        if len(rates)<2:self.votes=[];return None
        estimate=float(np.median(rates));tolerance=max(.04,abs(estimate)*.12)
        if estimate<-.02 or sum(abs(r-estimate)<=tolerance for r in rates)<max(2,math.ceil(len(rates)*.75)):
            self.votes=[];return None
        estimate=max(0.,estimate);self.last_observation=now;self.last_sample=(now,estimate)
        if self.rate is not None and abs(estimate-self.rate)<=max(.04,self.rate*.15):
            self.votes=[];return None
        if self.votes and abs(estimate-self.votes[-1][1])>max(.04,estimate*.12):self.votes=[]
        self.votes.append((now-dt/2,estimate));self.votes=self.votes[-5:]
        if len(self.votes)<(5 if self.rate is None else 3):return None
        new=float(np.median([r for _,r in self.votes]));new=0. if new<.03 else new
        if self.base is None and new==0:return None
        old_rate=self.rate;self.rate=new
        if self.base is None:self.base=new
        effective=self.votes[0][0];self.votes=[]
        return dict(type='global_flow_change',time=now,effective=effective,old_rate=old_rate,
                    rate=new,multiplier=new/self.base,phase='paused' if new==0 else 'moving')


class MusicalClock:
    """Shadow-only song-local pulse clock and explicitly ambiguous bar phases.

    Meter=4 beats is a hypothesis. An observed pulse may be an eighth or a
    sixteenth; timing records alone cannot prove the musical downbeat.
    """
    def __init__(self,config):
        self.grid=BeatGrid(16,config.get('bpm'),0)
        self.step=None;self.epoch=None;self.frozen=False;self.freeze_reason=None
        self.suspended_until=-float('inf');self.rows=deque(maxlen=192)
        self.last_evidence=None;self.conflicts=0
    def flow_change(self,event):
        if event is None or event.get('old_rate') is None:return
        self.suspended_until=event['time']+2.
        if self.step is not None:
            self.frozen=True;self.freeze_reason='visual_scroll_changed'
    def observe(self,arrival,now,lane):
        if self.frozen or now<self.suspended_until or not math.isfinite(arrival):return
        for row in reversed(self.rows):
            if abs(row['arrival']-arrival)<.025:
                row['lanes'].add(lane);return
        if self.step is None:
            self.grid.observe(arrival)
            if self.grid.locked:
                self.step=self.grid.period;self.epoch=self.grid.phase
        else:
            residual=arrival-(self.epoch+round((arrival-self.epoch)/self.step)*self.step)
            if abs(residual)>.015:
                self.conflicts+=1;return
            self.epoch+=max(-.0005,min(.0005,residual*.1))
        self.rows.append(dict(arrival=arrival,lanes={lane}));self.last_evidence=now
    def status(self,now):
        if self.step is None:
            return dict(state='suspended' if now<self.suspended_until else 'collecting',
                        observations=len(self.rows),candidates=[],sends_input=False)
        ticks={}
        for row in self.rows:
            k=round((row['arrival']-self.epoch)/self.step)
            ticks[k]=max(ticks.get(k,0),len(row['lanes']))
        ordered=sorted(ticks);gaps=[b-a for a,b in zip(ordered,ordered[1:])]
        recent=[g for g in gaps[-12:] if 0<g<=8]
        stride=max(set(recent),key=lambda g:(recent.count(g),-g)) if recent else None
        candidates=[]
        # Keep both eighth/16th interpretations. Uniform pulses must not
        # manufacture a confident bar start merely by choosing the first row.
        for bar_ticks in (8,16):
            beat_ticks=bar_ticks//4
            for offset in range(bar_ticks):
                score=0.;evidence=0
                for i,k in enumerate(ordered):
                    if (k-offset)%bar_ticks:continue
                    chord=ticks[k]>=2
                    rest=i>0 and k-ordered[i-1]>=beat_ticks*2
                    if chord:score+=.25;evidence+=1
                    if rest:score+=1.;evidence+=1
                start=self.epoch+offset*self.step
                next_bar=start+(math.floor((now-start)/(bar_ticks*self.step))+1)*bar_ticks*self.step
                candidates.append(dict(bar_ticks=bar_ticks,offset_ticks=offset,next_bar=next_bar,
                    bpm_candidate=60/(beat_ticks*self.step),score=score,evidence=evidence))
        candidates.sort(key=lambda c:(-c['score'],c['bar_ticks'],c['offset_ticks']))
        best=candidates[0];runner=candidates[1]
        confidence=0. if best['evidence']<3 else min(.65,max(0.,best['score']-runner['score'])/max(1.,best['score']))
        return dict(state='holdover' if self.frozen else 'tracking',step_ms=self.step*1000,
            epoch=self.epoch,step_index=math.floor((now-self.epoch)/self.step),observations=len(self.rows),
            holdover_age=None if self.last_evidence is None else max(0.,now-self.last_evidence),
            bar_confidence=confidence,bar_ambiguous=confidence<.5,
            candidates=[c for length in (8,16) for c in [x for x in candidates if x['bar_ticks']==length][:3]],
            pulse_stride=stride,pulse_ms=None if stride is None else stride*self.step*1000,
            conflicts=self.conflicts,sends_input=False,meter_assumption='4 beats; eighth/16th unresolved')


class MechanismCadence:
    """Opt-in bounded continuation of an observed wide-blue rhythm only."""
    def __init__(self,mode):
        self.mode=mode;self.records=deque(maxlen=24);self.plan=None;self.cooldown=0.
        self.speeds=deque(maxlen=8);self.trend_votes=0;self.snap_records=deque(maxlen=24)
    def observe(self,track,arrival,now,snapped=None):
        if self.plan is not None or now<self.cooldown:return
        if track.get('ignored_reason') or track.get('kind')=='slide_end':return
        if any(identity==track['id'] for identity,_ in self.records):return
        self.records.append((track['id'],arrival))
        self.snap_records.append((track['id'],arrival,arrival if snapped is None else snapped))
    def start(self,event,clock,flow,now,phase_anchor=None):
        if self.plan is not None or now<self.cooldown or clock is None or clock.step is None:return None
        sample=getattr(flow,'last_sample',None)
        if sample is None or now-sample[0]>.220:return None
        if self.speeds and sample[0]<=self.speeds[-1][0]:return None
        if sample[1]<.15:
            self.speeds.clear();self.trend_votes=0;return None
        if self.speeds and sample[0]-self.speeds[-1][0]>.080:
            self.speeds.clear();self.trend_votes=0
        self.speeds.append(sample)
        if len(self.speeds)<8:return None
        times=np.array([t for t,_ in self.speeds]);times-=times[0]
        values=np.array([v for _,v in self.speeds])
        initial=float(np.mean(values[:3]));final=float(np.mean(values[-3:]))
        centered=times-times.mean()
        slope=float(centered@(values-values.mean())/(centered@centered))
        residual=float(np.sqrt(np.mean((values-values.mean()-slope*centered)**2)))
        drops=-np.diff(values);total=float(values[0]-values[-1])
        continuous=(times[-1]>=.075 and slope<0 and initial-final>.06*initial
                    and np.count_nonzero(drops>.003*initial)>=4
                    and total>0 and float(max(drops))<.65*total
                    and residual<.06*initial)
        self.trend_votes=self.trend_votes+1 if continuous else 0
        if self.trend_votes<2:return None
        # One rounding unit is the learned grid cell, not the recent
        # rhythm's pulse_stride * step (which can be two or more cells).
        pulse=clock.step
        if not math.isfinite(pulse) or pulse<=0:return None
        # Integer-neighbourhood tolerance: 10% of P, capped at 15ms.
        tolerance=min(.015,pulse*.10)
        records=list(self.records)
        rows=records[-2:]
        if len(rows)<2 or not now-.75<=rows[-1][1]<=now+1.:return None
        d1=rows[1][1]-rows[0][1]
        if d1<=0:return None
        nearest=round(d1/pulse)
        stride=max(1,nearest if abs(d1-nearest*pulse)<=tolerance else math.ceil(d1/pulse))
        interval=stride*pulse
        raw_gaps=[(b[1]-a[1])*1000 for a,b in zip(rows,rows[1:])]
        if not .04<=interval<=1.2:return None
        anchor_id,anchor=rows[0]
        raw_anchor=anchor
        epoch=getattr(clock,'epoch',None)
        # Snap musical time once. Offset compensation is still applied only
        # by the input scheduler; subsequent slots keep this frozen phase.
        if epoch is not None and math.isfinite(epoch):
            anchor=epoch+round((anchor-epoch)/pulse)*pulse
        anchor_correction_ms=(anchor-raw_anchor)*1000
        slots={identity:anchor+i*interval for i,(identity,_) in enumerate(rows)}
        last_id=rows[-1][0];last_time=slots[last_id]
        self.plan=dict(start=now,until=now+4.,interval=interval,stride=stride,
            sixteenth_ms=pulse*500,reference_rate=initial,anchor_id=anchor_id,anchor=anchor,
            slots=slots,last_id=last_id,last_time=last_time,
            grid_step_ms=pulse*1000,anchor_correction_ms=anchor_correction_ms,
            integer_tolerance_ms=tolerance*1000,raw_gaps_ms=raw_gaps)
        clock.flow_change(dict(time=now,old_rate=initial,rate=final))
        return dict(type='mechanism_cadence_started',time=now,interval_ms=interval*1000,
            stride=stride,anchor=anchor,anchor_id=anchor_id,until=self.plan['until'],mode=self.mode,
            trigger='visual_continuous_deceleration',pulse_ms=pulse*1000,
            anchor_correction_ms=anchor_correction_ms,
            acceleration=slope,old_rate=initial,rate=final,
            integer_tolerance_ms=tolerance*1000,raw_gaps_ms=raw_gaps,
            scope='first head snapped once; fixed integer grid stride; candidate bar')

    def _obsolete_acceleration_start(self,event,clock,flow,now,phase_anchor=None):
        sample=getattr(flow,'last_sample',None)
        if sample is None or sample[0]!=now:return None
        if self.speeds and sample[0]==self.speeds[-1][0]:return None
        if sample[1]<.15:
            self.speeds.clear();self.trend_votes=0;return None # stop has a separate handler
        if self.speeds and now-self.speeds[-1][0]>.06:self.speeds.clear()
        self.speeds.append(sample)
        if self.plan is not None or now<self.cooldown or len(self.speeds)<8:return None
        values=np.array([v for _,v in self.speeds]);times=np.array([t-now for t,_ in self.speeds])
        initial=float(np.mean(values[:3]));final=float(np.mean(values[-3:]))
        centered=times-times.mean();slope=float(centered@(values-values.mean())/(centered@centered))
        residual=float(np.sqrt(np.mean((values-(values.mean()+slope*centered))**2)))
        # Multiple significant downward steps, a sustained trend and a small
        # residual distinguish an easing curve from one abrupt speed jump.
        continuous=(times[-1]-times[0]>=.075 and slope<0 and
                    .08*initial<initial-final<.35*initial and
                    np.count_nonzero(np.diff(values)<-.01*initial)>=3 and residual<.08*initial)
        self.trend_votes=self.trend_votes+1 if continuous else 0
        recent_errors=[raw-snap for _,raw,snap in list(self.snap_records)[-3:]]
        snap_drift=(len(recent_errors)==3 and
                    all(.001<b-a<.025 for a,b in zip(recent_errors,recent_errors[1:])))
        # A growing pre-snap delay may confirm a gentler continuous easing,
        # but never a single jump or an instantaneous stop.
        easing=slope<0 and residual<.08*initial and np.count_nonzero(np.diff(values)<-.002*initial)>=3
        if self.trend_votes<2 and not (snap_drift and easing):return None
        if recent_errors and any(abs(e)>.001 for e in recent_errors) and not snap_drift:return None
        if clock is None or clock.step is None:return None
        rows=list(self.records)[-5:]
        if len(rows)<4:return None
        if not now-.75<=rows[-1][1]<=now+1.:return None
        gaps=np.diff([t for _,t in rows]);observed=float(np.median(gaps))
        # Infer the stride from the preceding stable observations, NOT a
        # hard-coded eighth/16th interpretation of the learned grid unit.
        stable=list(self.snap_records)[-5:]
        snapped_gaps=np.diff([s for _,_,s in stable]) if len(stable)>=4 else gaps
        interval=float(np.median(snapped_gaps[:3]))
        unit=clock.step/2
        stride=max(1,round(interval/unit))
        quantized=stride*unit
        if abs(quantized-interval)<=.020:interval=quantized
        if not .04<=interval<=.6 or np.max(abs(gaps-observed))>max(.02,observed*.12):return None
        if abs(observed-interval)>max(.03,interval*.25):return None
        errors=[raw-snap for _,raw,snap in stable[-3:]]
        drift=len(errors)==3 and all(.001<b-a<.025 for a,b in zip(errors,errors[1:]))
        # Continue the already completed head's PLANNED musical time, not
        # its late API/frame dispatch time and not a fresh grid phase snap.
        # With no completed head yet, keep the first reliable observation.
        anchor_id,anchor=rows[0]
        anchor_index=0
        if phase_anchor is not None:
            for i,(identity,_) in enumerate(rows):
                if identity==phase_anchor[0]:
                    anchor_id,anchor=phase_anchor;anchor_index=i;break
        slots={identity:anchor+(i-anchor_index)*interval for i,(identity,_) in enumerate(rows)}
        last_id=rows[-1][0];last_time=slots[last_id]
        self.plan=dict(start=now,until=now+4.,interval=interval,
            sixteenth_ms=unit*1000,stride=stride,reference_rate=initial,
            snap_drift_ms=[e*1000 for e in errors],anchor_id=anchor_id,anchor=anchor,
            slots=slots,last_id=last_id,last_time=last_time)
        clock.flow_change(dict(time=now,old_rate=initial,rate=final))
        return dict(type='mechanism_cadence_started',time=now,interval_ms=interval*1000,
                    stride=stride,anchor=anchor,anchor_id=anchor_id,until=self.plan['until'],mode=self.mode,
                    snap_drift=drift,snap_drift_ms=[e*1000 for e in errors],
                    trigger='continuous_deceleration',acceleration=slope,
                    scope='observed wide blue only; musical BPM/bar phase unconfirmed')
    def assign(self,tracks,now):
        p=self.plan
        if p is None:return []
        if now>p['until']:
            self.plan=None;self.records.clear();self.cooldown=now+2.;return []
        for t in sorted(tracks,key=lambda t:t['id']):
            if t['fired'] or t.get('ignored_reason') or t.get('kind')=='slide_end':continue
            if len(t.get('history',()))<3:continue
            if t['id']<p['last_id'] or t['id'] in p['slots']:continue
            target=p['last_time']+p['interval']
            if target>p['until'] or len(p['slots'])>=16:continue
            p['slots'][t['id']]=target;p['last_id']=t['id'];p['last_time']=target
        return [(t,p['slots'][t['id']]) for t in tracks if not t['fired'] and not t.get('ignored_reason') and t['id'] in p['slots']]
    def status(self):
        if self.plan is None:return dict(mode=self.mode,state='collecting',sends_input=self.mode=='active')
        return dict(mode=self.mode,state='continuing',stride=self.plan['stride'],interval_ms=self.plan['interval']*1000,
            grid_step_ms=self.plan.get('grid_step_ms'),
            sixteenth_ms=self.plan['sixteenth_ms'],anchor=self.plan['anchor'],until=self.plan['until'],
            slots=[dict(id=k,arrival=v) for k,v in self.plan['slots'].items()],
            sends_input=self.mode=='active',bar_ambiguous=True)


class RhythmController:
    def __init__(self, config):
        self.c=config; self.keys=config["keys"]; self.grid=BeatGrid(16,config.get("bpm"),config.get('grid_snap_ms',3)); self.last_visual=None
        self.tracks=[]; self.sequence=0; self.until={};self.retrigger_until={}
        self.held_pending={};self.held_restored={};self.held_last_target={}
        self.all_release_batch=None;self.last_full_restore=-float('inf');self.completed_release_groups=deque(maxlen=8)
        self.mechanism_fill=[];self.mechanism_fill_plan=None
        self.holds={};self.zone=config.get('prediction_zone',[.26,.62]);self.motion=MotionCurve(config)
        self.distinct_pairs=set()
        self.flow_mode=config.get('global_flow','off')
        if self.flow_mode not in ('off','shadow','active'):raise ValueError('global_flow must be off/shadow/active')
        if self.flow_mode=='active' and (config.get('input_mode')!='all-held' or config.get('release_scope','target')!='target'):
            raise ValueError('active global flow requires all-held target mode')
        self.flow=GlobalFlow(config,self.motion) if self.flow_mode!='off' else None
        if config.get('measure_clock','off') not in ('off','shadow'):raise ValueError('measure_clock must be off/shadow')
        self.music_clock=MusicalClock(config) if config.get('measure_clock')=='shadow' else None
        self.clock_flow=GlobalFlow(config,self.motion) if self.music_clock is not None and self.flow is None else None
        mode=config.get('mechanism_mode','off')
        if mode not in ('off','shadow','active'):raise ValueError('mechanism_mode must be off/shadow/active')
        if mode!='off' and (config.get('input_mode')!='all-held' or config.get('release_scope','target')!='target' or self.flow_mode=='active'):
            raise ValueError('mechanism requires all-held target mode without active global flow')
        self.mechanism=MechanismCadence(mode) if mode!='off' else None
        if self.mechanism is not None and self.music_clock is None:self.music_clock=MusicalClock(config)
        if self.mechanism is not None and self.flow is None and self.clock_flow is None:self.clock_flow=GlobalFlow(config,self.motion)

    def scheduled_arrival(self,track):
        if track.get('mechanism_arrival') is not None:return track['mechanism_arrival']
        return self.grid.nearest(track['arrival'])

    def mechanism_phase_anchor(self):
        if self.mechanism is None:return None
        ids={identity for identity,_ in list(self.mechanism.records)[-5:]}
        completed=[t for t in self.tracks if t['id'] in ids and t.get('completed_head_target') is not None
                   and t['fired'] and not t.get('ignored_reason')]
        if not completed:return None
        track=max(completed,key=lambda t:t['completed_head_target'])
        return track['id'],track['completed_head_target']+self.c.get('input_offset_ms',0)/1000

    def apply_mechanism(self,now):
        if self.mechanism is None:return []
        previous=self.mechanism.plan
        planned=self.mechanism.assign(self.tracks,now);events=[]
        if previous is not None and self.mechanism.plan is None:
            events.append(dict(type='mechanism_cadence_finished',time=now))
            for t in self.tracks:t.pop('mechanism_arrival',None)
        if self.mechanism.mode!='active':return events
        for t,arrival in planned:
            covered=next((s for s in self.mechanism_fill if abs(s['arrival']-arrival)<.008),None)
            if covered is not None:
                t['fired']=True
                events.append(dict(type='mechanism_fill_covered',id=t['id'],time=now,arrival=arrival))
                continue
            if t.get('mechanism_arrival') is None:
                events.append(dict(type='mechanism_head_planned',id=t['id'],time=now,arrival=arrival))
            t.update(mechanism_arrival=arrival,arrival=arrival,locked=True,lock_until=arrival+.035,
                     prediction_source='mechanism_cadence')
            if t.get('held_ready') is not None:
                target=arrival-self.c.get('input_offset_ms',0)/1000
                ready=max(target,t.get('held_gap_started',now)+self.c.get('release_gap_ms',8)/1000)
                t.update(held_target=target,held_ready=ready)
                self.held_pending[self.keys[t.get('input_lane',t['lane'])]]=(t['id'],ready)
        return events

    def mechanism_fill_heads(self,now):
        """Bounded speculative heads, fed through the ordinary target-key scheduler."""
        mech=self.mechanism
        if mech is None or mech.mode!='active' or mech.plan is None:return []
        p=mech.plan
        if self.mechanism_fill_plan is not p:
            self.mechanism_fill=[];self.mechanism_fill_plan=p
        known=[t for t in self.tracks if t['id'] in p['slots'] and not t.get('ignored_reason')]
        if not known:return []
        template=max(known,key=lambda t:p['slots'][t['id']])
        # Only fill AFTER the recognized queue has actually completed.
        if any(not t['fired'] for t in known):return self.mechanism_fill
        detector=self.flow or self.clock_flow
        sample=getattr(detector,'last_sample',None)
        if sample is None or now-sample[0]>.220:return self.mechanism_fill
        if not .15<sample[1]<p.get('reference_rate',sample[1])*.85:return self.mechanism_fill
        future=[t['arrival']-self.c.get('input_offset_ms',0)/1000 for t in self.tracks
                if not t['fired'] and not t.get('ignored_reason') and t.get('arrival') is not None]
        if future and min(future)-now<=.200:return self.mechanism_fill
        # Eight learned eighth-pulses per candidate 4/4 bar. This remains a
        # hypothesis; never extend the four-second hard budget.
        if 'fill_until' not in p:
            candidates=self.music_clock.status(now).get('candidates',[])
            pulse=self.music_clock.status(now).get('pulse_stride',1) or 1
            bar_ticks=16 if pulse>=2 else 8
            candidate=next((c for c in candidates if c['bar_ticks']==bar_ticks),None)
            if candidate is None:return []
            boundary=candidate['next_bar'];period=self.music_clock.step*bar_ticks
            p['fill_until']=min(boundary,p['until'])
        offset=self.c.get('input_offset_ms',0)/1000
        last=max([p['last_time']]+[s['arrival'] for s in self.mechanism_fill])
        arrival=last+p['interval']
        lead=max(self.c.get('release_lead_ms',60),self.c.get('release_gap_ms',8))/1000
        if now>=p['fill_until'] or arrival>p['fill_until']-self.music_clock.step/2 or len(self.mechanism_fill)>=16:return self.mechanism_fill
        if now<arrival-offset-lead:return self.mechanism_fill
        s=dict(template)
        for name in ('held_ready','held_target','completed_head_target','pink_chord_leader'):
            s.pop(name,None)
        s.update(id=-(len(self.mechanism_fill)+1),arrival=arrival,mechanism_arrival=arrival,
                 fired=now>arrival-offset+.035,locked=True,lock_until=arrival+.035,
                 prediction_source='mechanism_speculative_fill',last=now)
        # Speculation may not steal a neighbouring slider's early window.
        if any(not t['fired'] and not t.get('ignored_reason') and t['id'] not in p['slots']
               and t.get('arrival') is not None and abs(t['arrival']-arrival)<=.250
               and s['lane'] in self.trigger_lanes(t) for t in self.tracks):
            s['fired']=True
        self.mechanism_fill.append(s)
        return self.mechanism_fill

    def sync_global_flow(self,now,change=None):
        if self.flow_mode!='active' or self.flow.rate is None:return
        hit=float(self.motion.phase(self.c['hit_line_y']));rate=self.flow.rate
        for t in self.tracks:
            if t['fired'] or t.get('ignored_reason') or not t.get('locked'):continue
            if t.get('phase_rate') is None:continue
            # Preserve the actual last visual sample separately from virtual
            # anchors, so stopping cannot create an unlimited blind coast.
            visual=t.setdefault('flow_visual',t['last'])
            if now-visual>2.:
                t.update(arrival=None,locked=False);continue
            old_rate=t['phase_rate'];last=t['last']
            boundary=now if change is None else max(last,min(now,change['effective']))
            phase=float(self.motion.phase(t['y']))+old_rate*max(0.,boundary-last)+rate*max(0.,now-boundary)
            t.update(y=float(self.motion.position(phase)),last=now,phase_rate=rate,
                     velocity=rate/self.motion.derivative(float(self.motion.position(phase))))
            t['arrival']=None if rate==0 else now+(hit-phase)/rate
            t['lock_until']=min(visual+2.,now+.75 if rate==0 else t['arrival']+.035)
            t['prediction_source']='global_flow_paused' if rate==0 else 'global_flow'
            if t.get('held_ready') is not None:
                target=float('inf') if rate==0 else self.grid.nearest(t['arrival'])-self.c.get('input_offset_ms',0)/1000
                ready=max(target,t.get('held_gap_started',now)+self.c.get('release_gap_ms',8)/1000)
                t.update(held_target=target,held_ready=ready)
                key=self.keys[t.get('input_lane',t['lane'])]
                self.held_pending[key]=(t['id'],ready)

    def note_geometry(self,note):
        span=discrete_span(self.c,note.center[0],note.center[1],note.width)
        if span is None:return None
        centre=(span[0]+span[1])/4
        canonical=min(5,max(0,int(math.floor(centre-1e-6))))
        if note.lane==canonical:return span
        # Accept historical centre-floor labels on the other side of a
        # boundary, but not inconsistent synthetic/faulty lane metadata.
        if abs(centre-round(centre))<.08 and note.lane in (round(centre)-1,round(centre)):
            return span
        return None

    def merge_duplicates(self,now):
        events=[];removed=set()
        for index,a in enumerate(self.tracks):
            if a['id'] in removed:continue
            for b in self.tracks[index+1:]:
                if b['id'] in removed or a['color']!=b['color'] or abs(a['lane']-b['lane'])!=1:continue
                if not a.get('cell_span') or a['cell_span']!=b.get('cell_span'):continue
                if tuple(sorted((a['id'],b['id']))) in self.distinct_pairs:continue
                if not (a.get('locked') and b.get('locked')) or a['arrival'] is None or b['arrival'] is None:continue
                if abs(a['arrival']-b['arrival'])>=.025 or abs(self.motion.predict(a,now)-self.motion.predict(b,now))>=.025:continue
                keep,drop=sorted((a,b),key=lambda t:(t['fired'],t.get('held_ready') is not None,t['last']),reverse=True)
                removed.add(drop['id'])
                keep['grid_observed']=keep.get('grid_observed',False) or drop.get('grid_observed',False)
                for key,(identity,_) in list(self.held_pending.items()):
                    if identity==drop['id']:del self.held_pending[key]
                self.holds.pop(drop['id'],None)
                if self.all_release_batch is not None:
                    self.all_release_batch['tracks']=[pair for pair in self.all_release_batch['tracks'] if pair[0]['id']!=drop['id']]
                    if not self.all_release_batch['tracks']:self.all_release_batch=None
                events.append(dict(type='duplicate_track_merged',id=drop['id'],kept_id=keep['id'],time=now,cell_span=list(keep['cell_span'])))
                if a is drop:break
        if removed:self.tracks=[t for t in self.tracks if t['id'] not in removed]
        return events

    def update_note_kind(self,track,note,now):
        """A one-frame colour hit cannot permanently suppress a head."""
        if track.get('ignored_reason')=='slide_end':return []
        if note.kind!='slide_end':
            track['end_votes']=0
            track['head_observations']=track.get('head_observations',0)+1
            if track.get('locked') and track['head_observations']>=3:track['head_confirmed']=True
            return []
        if track.get('head_confirmed') or (track.get('locked') and track.get('head_observations',0)>=3):
            note.raw_kind='slide_end';note.kind=track['kind']
            if track.get('tail_veto_logged'):return []
            track['tail_veto_logged']=True
            return [dict(id=track['id'],type='slide_end_rejected_confirmed_head',time=now)]
        count=track.get('end_votes',0)+1 if now-track.get('end_vote_time',-float('inf'))<=.05 else 1
        track.update(end_votes=count,end_vote_time=now)
        if count<3:return []
        track.update(kind='slide_end',fired=True,ignored_reason='slide_end')
        for key,(identity,_) in list(self.held_pending.items()):
            if identity==track['id']:del self.held_pending[key]
        track.pop('held_ready',None);track.pop('held_target',None)
        if self.all_release_batch is not None:
            self.all_release_batch['tracks']=[pair for pair in self.all_release_batch['tracks'] if pair[0]['id']!=track['id']]
            if not self.all_release_batch['tracks']:self.all_release_batch=None
        return [dict(id=track['id'],type='ignored_slide_end',time=now,color=note.color)]

    def refine_blue(self,track,note,now):
        """Two clean near observations may refine, never replace, a clock.

        Pink/holds and the judgement glow cannot take this path. Each update
        is capped to 8ms from the original middle-zone clock, not cumulative.
        """
        if note.color!='blue' or track['fired'] or not self.c.get('near_blue_refinement',False) or not self.zone[1]<note.center[1]<=.735:return
        y=note.center[1];left,right=field_edges(self.c,y);width=right-left
        old_width=track.get('normalized_width',0);old_height=track.get('normalized_height',0)
        if old_width<=0 or old_height<=0:return
        if not .85<=note.width/width/old_width<=1.15 or not .7<=note.height/width/old_height<=1.3:return
        if abs(y-self.motion.predict(track,now))>.015:return
        pending=track.setdefault('near_history',deque(maxlen=3))
        if pending and (now-pending[-1][0]>.05 or y<=pending[-1][1]):pending.clear()
        pending.append((now,y))
        if len(pending)<2 or pending[-1][0]-pending[0][0]<.008:return
        points=list(track['history'])+list(pending);points=points[-8:]
        tm=np.array([p[0]-now for p in points]);ys=np.array([p[1] for p in points]);phases=self.motion.phase(ys)
        centered=tm-tm.mean();denom=float(centered@centered)
        if denom<=1e-10:return
        rate=float(centered@(phases-phases.mean())/denom)
        if rate<=0:return
        intercept=float(phases.mean()-rate*tm.mean())
        if np.max(abs(ys-self.motion.position(rate*tm+intercept)))>.006:return
        estimate=now+float((self.motion.phase(self.c['hit_line_y'])-self.motion.phase(y))/rate)
        reference=track.setdefault('middle_arrival',track['arrival'])
        if abs(estimate-reference)>.008 or estimate<now:return
        track.update(arrival=estimate,velocity=rate/self.motion.derivative(y),phase_rate=rate,
                     x=note.center[0],y=y,last=now,prediction_source='near_blue_refinement',
                     lock_until=min(now+self.c.get('locked_prediction_ms',750)/1000,estimate+.035))
        track['history'].extend(pending);pending.clear()
    def rejoin_face_fragments(self,notes,now):
        """Restore a briefly split face only with three prior whole samples.

        This is temporal shape evidence, not broad chord/time coalescing.
        Independent adjacent notes without a known whole parent stay separate.
        """
        result=list(notes);events=[]
        for t in self.tracks:
            template=t.get('face_template')
            if template is None or template[3]<3 or now-template[2]>.06:continue
            if t['color'] not in ('green','yellow'):continue
            pieces=[]
            for n in result:
                if n.color!=t['color'] or abs(n.center[1]-self.motion.predict(t,now))>.015:continue
                left,right=field_edges(self.c,n.center[1]);scale=12/(right-left)
                a=(n.center[0]-n.width/2-left)*scale;b=(n.center[0]+n.width/2-left)*scale
                if a>=template[0]-.3 and b<=template[1]+.3 and b-a<.75*(template[1]-template[0]):pieces.append((a,b,n))
            if len(pieces)<2:continue
            pieces.sort(key=lambda p:p[0]);a=pieces[0][0];b=max(p[1] for p in pieces);width=template[1]-template[0]
            if abs(a-template[0])>.3 or abs(b-template[1])>.3:continue
            if any(q[0]-p[1]>.2*width for p,q in zip(pieces,pieces[1:])):continue
            if max(p[2].center[1] for p in pieces)-min(p[2].center[1] for p in pieces)>.003:continue
            x0=min(n.center[0]-n.width/2 for _,_,n in pieces);x1=max(n.center[0]+n.width/2 for _,_,n in pieces)
            y=float(np.mean([n.center[1] for _,_,n in pieces]));height=max(n.height for _,_,n in pieces)
            kind='slide_end' if all(n.kind=='slide_end' for _,_,n in pieces) else 'tap'
            note=Note(t['lane'],kind,((x0+x1)/2,y),x1-x0,height,1.,t['color'])
            identities={id(n) for _,_,n in pieces}
            result=[n for n in result if id(n) not in identities]+[note]
            events.append(dict(type='face_fragments_rejoined',id=t['id'],time=now,pieces=len(pieces)))
        return result,events

    def face_continuation(self,t,note,now):
        if t['color'] not in ('green','yellow') or abs(t['lane']-note.lane)!=1:return False
        if now-t['last']>.06 or abs(note.center[1]-self.motion.predict(t,now))>.015:return False
        template=t.get('face_template')
        if template is None or template[3]<3:return False
        left,right=field_edges(self.c,note.center[1]);scale=12/(right-left)
        a=(note.center[0]-note.width/2-left)*scale;b=(note.center[0]+note.width/2-left)*scale
        return abs(a-template[0])<.4 and abs(b-template[1])<.4

    def decide(self, notes, now, paths=(), dispatch_time=None):
        # Frame intervals are not musical intervals. Grid estimation is disabled
        # until distinct tracked note arrival times are available.
        events=[]
        if self.flow is not None:
            change=self.flow.observe(notes,now)
            self.sync_global_flow(now,change)
            if self.music_clock is not None:self.music_clock.flow_change(change)
            if self.mechanism is not None:
                event=self.mechanism.start(change,self.music_clock,self.flow,now,self.mechanism_phase_anchor())
                if event is not None:events.append(event)
            if change is not None:events.append(dict(change,mode=self.flow_mode))
        elif self.clock_flow is not None:
            change=self.clock_flow.observe(notes,now)
            if self.music_clock is not None:self.music_clock.flow_change(change)
            if self.mechanism is not None:
                event=self.mechanism.start(change,self.music_clock,self.clock_flow,now,self.mechanism_phase_anchor())
                if event is not None:events.append(event)
        self.tracks=[t for t in self.tracks if now-t['last']<.30 or (t.get('locked') and not t['fired'] and now<=t.get('lock_until',0))]
        notes,fragment_events=self.rejoin_face_fragments(notes,now)
        events.extend(fragment_events)
        available={t['id'] for t in self.tracks}
        seen=set();pink_observed=[]
        for note in sorted(notes,key=lambda n:n.center[1],reverse=True):
            y=note.center[1]
            # Protection boundary applies even to unconfirmed tracks: lower
            # effects must neither consume an association nor poison history.
            if y>self.zone[1] and not self.c.get('near_blue_refinement',False):continue
            def distance(t):return abs(y-self.motion.predict(t,now))
            span=self.note_geometry(note)
            candidates=[t for t in self.tracks if t['id'] in available and t['color']==note.color
                and (t['lane']==note.lane or self.face_continuation(t,note,now) or (span is not None and span==t.get('cell_span') and abs(t['lane']-note.lane)==1 and distance(t)<.025))
                and distance(t)<.05 and y>=t['y']-.012]
            track=min(candidates,key=distance) if candidates else None
            if track is None:
                if y>self.zone[1]:continue
                self.sequence+=1
                track=dict(id=self.sequence,lane=note.lane,y=y,last=now,history=deque(maxlen=8),fired=False,arrival=None,color=note.color,kind='tap' if note.kind=='slide_end' else note.kind,
                           locked=False,lock_until=0.,stable_fit_count=0,prediction_source='unconfirmed')
                self.tracks.append(track)
            available.discard(track['id'])
            seen.add(track['id'])
            if note.kind=='pink_trial':pink_observed.append((track,y))
            if y>self.zone[1] and track.get('locked'):
                # Near-zone observations may be sparkles or clipped bars.
                # Keep the established clock and last trustworthy measurement.
                self.refine_blue(track,note,now)
                continue
            if track.get('locked'):
                # Gate individual observations BEFORE they enter the fit. A
                # sparkle must not poison all eight subsequent frame fits.
                elapsed=now-track['last']
                innovation=distance(track)
                if elapsed<.12 and innovation>max(.012,abs(track.get('velocity',0))*elapsed*.40):
                    track['prediction_source']='rejected_observation'
                    continue
            track.update(x=note.center[0],y=y,last=now); track['history'].append((now,y))
            if self.flow_mode=='active':track['flow_visual']=now
            left,right=field_edges(self.c,y)
            track.update(normalized_width=note.width/(right-left),normalized_height=note.height/(right-left))
            if note.color in ('green','yellow'):
                a=(note.center[0]-note.width/2-left)/(right-left)*12;b=(note.center[0]+note.width/2-left)/(right-left)*12
                prior=track.get('face_template');count=1
                if prior and now-prior[2]<=.06 and abs(a-prior[0])<.4 and abs(b-prior[1])<.4:count=prior[3]+1
                track['face_template']=(a,b,now,count)
            if span is not None:track['cell_span']=span
            events.extend(self.update_note_kind(track,note,now))
            if note.kind=='hold' and not track.get('ignored_reason'): track['kind']='hold'
            history=track['history']
            if len(history)>=3 and now-history[0][0]>.018 and .10<=y<=self.zone[1]:
                times=np.array([p[0]-now for p in history]); ys=np.array([p[1] for p in history])
                centered=times-times.mean();denom=float(centered@centered)
                phases=self.motion.phase(ys)
                rate=float(centered@(phases-phases.mean())/denom) if denom>1e-10 else 0.
                intercept=float(phases.mean()-rate*times.mean())
                velocity=rate/self.motion.derivative(y)
                remaining=float((self.motion.phase(self.c['hit_line_y'])-self.motion.phase(y))/rate) if velocity>.025 else float('inf')
                middle=self.zone[0]<=y<=self.zone[1]
                residual=np.max(np.abs(ys-self.motion.position(rate*times+intercept)))
                if velocity>.025 and -.035<=remaining<=(.8 if middle else 3.) and residual<.012:
                    estimate=now+remaining
                    if track.get('locked') and track.get('arrival') is not None and abs(estimate-track['arrival'])>.035:
                        # A single jump is ignored; a coherent sequence can
                        # recover from an early imperfect clock in the middle.
                        pending=track.get('pending_arrival')
                        count=track.get('pending_count',0)+1 if pending is not None and abs(estimate-pending)<.012 else 1
                        track['pending_arrival']=estimate;track['pending_count']=count
                        if count<3:
                            track['prediction_source']='rejected_jump';continue
                    track['pending_count']=0;track.pop('pending_arrival',None)
                    track['arrival']=estimate;track['velocity']=velocity;track['phase_rate']=rate
                    if self.c.get('input_mode')!='all-held' and note.kind=='hold' and note.tail:
                        route=[];lane=note.lane
                        for point in note.tail:
                            px,py=point[:2]
                            left,right=field_edges(self.c,py)
                            if not left<=px<=right:continue
                            position=(px-left)/(right-left)*6
                            # Small boundary jitter must not create alternating
                            # key edges on successive ribbon scan rows.
                            if position>=lane+1.08 or position<lane-.08:
                                lane=min(5,max(0,int(position)))
                            when=now+float((self.motion.phase(self.c['hit_line_y'])-self.motion.phase(py))/rate)-self.c.get('input_offset_ms',0)/1000
                            route.append((when,lane))
                        track['hold_route']=sorted(route)
                    track['prediction_source']='preliminary_curve'
                    if middle:track['stable_fit_count']+=1
                    if middle and track['stable_fit_count']>=2:
                        track['locked']=True
                        if note.kind!='slide_end' and track.get('head_observations',0)>=3:
                            track['head_confirmed']=True
                        track['lock_until']=min(now+self.c.get('locked_prediction_ms',750)/1000,estimate+.035)
                        track['prediction_source']='middle_zone'
                    if y>self.zone[0]+.75*(self.zone[1]-self.zone[0]) and track.get('locked') and track['stable_fit_count']>=3 and residual<.006 and self.mechanism is not None:
                        self.mechanism.observe(track,estimate,now,self.grid.nearest(estimate))
                    if y>self.zone[0]+.75*(self.zone[1]-self.zone[0]) and track.get('locked') and track['stable_fit_count']>=3 and residual<.006 and note.color=='blue' and not track.get('grid_observed'):
                        if self.music_clock is not None:self.music_clock.observe(estimate,now,note.lane)
                        if not (self.mechanism is not None and self.mechanism.mode=='active' and self.mechanism.plan is not None):self.grid.observe(estimate)
                        track['grid_observed']=True
        alive={t['id'] for t in self.tracks}
        self.distinct_pairs={p for p in self.distinct_pairs if p[0] in alive and p[1] in alive}
        ordered=sorted(seen)
        self.distinct_pairs.update((a,b) for i,a in enumerate(ordered) for b in ordered[i+1:])
        self.sync_global_flow(now)
        self.observe_pink_chords(pink_observed,now)
        events.extend(self.merge_duplicates(now))
        events.extend(self.apply_mechanism(now))
        decision=self.poll(now if dispatch_time is None else dispatch_time,paths)
        decision['events']=events+decision['events']
        if self.music_clock is not None:decision['music_clock']=self.music_clock.status(now)
        if self.mechanism is not None:decision['mechanism']=self.mechanism.status()
        return decision

    def poll(self, now, paths=None):
        """Pump known deadlines between captures; bounded visual coasting."""
        if self.c.get('input_mode')=='all-held':return self.poll_all_held(now)
        events=[]
        for track in self.tracks:
            if track['fired'] or track['arrival'] is None: continue
            if track['color']=='pink' and not self.c.get('pink_tap_trial',False):continue
            if not track.get('locked'):continue
            if now>track.get('lock_until',0):continue
            target=self.scheduled_arrival(track)-self.c.get('input_offset_ms',0)/1000
            # An occupied key needs a real up edge before the next head. Do
            # not swallow same-colour/adjacent notes as continuation of a hold.
            occupied=[identity for identity,h in self.holds.items() if h['lane']==track['lane']]
            if occupied and now-.035<=target<=now+.012 and not track.get('retrigger_ready'):
                ready=now+.008
                for identity in occupied:
                    del self.holds[identity]
                    events.append(dict(id=identity,type='hold_interrupted_for_next_note',next_id=track['id'],time=now))
                self.until.pop(self.keys[track['lane']],None)
                self.retrigger_until[self.keys[track['lane']]]=ready;track['retrigger_ready']=ready
            if now<track.get('retrigger_ready',-float('inf')):continue
            if now-.035<=target<=now:
                key=self.keys[track['lane']]
                if self.until.get(key,0)>now: continue
                self.until[key]=now+self.c.get('tap_ms',25)/1000; track['fired']=True
                if track['kind']=='hold':
                    route=track.get('hold_route',[])
                    self.holds[track['id']]=dict(lane=track['lane'],color=track['color'],last=now,start=now,
                        route=route,route_index=0,trusted_route=bool(route))
                events.append(dict(id=track['id'],key=key,arrival=track['arrival'],time=now,target=target,
                                   middle_arrival=track.get('middle_arrival',track['arrival']),
                                   grid_arrival=self.grid.nearest(track['arrival']),grid_locked=self.grid.locked,
                                   lateness_ms=(now-target)*1000,coast_ms=(now-track['last'])*1000,
                                   prediction_source=track['prediction_source'],rhythm_correction_ms=(self.grid.nearest(track['arrival'])-track['arrival'])*1000))
            elif target<now-.035: track['fired']=True
        desired={key for key,end in self.until.items() if end>now}
        for identity,hold in list(self.holds.items()):
            if hold.get('trusted_route'):
                while hold['route_index']<len(hold['route']) and hold['route'][hold['route_index']][0]<=now:
                    next_lane=hold['route'][hold['route_index']][1]
                    if next_lane!=hold['lane']:events.append(dict(id=identity,type='hold_route_step',from_lane=hold['lane'],to_lane=next_lane,time=now))
                    hold['lane']=next_lane;hold['route_index']+=1
                # No release judgement: keep the final known key until a new
                # head requires retrigger, stop, or the existing 20s safety cap.
                hold['last']=now
            if now-hold['last']>self.c.get('hold_loss_ms',180)/1000 or now-hold['start']>20:
                del self.holds[identity]; events.append(dict(id=identity,type='hold_release',time=now));continue
            desired.add(self.keys[hold['lane']])
        desired={key for key in desired if now>=self.retrigger_until.get(key,-float('inf'))}
        return {"keys":desired,"events":events,"bpm":self.grid.bpm,"grid":self.grid.status(),"holds":[dict(id=i,**{k:v for k,v in h.items() if k!='route'}) for i,h in self.holds.items()]}

    def trigger_lanes(self,track):
        """Keys whose four-cell input footprint overlaps this note.

        Coordinates are in six-key units (two chart cells per key).
        Missing geometry keeps the visual centre key as the only candidate.
        """
        if 'x' not in track or track.get('normalized_width',0)<=0:
            return {track['lane']}
        left,right=field_edges(self.c,track['y'])
        position=(track['x']-left)/(right-left)*6
        half=track['normalized_width']*3
        # One key unit is two chart cells. Demand at least half a chart
        # cell of overlap; a blurred outline crossing a neighbouring cell
        # boundary by a few pixels is not evidence that its key can hit.
        return {i for i in range(6)
            if min(position+half,i+1.5)-max(position-half,i-.5)>=.25} or {track['lane']}

    def observe_pink_chords(self,observed,now):
        """Only co-visible flick heads on the same row may share one edge.

        Confirm twice from fresh visual rows, not estimated arrival proximity:
        separate fits of the very same row can differ by tens of milliseconds.
        Recognition tracks remain separate for analysis and tail decisions.
        """
        if self.c.get('input_mode')!='all-held' or self.c.get('release_scope','target')!='target':return
        rows=[];positions={t['id']:y for t,y in observed}
        for track,y in sorted(observed,key=lambda pair:pair[1]):
            if track.get('fired') or track.get('ignored_reason'):continue
            if not rows or y-positions[rows[-1][0]['id']]>.003:rows.append([])
            rows[-1].append(track)
        votes=getattr(self,'pink_row_votes',{});new_votes={}
        for row in rows:
            if len(row)<2:continue
            ids=tuple(sorted(t['id'] for t in row))
            common=set.intersection(*(self.trigger_lanes(t) for t in row))
            if not common:continue
            old=votes.get(ids,(0,-float('inf')))
            count=old[0]+1 if now-old[1]<=.05 else 1
            new_votes[ids]=(count,now)
            if count<2:continue
            # Do not retarget an already released key or replace a group
            # during its pending pulse. Existing membership stays frozen.
            if any(t.get('held_ready') is not None for t in row):continue
            by_id={t['id']:t for t in self.tracks}
            old_groups=[]
            for t in row:
                leader=by_id.get(t.get('pink_chord_leader'),t)
                members=leader.get('pink_chord_members',())
                if members:old_groups.append((leader,members))
            if any(not set(members)<=set(ids) or leader.get('held_ready') is not None or leader['fired']
                   for leader,members in old_groups):continue
            for t in row:
                t.pop('pink_chord_leader',None);t.pop('pink_chord_lane',None);t.pop('pink_chord_members',None)
            lane=min(common,key=lambda k:(sum(abs(k-t['lane']) for t in row),k))
            leader=min(row,key=lambda t:(abs(t['lane']-lane),t['id']))
            leader.update(pink_chord_lane=lane,pink_chord_members=ids)
            for t in row:
                if t is not leader:t['pink_chord_leader']=leader['id']
        self.pink_row_votes=new_votes

    def finish_pink_chords(self,now):
        events=[];by_id={t['id']:t for t in self.tracks}
        for t in self.tracks:
            leader=by_id.get(t.get('pink_chord_leader'))
            if leader is None or leader.get('ignored_reason'):
                t.pop('pink_chord_leader',None);continue
            if leader['fired'] and not t['fired']:
                t['fired']=True
                events.append(dict(id=t['id'],type='pink_chord_covered',leader_id=leader['id'],
                    key=self.keys[leader.get('input_lane',leader['lane'])],time=now))
        return events

    def select_input_lane(self,track,target,now):
        """Prefer a key exclusive to this head over upcoming distinct heads."""
        if track.get('held_ready') is not None or track['fired']:
            return track.get('input_lane',track['lane'])
        if 'pink_chord_lane' in track:
            track['input_reason']='shared_pink_chord'
            return track['pink_chord_lane']
        horizon=self.c.get('key_lookahead_ms',0)/1000
        slide_guard=self.c.get('slide_guard_ms',160)/1000
        if horizon<=0:return track['lane']
        candidates=self.trigger_lanes(track)
        future=[];coloured_times=[]
        for other in self.tracks:
            if other is track or other['fired'] or not other.get('locked') or other['arrival'] is None:continue
            if now>other.get('lock_until',0):continue
            if other['color']=='pink' and not self.c.get('pink_tap_trial',False):continue
            other_target=self.scheduled_arrival(other)-self.c.get('input_offset_ms',0)/1000
            delay=other_target-target
            if .010+1e-9<delay<=horizon:
                future.append((delay,self.trigger_lanes(other)))
            if .010+1e-9<delay<=slide_guard+1e-9 and other['color'] in ('green','yellow'):
                coloured_times.append(delay)
        future.sort(key=lambda pair:pair[0])
        # Edge presses on a two-cell face can be attracted to a coloured
        # slide behind it. Prefer its own column over geometric avoidance.
        # Keep a half-cell allowance for outline/measurement uncertainty.
        small_face=0<track.get('normalized_width',0)*12<=2.5
        if small_face and track['lane'] in candidates and coloured_times:
            lane=track['lane']
            track.update(input_lane=lane,input_reason='centre_before_coloured_slide',
                input_conflicts=sum(lane in lanes for _,lanes in future))
            return lane
        def score(lane):
            # Avoid the nearest subsequent time group first, then all later
            # heads in the horizon. No eligible safe key means best effort.
            first=sum(lane in lanes for delay,lanes in future if delay<=future[0][0]+.010) if future else 0
            total=sum((horizon-delay+.001) for delay,lanes in future if lane in lanes)
            key=self.keys[lane]
            busy=key in self.held_pending and self.held_pending[key][0]!=track['id']
            return (busy,first,total,abs(lane-track['lane']),lane)
        lane=min(candidates,key=score)
        track.update(input_lane=lane,input_conflicts=sum(lane in lanes for _,lanes in future),
            input_reason='lookahead' if lane!=track['lane'] else 'visual_centre')
        return lane

    def guard_baseline_restore(self,decision,actual_down,now):
        """Filter every baseline UP->DOWN transition at the input boundary.

        Includes initial/resume/stale-frame recovery, dense exit and global
        release. Keep held safe keys unchanged; a scheduled head's own edge
        is intentional and must not be swallowed by its future-note guard.
        """
        if self.c.get('input_mode')!='all-held':return decision
        if self.flow_mode=='active' and self.flow.rate==0:
            decision['keys']=set(decision['keys']) & set(actual_down)
            return decision
        desired=set(decision['keys']);rising=desired-set(actual_down)
        intentional={e['key'] for e in decision.get('events',[]) if
            'arrival' in e and e.get('key') in self.keys and
            abs(now-e.get('time',now))<=.035}
        blocked={}
        for track in self.tracks:
            if track['fired'] or track.get('ignored_reason') or track.get('arrival') is None:continue
            if track.get('locked'):
                if now>track.get('lock_until',0):continue
            elif now-track.get('last',-float('inf'))>.05:continue
            if track['color']=='pink' and not self.c.get('pink_tap_trial',False):continue
            target=self.scheduled_arrival(track)-self.c.get('input_offset_ms',0)/1000
            if not -.035<=target-now<=.250+1e-9:continue
            for lane in self.trigger_lanes(track):
                key=self.keys[lane]
                if key in rising and key not in intentional:
                    blocked.setdefault(key,[]).append(track['id'])
        decision['keys']=desired-set(blocked)
        decision['restore_blocked']=blocked
        signature=tuple((k,tuple(sorted(ids))) for k,ids in sorted(blocked.items()))
        if signature!=getattr(self,'restore_guard_signature',()):
            decision.setdefault('events',[]).append(dict(type='baseline_restore_guard',time=now,
                blocked=blocked,window_ms=250))
        self.restore_guard_signature=signature
        return decision

    def poll_all_held(self,now):
        """Baseline six held keys; only confirmed heads create release gaps."""
        chord_events=self.finish_pink_chords(now)
        dense=self.poll_dense_heads(now)
        if dense is not None:
            dense['events']=chord_events+dense['events']+self.finish_pink_chords(now)
            return dense
        if self.c.get('release_scope','target')=='all':
            return self.poll_release_all(now)
        events=chord_events
        fill=self.mechanism_fill_heads(now)
        active={t['id'] for t in self.tracks+fill}
        for key,(identity,ready) in list(self.held_pending.items()):
            if identity not in active and now>=ready:
                del self.held_pending[key];self.held_restored[key]=now
                events.append(dict(id=identity,key=key,type='gap_recovered_no_track',time=now))
        for track in sorted(self.tracks+fill,key=lambda t:t['arrival'] if t['arrival'] is not None else float('inf')):
            if track.get('pink_chord_leader') is not None:continue
            if track['fired'] or not track.get('locked') or track['arrival'] is None:continue
            if track['color']=='pink' and not self.c.get('pink_tap_trial',False):continue
            target=self.scheduled_arrival(track)-self.c.get('input_offset_ms',0)/1000
            lead=max(self.c.get('release_lead_ms',60),self.c.get('release_gap_ms',8))/1000
            if track.get('held_ready') is None and (target>now+lead or now>track.get('lock_until',0)):continue
            lane=self.select_input_lane(track,target,now)
            key=self.keys[lane]
            if track.get('held_ready') is not None:
                if now<track['held_ready']:continue
                track['fired']=True;self.held_pending.pop(key,None);self.held_restored[key]=now
                target=track['held_target'];self.held_last_target[key]=target
                track['completed_head_target']=target
                events.append(dict(id=track['id'],key=key,time=now,arrival=track['arrival'],target=target,
                    visual_lane=track['lane'],input_lane=lane,input_conflicts=track.get('input_conflicts',0),input_reason=track.get('input_reason'),
                    grid_arrival=target+self.c.get('input_offset_ms',0)/1000,grid_locked=self.grid.locked,
                    lateness_ms=(now-target)*1000,coast_ms=(now-track['last'])*1000,
                    prediction_source=track['prediction_source'],input_mode='all-held',
                    rhythm_correction_ms=(target+self.c.get('input_offset_ms',0)/1000-track['arrival'])*1000))
                continue
            if now>track.get('lock_until',0):continue
            target=self.scheduled_arrival(track)-self.c.get('input_offset_ms',0)/1000
            if abs(target-self.held_last_target.get(key,-float('inf')))<.008 and now-self.held_restored.get(key,-float('inf'))<.025:
                track['fired']=True
                events.append(dict(id=track['id'],key=key,type='coalesced_same_key_head',time=now,target=target));continue
            if target<now-.035:track['fired']=True;continue
            gap=self.c.get('release_gap_ms',8)/1000
            if target>now+max(self.c.get('release_lead_ms',60)/1000,gap) or key in self.held_pending:continue
            # Give the restored down edge a minimum dwell before another gap.
            if now-self.held_restored.get(key,-float('inf'))<self.c.get('min_down_ms',12)/1000:continue
            ready=max(target,now+gap)
            track.update(held_ready=ready,held_target=target,input_lane=lane)
            if self.flow_mode=='active' or (self.mechanism is not None and self.mechanism.mode=='active'):track['held_gap_started']=now
            self.held_pending[key]=(track['id'],ready)
            events.append(dict(id=track['id'],key=key,type='release_before_head',time=now,target=target,resume=ready,
                visual_lane=track['lane'],input_lane=lane,input_conflicts=track.get('input_conflicts',0),input_reason=track.get('input_reason')))
        events.extend(self.finish_pink_chords(now))
        desired=set(self.keys)-set(self.held_pending)
        return dict(keys=desired,events=events,bpm=self.grid.bpm,grid=self.grid.status(),holds=[],input_mode='all-held')

    def poll_dense_heads(self,now):
        """Suppress the six-key baseline around confirmed dense head clusters."""
        threshold=self.c.get('dense_gap_ms',100)/1000
        if threshold<=0:return None
        offset=self.c.get('input_offset_ms',0)/1000
        heads=sorted([(t,self.scheduled_arrival(t)-offset) for t in self.tracks
            if not t['fired'] and t.get('pink_chord_leader') is None and t.get('locked') and t['arrival'] is not None
            and now<=t.get('lock_until',0) and t['arrival']-offset>=now-.035
            and (t['color']!='pink' or self.c.get('pink_tap_trial',False))],key=lambda p:p[1])
        active=getattr(self,'dense_active',False);events=[]
        members=set()
        for (first,a),(second,b) in zip(heads,heads[1:]):
            # A simultaneous chord is not a successive head sequence.
            if .010+1e-9<b-a<threshold:
                members.update((first['id'],second['id']))
        close=bool(members)
        if not active:
            if not close:return None
            gap=self.c.get('release_gap_ms',8)/1000
            dwell=self.c.get('min_down_ms',12)/1000
            self.dense_active=True;self.dense_ready=now+gap
            # A mode change must not truncate a head just pressed by the
            # target-key scheduler. Preserve its minimum down duration.
            self.dense_pulses={k:t+dwell for k,t in self.held_restored.items() if t+dwell>now}
            self.dense_key_ready={k:end+gap for k,end in self.dense_pulses.items()}
            self.dense_until=now;self.dense_blocked={};self.dense_members=set();self.all_release_batch=None
            self.held_pending.clear()
            for track in self.tracks:
                if not track['fired']:
                    track.pop('held_ready',None);track.pop('held_target',None)
            events.append(dict(type='dense_mode_enter',time=now))
        self.dense_members.update(members)
        heads=[pair for pair in heads if pair[0]['id'] in self.dense_members]
        if heads:self.dense_until=max(self.dense_until,max(target for _,target in heads))
        for track,target in heads:
            left,right=field_edges(self.c,track.get('y',.4))
            position=(track.get('x',left+(track['lane']+.5)*(right-left)/6)-left)/(right-left)*6
            half=track.get('normalized_width',1/6)*3
            # Six keys cover twelve chart cells: each key's own two cells
            # plus one cell on either side. Test interval overlap, not just
            # whether a key centre lies inside the visible note.
            lanes={track['lane']}|{i for i in range(6)
                if position+half>i-.5+1e-9 and position-half<i+1.5-1e-9}
            for lane in lanes:
                key=self.keys[lane]
                self.dense_blocked[key]=max(self.dense_blocked.get(key,0),target+self.c.get('dense_recovery_ms',125)/1000)
        # Stay released after the last pulse: restoring all six immediately
        # would itself generate another unwanted down edge near that head.
        if not heads and now>self.dense_until+self.c.get('dense_recovery_ms',125)/1000:
            self.dense_active=False
            self.last_full_restore=now
            return dict(keys=set(self.keys),events=[dict(type='dense_mode_exit',time=now)],
                bpm=self.grid.bpm,grid=self.grid.status(),holds=[],input_mode='all-held')
        for key,end in list(self.dense_pulses.items()):
            if end<=now:
                del self.dense_pulses[key]
                self.dense_key_ready[key]=now+self.c.get('release_gap_ms',8)/1000
        for track,target in heads:
            if target>now:continue
            lane=self.select_input_lane(track,target,now)
            key=self.keys[lane]
            ready=max(self.dense_ready,self.dense_key_ready.get(key,-float('inf')))
            if now>=ready and now-target<=.035:
                if self.dense_pulses.get(key,0)>now:continue
                track.update(fired=True,input_lane=lane,completed_head_target=target)
                self.dense_pulses[key]=now+max(self.c.get('dense_tap_ms',12),self.c.get('min_down_ms',12))/1000
                self.held_restored[key]=now
                events.append(dict(id=track['id'],key=key,time=now,target=target,arrival=track['arrival'],
                    visual_lane=track['lane'],input_lane=lane,input_conflicts=track.get('input_conflicts',0),input_reason=track.get('input_reason'),
                    lateness_ms=(now-target)*1000,type='dense_head',input_mode='dense-taps'))
        baseline={k for k in self.keys if self.dense_blocked.get(k,0)<now}
        return dict(keys=baseline|{k for k,end in self.dense_pulses.items() if end>now},events=events,
            bpm=self.grid.bpm,grid=self.grid.status(),holds=[],input_mode='dense-taps')

    def poll_release_all(self,now):
        """Experimental whole-keyboard release/repress per confirmed chord."""
        events=[];batch=self.all_release_batch
        window=.010;epsilon=1e-9
        pending_ids={t['id'] for t,_ in batch['tracks']} if batch else set()
        candidates=[]
        for track in self.tracks:
            if track['fired'] or not track.get('locked') or track['arrival'] is None or track['id'] in pending_ids:continue
            if track['color']=='pink' and not self.c.get('pink_tap_trial',False):continue
            target=self.grid.nearest(track['arrival'])-self.c.get('input_offset_ms',0)/1000
            # Late-confirmed members of an already pressed chord do not
            # manufacture another global pulse. Never chain beyond 10ms span.
            joined=False
            for group in reversed(self.completed_release_groups):
                lo=min(group['min'],target);hi=max(group['max'],target)
                if 0<=now-group['time']<=.1 and hi-lo<=window+epsilon:
                    track['fired']=True;group.update(min=lo,max=hi)
                    events.append(dict(id=track['id'],type='coalesced_late_group_head',time=now,target=target,group_id=group['id']))
                    joined=True;break
            if joined:continue
            if now>track.get('lock_until',0):continue
            if target<now-.035:track['fired']=True;continue
            candidates.append((track,target))
        candidates.sort(key=lambda pair:pair[1])
        if batch is not None:
            for track,target in candidates:
                lo=min(batch['min'],target);hi=max(batch['max'],target)
                if hi-lo<=window+epsilon:
                    batch['tracks'].append((track,target));batch.update(min=lo,max=hi)
                    events.append(dict(id=track['id'],type='joined_release_group',time=now,target=target,resume=batch['ready'],group_id=batch['tracks'][0][0]['id']))
            if now<batch['ready']:
                return dict(keys=set(),events=events,bpm=self.grid.bpm,grid=self.grid.status(),holds=[],input_mode='all-held',release_scope='all')
            seen=set()
            for track,target in batch['tracks']:
                track['fired']=True;key=self.keys[track['lane']]
                if key in seen:
                    events.append(dict(id=track['id'],key=key,type='coalesced_same_key_head',time=now,target=target));continue
                seen.add(key)
                events.append(dict(id=track['id'],key=key,arrival=track['arrival'],target=target,time=now,
                    lateness_ms=(now-target)*1000,coast_ms=(now-track['last'])*1000,
                    grid_arrival=target+self.c.get('input_offset_ms',0)/1000,grid_locked=self.grid.locked,
                    rhythm_correction_ms=(target+self.c.get('input_offset_ms',0)/1000-track['arrival'])*1000,
                    prediction_source=track['prediction_source'],input_mode='all-held',release_scope='all'))
            self.completed_release_groups.append(dict(min=batch['min'],max=batch['max'],time=now,id=batch['tracks'][0][0]['id']))
            self.all_release_batch=None;self.last_full_restore=now
        elif now-self.last_full_restore>=.004:
            if candidates and candidates[0][1]<=now+self.c.get('release_lead_ms',60)/1000:
                earliest=candidates[0][1]
                chord=[pair for pair in candidates if pair[1]-earliest<=window+epsilon]
                # Center the initial chord; later members cannot push this
                # frozen deadline back repeatedly.
                ready=max(float(np.median([target for _,target in chord])),now+.008)
                self.all_release_batch=dict(ready=ready,tracks=chord,min=earliest,max=max(target for _,target in chord))
                events.append(dict(type='release_all_before_group',ids=[t['id'] for t,_ in chord],time=now,target=earliest,resume=ready))
                return dict(keys=set(),events=events,bpm=self.grid.bpm,grid=self.grid.status(),holds=[],input_mode='all-held',release_scope='all')
        return dict(keys=set(self.keys)-set(self.held_pending),events=events,bpm=self.grid.bpm,grid=self.grid.status(),holds=[],input_mode='all-held',release_scope='all')


def load_config(root, path=None):
    target=Path(path) if path else Path(root)/"domains/hololive_dreams/models/rhythm/rhythm_game_config.json"
    if not target.exists():
        return {"fps":120,"timeout":0,"analysis_width":960,"roi":[.20,.06,.86,.93],
                "hit_line_y":.86,"visual_window":.035,"min_area":18,"max_area":50000,
                "keys":["s","d","f","j","k","l"],"bpm":None,
                "colors":{"tap":([75,100,100],[135,255,255]),"hold":([35,70,70],[95,255,255]),
                           "special":([135,70,70],[179,255,255])}}
    return json.loads(target.read_text(encoding="utf-8-sig"))


def render_preview(image, observation, decision, config, fps):
    canvas=image.copy(); h,w=canvas.shape[:2]
    top=config.get('geometry',{}).get('top_y',13/711)
    a,b=field_edges(config,top);left,right=field_edges(config,config['hit_line_y'])
    for lane in range(7):
        cv2.line(canvas,(round((a+(b-a)*lane/6)*w),round(top*h)),
                 (round((left+(right-left)*lane/6)*w),round(config['hit_line_y']*h)),(160,160,160),1)
    for y,label,color in [(config.get('detection_start_y',.06),'FAR',(100,220,120)),
                          (config.get('prediction_zone',[.26,.62])[0],'FIT',(0,190,255)),
                          (config.get('prediction_zone',[.26,.62])[1],'LOCKED CLOCK',(70,70,255))]:
        cv2.line(canvas,(0,round(y*h)),(w-1,round(y*h)),color,1)
        cv2.putText(canvas,label,(8,round(y*h)+16),cv2.FONT_HERSHEY_SIMPLEX,.45,color,1)
    cv2.line(canvas,(round(left*w),round(config['hit_line_y']*h)),(round(right*w),round(config['hit_line_y']*h)),(180,180,180),2)
    cv2.putText(canvas,'ACTUAL HIT',(round(left*w),round(config['hit_line_y']*h)-5),cv2.FONT_HERSHEY_SIMPLEX,.4,(180,180,180),1)
    for n in observation['notes']:
        x,y=n['center']; bw,bh=n['width'],n['height']
        cv2.rectangle(canvas,(round((x-bw/2)*w),round((y-bh/2)*h)),
                      (round((x+bw/2)*w),round((y+bh/2)*h)),(0,255,255),2)
        tail=n.get('tail',())
        if len(tail)>1:
            points=np.array([(round(p[0]*w),round(p[1]*h)) for p in tail],np.int32)
            cv2.polylines(canvas,[points],False,(255,0,255),2)
        if n.get('color','blue')!='blue':
            cv2.putText(canvas,n['color']+':'+n['kind'],(round(x*w),round(y*h)),cv2.FONT_HERSHEY_SIMPLEX,.4,(255,255,255),1)
    for t in observation['tracks']:
        eta=t['eta_ms']; text=f"#{t['id']} {config['keys'][t['lane']].upper()} "
        text+=('CONSUMED' if t['fired'] else 'COLLECTING' if eta is None else f'{eta:+.0f}ms')
        if eta is not None and not t.get('locked'):text+=' PRELIM'
        if t.get('locked'):text+=' LOCK'
        if t.get('age_ms',0)>30:text+=f" COAST {t['age_ms']:.0f}ms"
        cv2.putText(canvas,text,(max(0,round(t['x']*w)-50),max(15,round(t['y']*h)-12)),
                    cv2.FONT_HERSHEY_SIMPLEX,.4,(0,255,0) if t['fired'] else (0,180,255),1)
    panel=np.zeros((145,w,3),np.uint8)
    lines=[f"{'LIVE' if decision['live'] else 'DRY RUN'} | {fps:.1f} FPS | mode={config.get('input_mode','normal')}",
           f"notes={len(observation['notes'])} tracks={len(observation['tracks'])} keys={','.join(decision['keys']) or '-'}",
           f"{decision.get('backend','')} capture={decision['capture_ms']:.1f}ms vision={decision['vision_ms']:.1f}ms input={decision['input_ms']:.1f}ms",
           f"blocked={decision.get('inhibited') or '-'} offset={config.get('input_offset_ms',0)}ms grid={decision.get('grid',{}).get('state','collecting')} step={decision.get('grid',{}).get('period_ms') or 0:.2f}ms confidence={decision.get('grid',{}).get('confidence',0):.0%}",
           'magenta=ribbon | holds='+str(decision.get('holds',[])),
           'F12 stops | keep game foreground | preview does not activate']
    for i,line in enumerate(lines):
        cv2.putText(panel,line,(8,21+i*23),cv2.FONT_HERSHEY_SIMPLEX,.47,(235,235,235),1)
    return np.concatenate((canvas,panel),axis=0)


def run(root, handle, *, live=False, config_path=None, should_yield=lambda:False, pause=lambda:False, progress=lambda _:None, preview=False, overrides=None, diagnostics=None):
    config=load_config(root,config_path)
    config.update(overrides or {})
    duration=float(config.get('timeout',0))
    if not math.isfinite(duration) or (duration!=0 and not 1<=duration<=1800):
        raise ValueError('timeout must be 0 (unlimited) or 1..1800 seconds')
    progress(f"Input mode={config.get('input_mode','normal')} release_scope={config.get('release_scope','target')} offset={config.get('input_offset_ms',0)}ms")
    # --live is the explicit input opt-in; default remains observation only.
    capture=create_capture(handle,config.get('capture_backend','auto'))
    safety={}
    if duration==0:safety['hold_timeout']=None
    elif config.get('input_mode')=='all-held':safety['hold_timeout']=duration
    computer=ActionComputer(live=live, audit_path=Path(root)/"runtime/computer-actions.jsonl",**safety)
    progress('Capture backend: '+str(capture.stats))
    vision,controller=RhythmVision(config),RhythmController(config); keys=KeyState(computer,live,config["keys"],on_send=diagnostics.input_edge if diagnostics else None)
    display=None
    if preview or config.get('preview'):
        from modular_agent.realtime.jump_rope_preview import Preview
        display=Preview(config,renderer=render_preview,title='Rhythm recognition')
    started=time.perf_counter(); frames=0; rows=deque(maxlen=600); reason="timeout"; original=None
    lock=threading.RLock(); stop=threading.Event()
    shared=dict(bounds=None,stamp=0.,error=None,events=deque(maxlen=2000))
    def pump():
        try:
            while not stop.wait(.001):
                with lock:
                    if diagnostics:diagnostics.check()
                    if computer.stopped or should_yield():
                        shared['error']='cancelled';stop.set();break
                    if pause():
                        keys.release();continue
                    if shared['bounds'] is None:continue
                    now=time.perf_counter()
                    if now-shared['stamp']>config.get('coast_ms',220)/1000:
                        keys.release();continue
                    d=controller.poll(now)
                    controller.guard_baseline_restore(d,keys.down,now)
                    if d['keys']!=keys.down:
                        if capture.bounds()!=shared['bounds']:raise RuntimeError('window_changed_before_scheduled_input')
                        keys.update(d['keys'])
                    shared['events'].extend(d['events'])
        except Exception as error:
            shared['error']=str(error);stop.set()
        finally:
            with lock:
                try:keys.release()
                except Exception as error:
                    shared['error']=shared['error'] or 'input_cleanup_failed: '+str(error)
                    shared['cleanup_error']=str(error);stop.set()
    timer=threading.Thread(target=pump,name='rhythm-input-deadlines',daemon=True);timer.start()
    try:
        while duration==0 or time.perf_counter()-started < duration:
            tick=time.perf_counter()
            if stop.is_set():reason=shared['error'] or 'scheduler_stopped';break
            if diagnostics:diagnostics.check()
            if computer.stopped or should_yield(): reason="cancelled"; break
            if pause():
                time.sleep(.01);continue
            image,bounds=capture.grab(config["roi"]); captured=time.perf_counter()
            if original is not None and bounds!=original: reason='window_changed'; break
            original=bounds
            if image is None:
                if display and display.stop.is_set():reason='preview_closed';break
                time.sleep(.001);continue
            observed=getattr(capture,'last_timestamp',None) or (tick+captured)/2
            if image.shape[1]>config["analysis_width"]:
                image=cv2.resize(image,(config["analysis_width"],round(image.shape[0]*config["analysis_width"]/image.shape[1])))
            notes=vision.detect(image,captured); detected=time.perf_counter()
            # Positions describe the captured frame, not the later recognition
            # completion. Keep the capture clock for speed estimation.
            with lock:
                if stop.is_set() or computer.stopped or should_yield():reason='cancelled_before_input';break
                if pause():
                    keys.release();continue
                if diagnostics:diagnostics.check()
                decision=controller.decide(notes,observed,vision.hold_paths,dispatch_time=time.perf_counter())
                if detected-tick>.05:
                    decision['keys']=set(); decision['inhibited']='stale frame >50ms';shared['stamp']=0.
                else:shared.update(bounds=bounds,stamp=observed)
                if capture.bounds()!=bounds: reason="window_changed_before_input"; break
                controller.guard_baseline_restore(decision,keys.down,time.perf_counter())
                keys.update(decision["keys"])
                scheduled_events=list(shared['events']);shared['events'].clear()
                decision['events'].extend(scheduled_events)
                if diagnostics:
                    snapshot=[dict(id=t['id'],lane=t['lane'],color=t['color'],kind=t['kind'],x=t['x'],y=t['y'],
                        ignored_reason=t.get('ignored_reason'),
                        locked=t.get('locked',False),prediction_source=t.get('prediction_source'),lock_until=t.get('lock_until'),
                        velocity=t.get('velocity'),phase_rate=t.get('phase_rate'),projected_y=controller.motion.predict(t,observed),
                        eta_ms=None if t['arrival'] is None else (t['arrival']-observed)*1000,
                        arrival=t['arrival'],age_ms=max(0,observed-t['last'])*1000,fired=t['fired']) for t in controller.tracks]
                    actual_keys=sorted(keys.down)
            dispatched=time.perf_counter(); frames+=1
            if diagnostics:diagnostics.frame(image,observed,bounds,notes,snapshot,decision,actual_keys,
                dict(capture=(captured-tick)*1000,vision=(detected-captured)*1000,input=(dispatched-detected)*1000))
            if display:
                if display.stop.is_set(): reason='preview_closed'; break
                tracks=[dict(id=t['id'],lane=t['lane'],x=t['x'],y=t['y'],fired=t['fired'],
                             locked=t.get('locked',False),prediction_source=t.get('prediction_source'),
                             age_ms=(detected-t['last'])*1000,
                             eta_ms=None if t['arrival'] is None else (t['arrival']-detected)*1000) for t in controller.tracks]
                display.publish(image,dict(notes=[n.__dict__ for n in notes],tracks=tracks),
                    dict(live=live,keys=sorted(keys.down),backend=capture.stats['backend'],bpm=decision['bpm'],grid=decision.get('grid'),holds=[config['keys'][h['lane']] for h in decision['holds']],inhibited=decision.get('inhibited'),
                         capture_ms=(captured-tick)*1000,vision_ms=(detected-captured)*1000,
                         input_ms=(dispatched-detected)*1000),bounds,frames/max(dispatched-started,.001))
            rows.append({"time":observed,"notes":[n.__dict__ for n in notes],"decision":{**decision,"keys":sorted(decision["keys"])},
                         "timing_ms":{"capture":(captured-tick)*1000,"vision":(detected-captured)*1000,"input":(dispatched-detected)*1000}})
            if frames%max(1,config["fps"]*3)==0: progress(f"rhythm dry-run={not live}; fps={frames/(dispatched-started):.1f}; notes={len(notes)}; bpm={controller.grid.bpm}")
            time.sleep(max(0,1/config["fps"]-(time.perf_counter()-tick)))
    except KeyboardInterrupt: reason="cancelled"
    except Exception as error: reason=str(error)
    finally:
        stop.set();timer.join(timeout=2)
        try:
            with lock:keys.release()
        except Exception as error:
            shared['cleanup_error']=str(error)
        finally:
            try: computer.close()
            except Exception as error:shared['cleanup_error']=str(error)
            finally:
                capture.close()
                if display: display.close()
    elapsed=time.perf_counter()-started
    return {"outcome":"unknown","verified":False,"reason":reason,"live":live,"frames":frames,
            "cleanup_error":shared.get('cleanup_error'),"hold_timeout_seconds":getattr(computer,'hold_timeout',30),
            "capture_stats":capture.stats,
            "scheduled_events_pending_log":list(shared['events']),"settings":config,
            "actual_fps":frames/max(elapsed,1e-9),"bpm":controller.grid.bpm,"rows":list(rows)}


if __name__ == "__main__":
    p=argparse.ArgumentParser(); p.add_argument('--project-root',default=str(Path(__file__).resolve().parents[4])); p.add_argument('--window-handle',type=int); p.add_argument('--config'); p.add_argument('--live',action='store_true')
    p.add_argument('--preview',action='store_true',help='non-activating recognition window')
    p.add_argument('--offset-ms',type=float,help='positive sends earlier; negative later')
    p.add_argument('--bpm',type=float,help='known song BPM, optional')
    p.add_argument('--analysis-width',type=int,help='try 720 for faster vision')
    p.add_argument('--fps',type=int,help='capture loop target, up to 240')
    p.add_argument('--capture',choices=['auto','dxcam','mss'],default='auto',help='default DXGI, with explicit MSS fallback')
    p.add_argument('--input-mode',choices=['normal','all-held'],default=None)
    p.add_argument('--release-scope',choices=['target','all'],default=None)
    a=p.parse_args(); root=Path(a.project_root).resolve()
    overrides={}
    overrides['capture_backend']=a.capture
    if a.input_mode is not None:overrides['input_mode']=a.input_mode
    if a.release_scope is not None:overrides['release_scope']=a.release_scope
    for attr,key,low,high in [('offset_ms','input_offset_ms',-100,100),('bpm','bpm',40,300),('analysis_width','analysis_width',480,1600),('fps','fps',30,240)]:
        value=getattr(a,attr)
        if value is not None:
            if not math.isfinite(value) or not low<=value<=high:p.error('invalid '+attr)
            overrides[key]=value
    from modular_agent.computer.windows import WindowsBackend
    backend=WindowsBackend()
    if a.window_handle is None:
        windows=[w for w in backend.windows() if w['title'].lower()=='hololive-dreams']
        if len(windows)!=1: p.error('Open hololive-Dreams first, or specify --window-handle')
        a.window_handle=windows[0]['handle']
    print('Tap + green/yellow hold prototype. Switch to game within 5 seconds. F12 stops.',flush=True)
    time.sleep(5)
    result=run(root,a.window_handle,live=a.live,config_path=a.config,preview=a.preview,overrides=overrides,progress=lambda s:print(s,flush=True))
    output=root/'runtime/rhythm/last-result.json'; output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False,indent=2))
