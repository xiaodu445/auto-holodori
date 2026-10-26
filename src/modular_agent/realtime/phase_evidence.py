"""Independent bounded-motion candidate chains; no image or control calls."""
import numpy as np

class PhaseEvidenceChain:
    def __init__(self, min_rate, max_rate, horizon=.35):
        self.low=float(min_rate);self.high=float(max_rate);self.horizon=horizon;self.beams=[];self.direction=None
    def update(self,candidates,now,direction):
        if self.direction!=direction:self.beams=[];self.direction=direction
        next_beams=[]
        for phase,quality in candidates:
            if quality<.45:continue
            next_beams.append([(now,float(phase),float(quality))])
            for records in self.beams:
                dt=now-records[-1][0]
                if not 0<dt<=.12:continue
                phase_unwrapped=phase+round(records[-1][1]-phase)
                travel=(phase_unwrapped-records[-1][1])*direction
                if not self.low*dt-.018<=travel<=self.high*dt+.018:continue
                chain=[r for r in records if now-r[0]<=self.horizon]+[(now,phase_unwrapped,quality)]
                next_beams.append(chain)
        def fit(records):
            t=np.array([r[0] for r in records]);x=np.array([r[1] for r in records]);t-=t[-1]
            if len(t)<4 or -t[0]<.16:return None
            slope,offset=np.polyfit(t,x,1);error=float(np.sqrt(np.mean((x-slope*t-offset)**2)))
            if not self.low<=slope*direction<=self.high or error>.014 or (x[-1]-x[0])*direction<.10:return None
            return dict(phase=float(offset)%1,rate=abs(float(slope)),error=error,span=float(-t[0]),quality=float(np.mean([r[2] for r in records])))
        scored=[]
        for records in next_beams:
            f=fit(records);span=now-records[0][0]
            score=np.mean([r[2] for r in records])+min(.15,span*.4)
            scored.append((score,records,f))
        scored.sort(key=lambda x:x[0],reverse=True);kept=[];keys=set()
        for score,records,f in scored:
            key=(round(records[-1][1]%1*96),round((records[-1][1]-records[0][1])/max(.01,now-records[0][0])*8),len(records)>=4)
            if key in keys:continue
            keys.add(key);kept.append((score,records,f))
            if len(kept)>=24:break
        self.beams=[r for _,r,_ in kept]
        viable=[(score,f) for score,r,f in kept if f is not None]
        return max(viable,key=lambda p:p[0])[1] if viable else None


class ClockRateEvidence:
    """Estimate clock frequency from trusted image coordinates, not corrections."""
    def __init__(self,low,high,horizon=1.4,max_gap=.25):
        self.low=low;self.high=high;self.horizon=horizon;self.max_gap=max_gap;self.records=[]
    def update(self,phase,now,direction):
        if self.records:
            dt=now-self.records[-1][0];phase+=round(self.records[-1][1]-phase)
            travel=(phase-self.records[-1][1])*direction
            if not 0<dt<=self.max_gap or not self.low*dt-.025<=travel<=self.high*dt+.025:self.records=[]
        self.records.append((now,float(phase)));self.records=[r for r in self.records if now-r[0]<=self.horizon]
        if len(self.records)<8 or now-self.records[0][0]<.4:return None
        t=np.array([r[0] for r in self.records]);x=np.array([r[1] for r in self.records]);t-=t[-1]
        slope,offset=np.polyfit(t,x,1);residual=float(np.sqrt(np.mean((x-slope*t-offset)**2)))
        if not self.low<=slope*direction<=self.high or residual>.015:return None
        return dict(rate=abs(float(slope)),residual=residual,span=float(-t[0]),time=float(now),samples=len(t))
