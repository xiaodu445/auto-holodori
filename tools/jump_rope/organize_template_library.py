from pathlib import Path
import json,hashlib,shutil
ROOT=Path(__file__).resolve().parents[2]
LIB=ROOT/'domains/hololive_dreams/data/jump_rope_template_library'
OLD=ROOT/'domains/hololive_dreams/data/jump_rope_phase'
def write(path,value):
 if path.exists():
  if json.loads(path.read_text(encoding='utf-8'))!=value:raise ValueError('Existing library data differs; create a new version instead of overwriting: '+str(path))
  return
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def rel(path):return path.relative_to(ROOT).as_posix()
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def copy_asset(source,target):
 if target.exists() and sha(target)!=sha(source):raise ValueError('Refusing to overwrite existing library asset: '+str(target))
 if not target.exists():shutil.copyfile(source,target)
def main():
 LIB.mkdir(parents=True,exist_ok=True);assets=[]
 for name,folder in [('rotation_audio_wide_v1.json','shapes/rotation/wide_camera_v1'),('swing_v1.json','shapes/low_swing/legacy_camera_v1')]:
  source=OLD/name;target=LIB/folder/'candidates.json';target.parent.mkdir(parents=True,exist_ok=True);copy_asset(source,target);data=json.loads(source.read_text(encoding='utf-8'))
  write(target.parent/'metadata.json',dict(schema=1,source=rel(source),sha256=sha(source),verified=False,provenance=data.get('provenance'),coordinate_space=data.get('coordinate_space','see_source_provenance'),candidate_count=len(data['samples']),tolerance_status='needs_calibration',camera_status='current_wide_camera_trial' if name.startswith('rotation') else 'legacy_camera_needs_new_recording',usage='Visible fragments must match fixed candidate geometry; full visibility is not required. No new runtime background rejection enabled by this organization.'))
  assets.append(dict(source=rel(source),file=rel(target),sha256=sha(target),kind='shape_candidates'))
 profiles=json.loads((OLD/'audio_forward_decelerate_trial.json').read_text(encoding='utf-8'));states=[]
 for stage in profiles['stages']:
  i=stage['id']
  for role,branch in stage['branches'].items():
   directions=['forward','reverse'] if role!='low_swing' else ['both']
   for direction in directions:
    if i==1 and (role!='normal' or direction!='forward'):continue
    name=role+'_'+direction if role!='low_swing' else 'low_swing';folder=LIB/f'stage_{i}'/name
    shape=LIB/('shapes/low_swing/legacy_camera_v1/candidates.json' if role=='low_swing' else 'shapes/rotation/wide_camera_v1/candidates.json')
    template=dict(schema=1,stage=i,role=role,direction=direction,verified=False,shape_ref=rel(shape),source=rel(OLD/'audio_forward_decelerate_trial.json'),source_branch=f"stages[{i-1}].branches.{role}",data=branch)
    write(folder/'generated'/'legacy_import'/'template.json',template)
    status=branch.get('direction_status',{}).get('rotation_'+direction,branch.get('status'))
    if role=='decelerate' and 'rotation_'+direction in branch.get('directions',{}):status=branch.get('status')
    metadata=dict(schema=1,stage=i,role=role,direction=direction,status='trial_needs_independent_validation' if status and status!='pending_calibration' else 'needs_recording_and_calibration',legacy_status=status,nominal_rate=branch['clock_rate'],verified=False,active_runtime=False,template_ref=rel(folder/'generated/legacy_import/template.json'),shape_ref=rel(shape),samples=[],limits='Imported legacy parameters are not new measurements. Whole original branch retained for traceability; use only requested direction.')
    write(folder/'index.json',metadata);(folder/'samples').mkdir(parents=True,exist_ok=True);states.append(dict(path=rel(folder),**metadata))
 annotations=[]
 for source in sorted((ROOT/'domains/hololive_dreams/data/jump_rope_samples/human').glob('*.json')):
  target=LIB/'annotations'/source.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
  assets.append(dict(source=rel(source),file=rel(target),sha256=sha(target),kind='human_annotation'));annotations.append(dict(file=rel(target),source=rel(source)))
 write(LIB/'annotations/index.json',dict(schema=1,annotations=annotations,limits='Historical annotations may reference different recordings or review frame indexes; do not automatically relabel them as new samples.'))
 recordings=[]
 for folder in sorted((ROOT/'runtime/jump-rope/recordings').iterdir()):
  if not folder.is_dir():continue
  files=[dict(file=rel(p),bytes=p.stat().st_size) for p in sorted(folder.iterdir()) if p.is_file()]
  recordings.append(dict(id=folder.name,path=rel(folder),files=files,storage='external_original_single_copy'))
 write(LIB/'recordings/index.json',dict(schema=1,recordings=recordings))
 write(LIB/'transitions/index.json',dict(schema=1,samples=[],categories=['stage_change','skill_entry','skill_exit','direction_change','occlusion_recovery'],status='needs_segmentation',limits='Audio annotations retained in annotations; no precise transition boundaries invented.'))
 write(LIB/'schemas/sample.example.json',dict(schema=1,sample_id='REPLACE_ME',recording_id='REPLACE_ME',stage=None,state=None,direction=None,kind='stable',frame_range=dict(start=None,end=None,end_exclusive=True),time_reference='timestamps.json original frame indexes',camera_id=None,label_certainty='unreviewed',visibility=None,cycle_boundaries=[],audio_event_range=None,status='unannotated',annotation_file=None,measurements_file=None,generated_template_file=None,split='unassigned',limits='No measurements until extraction; clip.avi is optional and not a timing authority.'))
 write(LIB/'manifest.json',dict(schema=1,description='Unified rope geometry and stage/skill sample catalog',stage1_rule='Only normal forward rotation at counts 0–9; other stage1 states do not occur.',states=states,assets=assets,runtime_settings='domains/hololive_dreams/models/jump_rope/jump_rope_visible_fit_config.json',runtime_compatibility='Current runtime still loads original assets. Imported library is organized but not auto-promoted.',promotion_policy='Require explicit source ranges, calibrated geometry/time data and separate-session validation before promotion.'))
 print(json.dumps(dict(states=len(states),annotations=len(annotations),recordings=len(recordings),library=rel(LIB)),ensure_ascii=False))
if __name__=='__main__':main()
