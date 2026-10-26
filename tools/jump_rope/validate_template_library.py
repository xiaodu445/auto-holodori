from pathlib import Path
import json,hashlib,math
ROOT=Path(__file__).resolve().parents[2];LIB=ROOT/'domains/hololive_dreams/data/jump_rope_template_library'
def check():
 files=list(LIB.rglob('*.json'))
 for p in files:json.loads(p.read_text(encoding='utf-8'))
 manifest=json.loads((LIB/'manifest.json').read_text(encoding='utf-8'));profiles=json.loads((ROOT/'domains/hololive_dreams/data/jump_rope_phase/audio_forward_decelerate_trial.json').read_text(encoding='utf-8'))
 for asset in manifest['assets']:
  for name in ['file','source']:
   p=(ROOT/asset[name]).resolve();assert p.is_relative_to(ROOT) and p.is_file(),asset
   assert hashlib.sha256(p.read_bytes()).hexdigest()==asset['sha256'],asset
  if asset['kind']=='shape_candidates':
   shape=json.loads((ROOT/asset['file']).read_text(encoding='utf-8'))
   for sample in shape['samples']:
    assert len(sample['curve'])==41 and all(len(point)==2 and all(math.isfinite(v) for v in point) for point in sample['curve'])
 assert len(manifest['states'])==29
 for state in manifest['states']:
  if state['stage']==1:assert state['role']=='normal' and state['direction']=='forward'
  assert (ROOT/state['shape_ref']).is_file()
  template=json.loads((ROOT/state['template_ref']).read_text(encoding='utf-8'))
  assert template['data']==profiles['stages'][state['stage']-1]['branches'][state['role']]
  assert template['verified'] is False and state['active_runtime'] is False
 for recording in json.loads((LIB/'recordings/index.json').read_text(encoding='utf-8'))['recordings']:
  for f in recording['files']:assert (ROOT/f['file']).is_file() and (ROOT/f['file']).stat().st_size==f['bytes']
 print(json.dumps(dict(json_files=len(files),states=29,source_hashes_verified=len(manifest['assets']),result='passed'),ensure_ascii=False))
if __name__=='__main__':check()
