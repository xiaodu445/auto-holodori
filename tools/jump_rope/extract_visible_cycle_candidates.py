"""Extract timed visible-fragment candidates from manually labeled intervals.
Only accepted observed pixels are used; model full predictions are never copied.
"""
import json,math,sys
from pathlib import Path
import numpy as np
import cv2
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from modular_agent.realtime.timed_rope_playback import TimedRopeTemplate
from modular_agent.realtime.rope_appearance import rope_evidence
from modular_agent.realtime.phase_tracking import CyclicTrajectory
from modular_agent.realtime.motion_states import BoundedTrajectory
LIB=ROOT/'domains/hololive_dreams/data/jump_rope_template_library';OUT=LIB/'generated/automatic_cycles';OUT.mkdir(parents=True,exist_ok=True)
rows=json.loads((ROOT/'runtime/jump-rope/frame-review/timed-recording-mainline/replay.json').read_text(encoding='utf-8'));labels=json.loads((LIB/'annotations/20261006-115004-094950-rope-points-v2.json').read_text(encoding='utf-8'))
params=json.loads((ROOT/'domains/hololive_dreams/models/jump_rope/jump_rope_visible_fit_config.json').read_text(encoding='utf-8'));profiles=json.loads((ROOT/'domains/hololive_dreams/data/jump_rope_phase'/params['stage_profiles_asset']).read_text(encoding='utf-8'));rotation=CyclicTrajectory(json.loads((ROOT/params['atlas']).read_text(encoding='utf-8')));swing=BoundedTrajectory(json.loads((ROOT/params['swing_atlas']).read_text(encoding='utf-8')));timing=json.loads((ROOT/'domains/hololive_dreams/models/jump_rope/jump_rope_mainline_input_config.json').read_text(encoding='utf-8-sig'))
periods={(1,'normal'):1.38,(2,'normal'):1.32,(2,'accelerate'):1.10,(3,'normal'):1.10,(3,'accelerate'):.91,(4,'normal'):.96,(4,'accelerate'):.78}
from modular_agent.realtime.jump_rope import load,phase_rope_components
config,module,_=load(ROOT);vision,_=phase_rope_components(ROOT,config,module,gear=True,gear_settings_path='domains/hololive_dreams/models/jump_rope/jump_rope_timed_playback_config.json');cv2.setNumThreads(1)
recording=ROOT/'runtime/jump-rope/recordings/20261006-115004-094950';stamps=json.loads((recording/'timestamps.json').read_text(encoding='utf-8'));cap=cv2.VideoCapture(str(recording/'screen.avi'));raw_observations=[]
def observed_interval(ann,stage,role,direction):
    cap.set(cv2.CAP_PROP_POS_FRAMES,max(0,ann['start_frame']-8));previous=None;low=high=None;result=[]
    start=max(0,ann['start_frame']-8);l,t,r,b=config['roi']
    for frame in range(start,ann['end_frame_exclusive']):
        ok,image=cap.read()
        if not ok:raise ValueError('missing source video frame')
        h,w=image.shape[:2];local=image[round(t*h):round(b*h),round(l*w):round(r*w)];width=config['phase_parameters']['inference_width'];scale=min(1,width/local.shape[1]);small=cv2.resize(local,(round(local.shape[1]*scale),round(local.shape[0]*scale))) if scale<1 else local;gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
        delta=np.zeros_like(gray) if previous is None else cv2.absdiff(gray,previous);scene=bool(np.mean(delta>30)>.45)
        if low is None or scene:low=gray.astype(float);high=low.copy()
        else:low=np.minimum(gray,low+2);high=np.maximum(gray,high-2)
        previous=gray;edges=cv2.Canny(gray,25,70);vision.legacy.distance=cv2.distanceTransform(255-edges,cv2.DIST_L2,3);moving_edges=edges&cv2.dilate(np.uint8(delta>8)*255,np.ones((3,3),np.uint8));vision.legacy.motion_distance=cv2.distanceTransform(255-moving_edges,cv2.DIST_L2,3);vision.legacy.variation=high-low
        vision.prepare_stage(stage,gray);ids=np.unique(np.concatenate([vision.lookup[temp.key] for temp in vision.templates if temp.context[:3]==(stage,role,direction)]));q,raw,seen,coverage,moving=rope_evidence(vision.legacy,vision.features,gray,ids,small);j=int(q.argmax())
        if frame<ann['start_frame'] or scene or q[j]<.50 or coverage[j]<.35 or moving[j]<.03 and not(q[j]>=.75 and coverage[j]>=.65):continue
        points=raw[j][seen[j]]/vision.features.units+np.array([l,t]);xs=sorted(set(points[:,0]));p=[[float(x),float(points[points[:,0]==x,1].mean())] for x in xs]
        if len(p)<12 or p[-1][0]-p[0][0]<.40:continue
        rec=dict(frame=frame,time=stamps[frame]['t'],points=p,quality=float(q[j]),coverage=float(coverage[j]),moving=float(moving[j]));result.append(rec);raw_observations.append(dict(rec,stage=stage,state=role,direction=direction))
    return result
entries=[];used=set()
for ann in labels['annotations']:
 if ann['kind'] not in ('stable','occlusion') or ann['label']=='normal' and ann['direction']=='reverse' and ann['stage']==2:continue
 stage,role=ann['stage'],ann['label'];direction='bidirectional' if role=='low_swing' else ann['direction'];identity=(stage,role,direction)
 if stage==2 and role=='decelerate':continue
 if identity in used or stage>4 or ann['start_frame']==4246:continue
 period=periods.get((stage,role),1/profiles['stages'][stage-1]['branches'][role]['clock_rate'])
 candidates=observed_interval(ann,stage,role,direction)
 if len(candidates)<8:continue
 windows=[]
 for candidate in candidates:
  st=candidate['time']
  if st-stamps[ann['start_frame']]['t']>period*1.5:break
  if stamps[min(ann['end_frame_exclusive'],len(stamps)-1)]['t']-st<period*.88:continue
  window=[r for r in candidates if st<=r['time']<st+period]
  if window:windows.append((window[-1]['time']-st,len(window),-st,window))
 if not windows:continue
 selected=max(windows,key=lambda w:w[:3])[3];start=selected[0]['time']
 # Keep up to one mark about every 1/40 cycle; preserve holes rather than invent data.
 sparse=[]
 for r in selected:
  if not sparse or r['time']-sparse[-1]['time']>=period/40:sparse.append(r)
 if len(sparse)<8 or sparse[-1]['time']-start<period*.88:
  print('Insufficient cycle support',identity,len(sparse),flush=True);continue
 samples=[dict(frame=r['frame'],elapsed_cycle_fraction=(r['time']-start)/period,points=r['points'],observed=True) for r in sparse]
 samples.append(dict(frame=None,elapsed_cycle_fraction=1.,points=sparse[0]['points'],observed=False,closure='periodic_repeat_of_start_assumption'))
 data=dict(schema=1,template_id=f'stage{stage}-{role}-{direction}-auto-visible-cycle',kind='timed_observed_rope_cycle',stage=stage,state=role,direction=direction,camera_id='wide_camera_v1',period_seconds=period,samples=samples,active_runtime=False,verified=False,source_kind='automatic_visible_cycle',period_source='human_approximate_reference' if (stage,role) in periods else 'legacy_unverified_prior',source_recording='runtime/jump-rope/recordings/20261006-115004-094950',source_interval=dict(start_frame=ann['start_frame'],end_frame_exclusive=ann['end_frame_exclusive'],human_label=ann['label'],kind=ann['kind']),training_frame_range=dict(start=sparse[0]['frame'],end=sparse[-1]['frame']+1),training_time_range=dict(start=start,end=start+period),source_observations='domains/hololive_dreams/data/jump_rope_template_library/generated/automatic_cycles/observations.json',extraction='global spatial ridge match restricted to human interval state; no predicted full curve copied',max_time_gap_fraction=.18,max_point_gap_x=.12,limitations=['Automatic local ridge observations assisted by existing candidates, not manual point truth.','Cycle origin is arbitrary first reliable fragment; endpoint repeats the first shape by a periodic assumption.','Unseen spatial and temporal regions remain unsupported.','Validation must exclude the training cycle; one recording only.'])
 template=TimedRopeTemplate(data);grid=np.arange(1024)/1024;x=np.linspace(.25,.8,41)
 targets=[(swing.curves(timing['low_forward_coordinate']),1),(swing.curves(timing['low_return_coordinate']),-1)] if role=='low_swing' else [(rotation.curves(timing['forward_coordinate'] if direction=='forward' else timing['reverse_coordinate']),0)]
 axis=np.interp(x,swing.curves(1)[:,0],swing.curves(1)[:,1])-np.interp(x,swing.curves(0)[:,0],swing.curves(0)[:,1]);jumps=[]
 for target,sign in targets:
  yy=np.interp(x,target[:,0],target[:,1]);errors=[]
  for u in grid:
   y=template.curve(u,x);mask=np.isfinite(y)
   if mask.sum()<12:errors.append(math.inf);continue
   velocity=template.curve(u+.003,x)-template.curve(u-.003,x);vm=np.isfinite(velocity)&mask
   if sign and (vm.sum()<12 or float(np.dot(velocity[vm],axis[vm]))*sign<=0):errors.append(math.inf);continue
   errors.append(float(np.mean((y[mask]-yy[mask])**2)))
  if not math.isfinite(min(errors)):break
  jumps.append(float(grid[int(np.argmin(errors))]))
 if len(jumps)!=len(targets):print('Missing onset support',identity);continue
 data['jump_progress_nodes']=jumps;data['jump_timing_source']='nearest supported observed shape to prior manual onset, direction-filtered for low swing; unverified'
 path=OUT/(data['template_id']+'.json');path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');entries.append(dict(file=path.relative_to(ROOT).as_posix(),template_id=data['template_id'],stage=stage,state=role,direction=direction));used.add(identity);print(identity,'marks',len(sparse),'range',data['training_frame_range'],flush=True)
cap.release()
(OUT/'observations.json').write_text(json.dumps(dict(schema=1,recording='runtime/jump-rope/recordings/20261006-115004-094950',observations=raw_observations,verified=False),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUT/'catalog.json').write_text(json.dumps(dict(schema=1,templates=entries,verified=False,source='human intervals; automatic observed fragments only'),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Automatic candidates',len(entries))
