"""Fit a review-only reverse cycle against the legacy atlas; no runtime changes."""
import json,sys
from pathlib import Path
import numpy as np
class MonotoneLinear:
    def __init__(self,x,y):self.x=x;self.y=y
    def __call__(self,x):return np.interp(x,self.x,self.y)
    def derivative(self):
        slopes=np.diff(self.y)/np.diff(self.x)
        return lambda x: slopes[np.clip(np.searchsorted(self.x,x,side="right")-1,0,len(slopes)-1)]
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from modular_agent.realtime.phase_tracking import CyclicTrajectory
LIB=ROOT/'domains/hololive_dreams/data/jump_rope_template_library'
S=LIB/'stage_2/normal_reverse/samples/20261006-115004-094950-segment-05'
OUT=S/'generated/two_cycle_fit';OUT.mkdir(parents=True,exist_ok=True)
REVIEW=ROOT/'runtime/jump-rope/frame-review/stage2-normal-reverse-fit';REVIEW.mkdir(parents=True,exist_ok=True)
d=json.loads((LIB/'annotations/20261006-115004-094950-rope-points-v2.json').read_text(encoding='utf-8'))
t=json.loads((ROOT/'runtime/jump-rope/recordings/20261006-115004-094950/timestamps.json').read_text())
atlas=CyclicTrajectory(json.loads((LIB/'shapes/rotation/wide_camera_v1/candidates.json').read_text()))
rows=[r for r in d['frame_points'] if 2564<=r['frame']<=2717 and r['points']]
grid=np.arange(2048)/2048;curves=atlas.curves(grid)
def cost(r,cs):
 p=np.array(r['points']);keep=(p[:,0]>=cs[0,:,0].min())&(p[:,0]<=cs[0,:,0].max());p=p[keep]
 return np.array([np.mean((np.interp(p[:,0],c[:,0],c[:,1])-p[:,1])**2) for c in cs])
# The shared boundary independently anchors the existing atlas coordinate.
e=cost(rows[0],curves)+cost(next(r for r in rows if r['frame']==2641),curves)
anchor=float(grid[np.argmin(e)]);progress=np.linspace(0,1,513);candidate=atlas.curves(anchor-progress)
def fit(a,b):
 rr=[r for r in rows if a<=r['frame']<=b];u=np.array([(r['time']-t[a]['t'])/(t[b]['t']-t[a]['t']) for r in rr]);C=np.array([cost(r,candidate) for r in rr]);n=len(rr);scores=np.full(513,np.inf);scores[0]=C[0,0];backs=[]
 for k in range(1,n):
  dt=u[k]-u[k-1];delta=progress[:,None]-progress[None,:];penalty=.002*(delta-dt)**2;penalty[(delta<0)|(delta>min(1,dt*4+.10))]=np.inf
  values=scores[None,:]+penalty;prev=values.argmin(axis=1);scores=values[np.arange(513),prev]+C[k];backs.append(prev)
  if rr[k]['frame']==b:scores[:-1]=np.inf
 j=int(scores.argmin());ids=[j]
 for back in reversed(backs):j=int(back[j]);ids.append(j)
 ids=ids[::-1];y=progress[ids];fit_u=u.copy();fit_y=y.copy()
 if fit_u[-1]<1:fit_u=np.r_[fit_u,1];fit_y=np.r_[fit_y,1]
 return rr,u,y,MonotoneLinear(fit_u,fit_y),np.sqrt(C[np.arange(n),ids])
r1,u1,p1,f1,err1=fit(2564,2641);r2,u2,p2,f2,err2=fit(2641,2717)
# Hold out cycle 2 entirely from the first-cycle warp fitting.
hold=np.array([cost(r,atlas.curves(np.array([anchor-f1(u)])))[0]**.5 for r,u in zip(r2,u2)])
uniform=np.array([cost(r,atlas.curves(np.array([anchor-u])))[0]**.5 for r,u in zip(r2,u2)])
nodes=np.unique(np.r_[np.linspace(0,1,81),u1]);v=f1(nodes);speed=f1.derivative()(nodes)/((t[2641]['t']-t[2564]['t']))
result={'schema':1,'stage':2,'state':'normal','direction':'reverse','status':'offline_trial_needs_shape_review','active_runtime':False,'verified':False,'atlas_anchor':anchor,'phase_convention':'atlas_phase = anchor - reverse_progress modulo 1','clock_nodes':nodes.tolist(),'reverse_progress_nodes':v.tolist(),'geometric_rate_cycles_per_second':speed.tolist(),'clock_rate':2/(t[2717]['t']-t[2564]['t']),'training_cycle':[2564,2641],'held_out_cycle':[2641,2717],'method':'Monotone discrete atlas match (513 progress nodes); weak time-increment penalty 0.002; monotone piecewise linear interpolation; fixed human cycle boundaries. No affine camera adjustment.','metrics':{'train_y_rmse_normalized':float(np.sqrt(np.mean(err1**2))),'holdout_y_rmse_normalized':float(np.sqrt(np.mean(hold**2))),'uniform_holdout_y_rmse_normalized':float(np.sqrt(np.mean(uniform**2))),'cycle_progress_disagreement_mean':float(np.mean(abs(f1(u2)-p2)))},'limitations':['The geometric coordinate is inherited from the old atlas, not independently measured rope angle.','Sparse point y residuals use interpolation within the atlas x range; they do not assess hidden rope segments.','One recording only; second-cycle ending shape at 2717 is unmarked.','Plateaus and derivative peaks can reflect shape ambiguity or sparse marks; do not deploy this derivative as runtime speed.']}
(OUT/'fit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def poly(x,y,ymax,color):
 return '<polyline fill="none" stroke="'+color+'" stroke-width="2" points="'+' '.join(f'{60+v*900:.2f},{330-w/ymax*280:.2f}' for v,w in zip(x,y))+'"/>'
chart='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 740" style="background:#222;color:white"><text x="60" y="25" fill="white">Reverse progress: cycle 1 orange / cycle 2 green / uniform gray</text>'+poly(nodes,v,1,'#ffac40')+poly(u2,p2,1,'#38ef79')+poly(nodes,nodes,1,'#888')+'<g transform="translate(0,370)"><text x="60" y="25" fill="white">Atlas progress / second (trial); peak '+f'{speed.max():.2f}'+'</text>'+poly(nodes,speed,max(1,float(speed.max())),'#ffac40')+'</g></svg>'
(REVIEW/'fit.svg').write_text(chart,encoding='utf-8')
html=['<!doctype html><meta charset="utf-8"><title>阶段2反摇正常：两圈拟合检阅</title><style>body{font:16px system-ui;background:#161b22;color:#ddd;max-width:1100px;margin:auto;padding:24px}img{max-width:100%}section{margin:30px 0;border-top:1px solid #555}svg{background:#222;width:100%}code{word-break:break-all}</style><h1>阶段2反摇正常：两圈拟合检阅</h1><p>第一圈训练：2564–2641；第二圈检验：2641–2717。绿色是人工标点，橙色是第一圈拟合在同周期进度的旧模板曲线。尚未接入实时模型。</p>',f'<p>第二圈标点纵向RMSE：{result["metrics"]["holdout_y_rmse_normalized"]*720:.1f}像素；匀速基线：{result["metrics"]["uniform_holdout_y_rmse_normalized"]*720:.1f}像素（按720像素图高换算）。该误差仅覆盖人工点，不能代表完整画面识别精度。</p><img src="fit.svg">']
for r in rows:
 a,b=(2564,2641) if r['frame']<=2641 else (2641,2717);u=(r['time']-t[a]['t'])/(t[b]['t']-t[a]['t']);c=atlas.curves(float(anchor-f1(u)));pts=' '.join(f'{x*1280:.2f},{y*720:.2f}' for x,y in c);circles=''.join(f'<circle cx="{x*1280}" cy="{y*720}" r="5" fill="#38ef79"/>' for x,y in r['points']);im=(ROOT/f'runtime/jump-rope/frame-review/recording-20261006-115004-094950/exact-frames/{r["frame"]:06d}.jpg')
 if not im.exists():
  files=list((ROOT/'runtime/jump-rope/frame-review/recording-20261006-115004-094950/exact-frames').glob(f'*{r["frame"]:06d}*'));im=files[0] if files else im
 html.append(f'<section><h2>帧{r["frame"]} · 第{1 if a==2564 else 2}圈 · 时间进度{u:.3f}</h2><svg viewBox="0 0 1280 720"><image href="{im.as_uri()}" width="1280" height="720"/><polyline points="{pts}" fill="none" stroke="#ffac40" stroke-width="3"/>{circles}</svg></section>')
html.append('<p>周期末没有标点的2717帧没有补造。局部平台与导数尖峰应结合原图复核；本页给出离线拟合证据。</p>');(REVIEW/'index.html').write_text('\n'.join(html),encoding='utf-8')
assert np.all(np.diff(v)>=-1e-10) and abs(v[0])<1e-10 and abs(v[-1]-1)<1e-10 and np.all(np.isfinite(speed))
assert all((ROOT/f'runtime/jump-rope/frame-review/recording-20261006-115004-094950/exact-frames/{r["frame"]:06d}.jpg').exists() for r in rows),'Review image naming needs correction'
print(json.dumps(result['metrics']));print('anchor',anchor,'speed_range',speed.min(),speed.max());print(REVIEW/'index.html')
