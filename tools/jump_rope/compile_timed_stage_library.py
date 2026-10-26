"""Compile stage 1-4 timed cycles from recorded shapes and explicit legacy priors."""
import json,sys,copy,hashlib,math
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2];sys.path.insert(0,str(ROOT/'src'))
from modular_agent.realtime.phase_tracking import CyclicTrajectory
from modular_agent.realtime.motion_states import BoundedTrajectory
from modular_agent.realtime.trajectory_bank import DirectionWarp,AngularWarp
from modular_agent.realtime.timed_rope_playback import TimedRopeTemplate
LIB=ROOT/'domains/hololive_dreams/data/jump_rope_template_library';OUT=LIB/'generated/stages_1_4_timed';OUT.mkdir(parents=True,exist_ok=True)
params=json.loads((ROOT/'domains/hololive_dreams/models/jump_rope_visible_fit_config.json').read_text(encoding='utf-8'));profiles=json.loads((ROOT/'domains/hololive_dreams/data/jump_rope_phase'/params['stage_profiles_asset']).read_text(encoding='utf-8'))
rotation=CyclicTrajectory(json.loads((ROOT/params['atlas']).read_text(encoding='utf-8')));swing=BoundedTrajectory(json.loads((ROOT/params['swing_atlas']).read_text(encoding='utf-8')))
from modular_agent.realtime.trajectory_bank import TrajectoryBank
swdata=json.loads((ROOT/params['swing_time_profile_asset']).read_text(encoding='utf-8'));swprofile=swdata.get('data',swdata);print('swing asset keys',list(swdata),flush=True)
# Config's already loaded time profile is the same form used by the loader.
if 'clock_nodes' not in swprofile:swprofile=params['swing_time_profile']
swwarp=AngularWarp(swprofile);revwarp=DirectionWarp(params['reverse_time_profile']);boundary=float(np.argmax(rotation.curves(np.arange(2048)/2048)[:,20,1])/2048)
timing=json.loads((ROOT/'domains/hololive_dreams/models/jump_rope_mainline_input_config.json').read_text(encoding='utf-8-sig'))
periods={(1,'normal'):1.38,(2,'normal'):1.32,(2,'accelerate'):1.10,(3,'normal'):1.10,(3,'accelerate'):.91,(4,'normal'):.96,(4,'accelerate'):.78,(4,'decelerate'):1.29}
entries=[]
def save(data):
 TimedRopeTemplate(data);path=OUT/(data['template_id']+'.json');path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');entries.append({'file':path.relative_to(ROOT).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'template_id':data['template_id'],'stage':data['stage'],'state':data['state'],'direction':data['direction'],'source_kind':data['source_kind'],'period_seconds':data['period_seconds']})
for stage in range(1,5):
 roles=['normal'] if stage==1 else ['normal','accelerate','low_swing'] if stage==2 else ['normal','accelerate','decelerate','low_swing']
 for role in roles:
  branch=profiles['stages'][stage-1]['branches'][role]
  for direction in (['forward'] if stage==1 else ['bidirectional'] if role=='low_swing' else ['forward','reverse']):
   mode='low_swing' if role=='low_swing' else 'rotation_'+direction;sign=-1 if direction=='reverse' else 1
   period=periods.get((stage,role),1/branch['clock_rate']);warp=swwarp if role=='low_swing' else DirectionWarp(branch['directions'][mode]) if mode in branch.get('directions',{}) else revwarp if direction=='reverse' else AngularWarp()
   nodes=np.linspace(0,1,97);angles=np.array([warp.evaluate(float(u))[0] for u in nodes]);angles[-1]=1
   coordinates=(1-np.cos(2*np.pi*angles))/2 if role=='low_swing' else (boundary+sign*angles)%1
   curves=swing.curves(coordinates) if role=='low_swing' else rotation.curves(coordinates)
   jumps=[swwarp.inverse(math.acos(1-2*timing['low_forward_coordinate'])/(2*math.pi)),swwarp.inverse(1-math.acos(1-2*timing['low_return_coordinate'])/(2*math.pi))] if role=='low_swing' else [warp.inverse(sign*(timing['reverse_coordinate'] if direction=='reverse' else timing['forward_coordinate'])-sign*boundary)]
   data=dict(schema=1,template_id=f'stage{stage}-{role}-{direction}-legacy-timed',kind='timed_observed_rope_cycle',stage=stage,state=role,direction=direction,camera_id='wide_camera_v1',period_seconds=period,samples=[dict(elapsed_cycle_fraction=float(u),points=c.tolist()) for u,c in zip(nodes,curves)],jump_progress_nodes=jumps,active_runtime=False,verified=False,source_kind='legacy_shape_and_warp_compiled_to_time',period_source='human_approximate_reference' if (stage,role) in periods else 'legacy_unverified_prior',source_branch=f'stages[{stage-1}].branches.{role}',source_profile=params['stage_profiles_asset'],source_shape=params['swing_atlas'] if role=='low_swing' else params['atlas'],max_time_gap_fraction=.18,max_point_gap_x=.12,limitations=['Compiled prior, not newly measured full cycle.','Low-swing shape uses legacy camera geometry.' ] if role=='low_swing' else ['Compiled prior, not newly measured full cycle.'])
   save(data)
# Keep the directly observed cycle as a separate candidate, with no old atlas motion.
p=LIB/'stage_2/normal_reverse/samples/20261006-115004-094950-segment-05/generated/timed_playback/template.json';data=json.loads(p.read_text(encoding='utf-8'));data['source_kind']='human_observed_cycle';data['camera_id']='wide_camera_v1';data['period_source']='human_confirmed_timestamp_boundaries';data['source_template']=p.relative_to(ROOT).as_posix()
temp=TimedRopeTemplate(data);grid=np.arange(2048)/2048;x=np.linspace(.25,.80,41);target=rotation.curves(timing['reverse_coordinate']);target_y=np.interp(x,target[:,0],target[:,1]);errors=[]
for u in grid:
 y=temp.curve(u,x);mask=np.isfinite(y);errors.append(np.mean((y[mask]-target_y[mask])**2) if mask.sum()>=20 else float('inf'))
data['jump_progress_nodes']=[float(grid[np.argmin(errors)])];data['jump_timing_source']='nearest observed shape to prior manual-onset reverse shape; unverified';save(data)
# The same measured direction animation is also a competing, explicitly borrowed
# shape at confirmed higher-stage/accelerated periods. It is never called a new
# measured sample of those states, and their original priors remain competitors.
for stage,role in [(2,'accelerate'),(3,'normal'),(3,'accelerate'),(4,'normal'),(4,'accelerate')]:
 borrowed=copy.deepcopy(data);borrowed.update(template_id=f'stage{stage}-{role}-reverse-borrowed-human-cycle',stage=stage,state=role,period_seconds=periods[(stage,role)],period_source='human_approximate_reference',source_kind='borrowed_reverse_cycle_time_scaled',shape_source_state={'stage':2,'state':'normal','direction':'reverse'})
 borrowed['limitations'].append('Borrowed stage-2 normal reverse shapes and time-stretched to this role period; target-state waveform is not independently measured.')
 save(borrowed)
# Add newly extracted visible-fragment cycles as separate competing candidates.
auto_catalog=LIB/'generated/automatic_cycles/catalog.json'
if auto_catalog.is_file():
 for entry in json.loads(auto_catalog.read_text(encoding='utf-8'))['templates']:
  auto=json.loads((ROOT/entry['file']).read_text(encoding='utf-8'));auto['source_template']=entry['file'];save(auto)
from modular_agent.realtime.timed_onset_calibration import calibrate_data,transfer_onsets
references={}
for entry in entries:
 path=ROOT/entry['file'];item=json.loads(path.read_text(encoding='utf-8'))
 if item['source_kind']=='automatic_visible_cycle':
  item=calibrate_data(item,ROOT);references[(item['stage'],item['state'],item['direction'])]=item
 elif item['source_kind']=='human_observed_cycle':
  item.update(source_recording='runtime/jump-rope/recordings/20261006-115004-094950',source_interval=dict(start_frame=2564,end_frame_exclusive=2793),training_time_range=dict(start=44.375005200039595,end=45.696596400113776));item=calibrate_data(item,ROOT);references[(2,'normal','reverse')]=item
 path.write_text(json.dumps(item,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
for entry in entries:
 path=ROOT/entry['file'];item=json.loads(path.read_text(encoding='utf-8'));context=(item['stage'],item['state'],item['direction']);reference=references.get(context)
 if reference and reference['template_id']!=item['template_id']:item=transfer_onsets(item,reference)
 elif not reference and item['direction']=='reverse':item=transfer_onsets(item,references[(2,'normal','reverse')])
 if item['stage']==2 and item['state']=='decelerate' or item['stage']==1 and (item['state'],item['direction'])!=('normal','forward') or item['stage']>4:raise ValueError('out-of-scope timed candidate')
 path.write_text(json.dumps(item,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');entry['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
catalog=dict(schema=1,scope='stages_1_4_except_stage2_decelerate',templates=entries,excluded_states=[dict(stage=2,state='decelerate',reason='user_deferred')],runtime_verified=False,limits='Stage 1 only forward normal; stage 5 delegates prior route. Compiled priors remain explicitly unverified.')
(OUT/'catalog.json').write_text(json.dumps(catalog,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print('templates',len(entries),'states',len({(e['stage'],e['state'],e['direction']) for e in entries}),'human_jump',data['jump_progress_nodes'])
