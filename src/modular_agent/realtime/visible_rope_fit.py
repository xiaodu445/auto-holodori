"""Independent visible-fragment phase fitting and causal clock-rate evidence."""
from collections import deque
import math
import numpy as np


class VisibleRopeFit:
    def __init__(self):
        self.records=deque();self.context=None;self.review=None

    @staticmethod
    def select(vision,table,support_fn,scene=False,cyclic=True):
        if scene or table is None:return None
        j=int(np.argmax(table['q']));coordinate=float(vision.grid[table['indices'][j]])
        q=float(table['q'][j]);coverage=float(table['coverage'][j]);moving=float(table['moving'][j])
        curve=vision.reference_curves[table['indices'][j]]
        support=support_fn(vision,curve,table['raw'][j],table['seen'][j],True)
        coords=vision.grid[table['indices']];gap=abs(coords-coordinate)
        if cyclic:gap=abs((coords-coordinate+.5)%1-.5)
        rivals=table['q'][gap>=.06];margin=q-float(np.max(rivals)) if len(rivals) else 0.
        trusted=q>=.65 and coverage>=.50 and moving>=.10 and np.count_nonzero(support)>=14 and margin>=.06
        return dict(coordinate=coordinate,quality=q,coverage=coverage,moving=moving,margin=margin,trusted=bool(trusted),index=j,support=support)

    @staticmethod
    def clock(bank,item,coordinate,gear=None):
        if item.mode=='low_swing':
            angle=math.acos(1-2*coordinate)/(2*math.pi)
            if item.coordinate_velocity<0:angle=1-angle
            return bank.warp.inverse(angle)
        warp=bank.profile_warp(item.mode,item.gear if gear is None else gear)
        if warp is None:return coordinate
        return item.rotation_anchor+item.direction*warp.inverse(item.direction*(coordinate-item.rotation_anchor))

    def update(self,bank,item,fit,now,dt=None):
        context=(item.mode,bank.item_stage(item),bank.epoch)
        if context!=self.context:self.records.clear();self.context=context
        self.review=dict(time=now,source='independent_visible_fragment',trusted=False,phase_applied=False,speed_applied=False)
        if fit is None or not fit['trusted']:
            if self.records and now-self.records[-1][0]>.08:self.records.clear()
            self.review['reason']='visible_fragment_not_trusted';return False
        if self.records and (now<=self.records[-1][0] or now-self.records[-1][0]>.08):self.records.clear()
        elapsed=dt if dt is not None else now-self.records[-1][0] if self.records else .016
        coordinate=fit['coordinate'];self.records.append((now,coordinate))
        while self.records and now-self.records[0][0]>.45:self.records.popleft()
        before=item.coordinate;clock=self.clock(bank,item,coordinate)
        error=(clock-item.phase+.5)%1-.5
        self.review.update(trusted=True,coordinate=coordinate,previous_coordinate=before,quality=fit['quality'],coverage=fit['coverage'],moving=fit['moving'],margin=fit['margin'],frames=len(self.records),span=now-self.records[0][0],phase_error=error)
        if abs(error)<=.04:
            limit=min(bank.c['max_phase_correction'],item.speed*max(0,elapsed)*bank.c['phase_correction_fraction'])
            correction=float(np.clip(error*.25,-limit,limit));item.phase+=correction
            self.review.update(path='gentle',phase_applied=True,phase_correction=correction)
        else:
            self.review['path']='recovery_pending'
            if len(self.records)<5 or now-self.records[0][0]<.12:
                self.review['reason']='collecting_independent_recovery_window';return False
            times=np.array([t-now for t,x in self.records])
            clocks=np.unwrap(np.array([self.clock(bank,item,x) for t,x in self.records])*2*math.pi)/(2*math.pi)
            slope,intercept=np.polyfit(times,clocks,1)
            residual=float(np.sqrt(np.mean((clocks-(slope*times+intercept))**2)))
            rate=slope*item.direction if item.mode!='low_swing' else slope
            self.review.update(recovery_residual=residual,recovery_rate=float(rate))
            travel=(clocks[-1]-clocks[0])*(item.direction if item.mode!='low_swing' else 1)
            rates=bank.rates(bank.item_stage(item))['swing_gears' if item.mode=='low_swing' else 'rotation_gears']
            if residual>.018 or not min(rates)*.6<=rate<=max(rates)*1.4 or travel<.025:
                self.review['reason']='independent_recovery_window_inconsistent';return False
            item.phase=clock+round(item.phase-clock)
            self.review.update(path='recovery',phase_applied=True,phase_correction=error)
        item.visual=True;item.score=max(item.score,fit['quality'])
        if item.mode=='low_swing':self.review['reason']='visible_phase_low_swing';return True
        if len(self.records)<10 or now-self.records[0][0]<.30:self.review['reason']='collecting_visible_speed_window';return True
        times=np.array([t-now for t,x in self.records]);options=[]
        for gear,nominal in enumerate(bank.rates(bank.item_stage(item))['rotation_gears']):
            clocks=np.unwrap(np.array([self.clock(bank,item,x,gear) for t,x in self.records])*2*math.pi)/(2*math.pi)
            slope,intercept=np.polyfit(times,clocks,1);residual=float(np.sqrt(np.mean((clocks-(slope*times+intercept))**2)))
            measured=float(slope*item.direction);error=abs(measured-nominal)/nominal
            travel=float((clocks[-1]-clocks[0])*item.direction)
            options.append(dict(gear=gear,nominal=nominal,rate=measured,residual=residual,relative_error=error,travel=travel,score=residual+.08*error))
        options.sort(key=lambda r:r['score']);self.review['speed_fits']=options
        valid=[r for r in options if r['residual']<=.010 and r['travel']>=.08 and .2<=r['rate']<=bank.c.get('max_rate',4.)]
        if not valid:self.review['reason']='visible_clock_fit_inconsistent';return True
        best=valid[0]
        confirmed=best['relative_error']<=.06 and (len(options)==1 or min(r['score'] for r in options if r is not best)-best['score']>=.0035)
        if not confirmed:
            current=next((r for r in valid if r['gear']==item.gear),None)
            if current is None:self.review['reason']='visible_speed_gears_ambiguous';return True
            best=current
        bank.visible_speed_authority=dict(time=now,epoch=bank.epoch,mode=item.mode,stage=bank.item_stage(item),gear=best['gear'],rate=best['rate'],gear_confirmed=confirmed)
        old_gear=item.gear;old_speed=item.speed;item.gear=best['gear'];item.warp=bank.profile_warp(item.mode,item.gear)
        clock=self.clock(bank,item,coordinate);item.phase=clock+round(item.phase-clock);item.speed=best['rate']
        speed_recovery=old_gear!=item.gear or abs(item.speed-old_speed)/old_speed>.08
        if speed_recovery:
            bank.gear_switches+=int(old_gear!=item.gear);bank.switches+=1;bank.event='trusted_visible_speed_fit'
            bank.items=[item];bank.branch_info={};bank.evidence={};bank.speed_evidence={};bank.stage_candidates=set()
            bank.item_stages={item.key:bank.stage_index};bank.pending=None;bank.pending_since=None
            if hasattr(bank,'audio_candidates'):bank.audio_candidates={}
        if speed_recovery:self.review['path']='recovery'
        self.review.update(speed_applied=True,gear_confirmed=confirmed,from_gear=old_gear,to_gear=item.gear,clock_rate=item.speed,reason='trusted_visible_speed_fit' if confirmed else 'trusted_visible_rate_gear_unresolved')
        return True
