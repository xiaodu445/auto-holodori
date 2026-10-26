"""Time-indexed observed rope templates and a causal playback selector.
No legacy geometric atlas or runtime input dependency.
"""
from collections import deque
import math
import numpy as np

class TimedRopeTemplate:
    def __init__(self,data):
        self.data=data;self.key=data['template_id'];self.context=tuple(data[k] for k in ('stage','state','direction','camera_id'))
        self.period=float(data['period_seconds']);self.nodes=np.array([s['elapsed_cycle_fraction'] for s in data['samples']]);self.points=[np.array(s['points'],float) for s in data['samples']]
        if not math.isfinite(self.period) or self.period<=0 or len(self.nodes)<3 or self.nodes[0]!=0 or self.nodes[-1]!=1 or np.any(np.diff(self.nodes)<=0):raise ValueError('invalid cycle nodes')
        for p in self.points:
            if p.ndim!=2 or p.shape[1]!=2 or len(p)<2 or not np.all(np.isfinite(p)) or np.any(p<0) or np.any(p>1) or np.any(np.diff(p[:,0])<=0):raise ValueError('invalid observed shape')
        self.max_time_gap=float(data.get('max_time_gap_fraction',.18));self.max_x_gap=float(data.get('max_point_gap_x',.12))
    def curve(self,progress,x):
        """Interpolate only observed temporal/spatial support; unknown stays NaN."""
        u=float(progress)%1;x=np.asarray(x,float);i=min(len(self.nodes)-2,max(0,int(np.searchsorted(self.nodes,u,side='right')-1)))
        gap=self.nodes[i+1]-self.nodes[i];w=(u-self.nodes[i])/gap
        if gap>self.max_time_gap:return np.full(x.shape,np.nan)
        yy=[]
        for p in self.points[i:i+2]:
            j=np.clip(np.searchsorted(p[:,0],x,side='right')-1,0,len(p)-2)
            valid=(x>=p[0,0])&(x<=p[-1,0])&((p[j+1,0]-p[j,0])<=self.max_x_gap)
            yy.append(np.where(valid,np.interp(x,p[:,0],p[:,1]),np.nan))
        if w<1e-10:return yy[0]
        if w>1-1e-10:return yy[1]
        return yy[0]*(1-w)+yy[1]*w
    def error(self,progress,points):
        p=np.asarray(points,float)
        if p.ndim!=2 or p.shape[1]!=2 or len(p)<6 or not np.all(np.isfinite(p)):return math.inf
        y=self.curve(progress,p[:,0]);mask=np.isfinite(y)
        if mask.sum()<6 or mask.mean()<.5:return math.inf
        return float(np.sqrt(np.mean((y[mask]-p[mask,1])**2)))

class TimedPlaybackBank:
    """Retain all candidates; compare recent trusted observations at their own periods."""
    def __init__(self,templates,*,window_seconds=.45,minimum_margin=.004):
        if not templates:raise ValueError('empty bank')
        self.templates=list(templates);self.history=deque();self.selected=self.templates[0];self.start=None;self.last_time=None
        self.window_seconds=window_seconds;self.minimum_margin=minimum_margin;self.pending=None
    def update(self,now,points=None,*,trusted=False,context=None):
        if not math.isfinite(now) or self.last_time is not None and now<=self.last_time:raise ValueError('nonmonotonic time')
        self.last_time=now
        if self.start is None:self.start=now
        pool=[t for t in self.templates if context is None or t.context==tuple(context)]
        if not pool:return {'path':'unsupported_context','template':None,'progress':None}
        if self.selected not in pool:
            self.selected=pool[0];self.start=now;self.history.clear();self.pending=None
        predicted=(now-self.start)/self.selected.period
        report={'path':'predict_only','template':self.selected.key,'progress':predicted%1,'period_seconds':self.selected.period}
        while self.history and now-self.history[0][0]>self.window_seconds:self.history.popleft()
        if not trusted or points is None:return report
        p=np.asarray(points,float)
        if p.ndim!=2 or p.shape[1]!=2 or len(p)<6 or not np.all(np.isfinite(p)):return report
        self.history.append((now,p.copy()))
        options=[]
        grid=np.arange(160)/160
        for t in pool:
            scores=[]
            for u in grid:
                e=[t.error(u+(at-now)/t.period,q) for at,q in self.history]
                scores.append(float(np.sqrt(np.mean(np.square(e)))) if all(math.isfinite(v) for v in e) else math.inf)
            scores=np.array(scores);j=int(scores.argmin());u=grid[j]
            gap=abs((grid-u+.5)%1-.5);rivals=scores[gap>=.06];margin=float(rivals.min()-scores[j]) if len(rivals) else 0
            options.append({'object':t,'progress':float(u),'error':float(scores[j]),'phase_margin':margin})
        options.sort(key=lambda x:x['error']);best=options[0];report['candidates']=[{k:v for k,v in o.items() if k!='object'}|{'template':o['object'].key} for o in options]
        if not math.isfinite(best['error']) or best['error']>.035 or best['phase_margin']<self.minimum_margin:
            self.pending=None;report['path']='ambiguous_hold';return report
        if best['object'] is not self.selected and len(options)>1 and options[1]['error']-best['error']<self.minimum_margin:
            self.pending=None;report['path']='template_tie_hold';return report
        delta=(best['progress']-predicted+.5)%1-.5
        if best['object'] is self.selected and abs(delta)<=.04:
            correction=float(np.clip(delta*.25,-.01,.01));self.start-=correction*self.selected.period
            report.update(path='gentle',phase_correction=correction,progress=((now-self.start)/self.selected.period)%1);self.pending=None;return report
        span=self.history[-1][0]-self.history[0][0]
        if len(self.history)<4 or span<.12:
            report['path']='collecting_recovery';return report
        self.selected=best['object'];self.start=now-best['progress']*self.selected.period
        report.update(path='recovery',template=self.selected.key,progress=best['progress'],period_seconds=self.selected.period,phase_correction=delta)
        return report
