"""Offline landing-branch comparisons, isolated from default C4 output and config."""
import argparse
import hashlib
import json
from pathlib import Path
from modular_agent.realtime import jump_rope
from modular_agent.realtime.validate_jump_rope_phase import validate

CASES={'all-once':{'landing_branches':True},'all-once-multi':{'landing_branches':True,'swing_gears':[.41683641803956556,.49880574854534915,.5848225200903135]},'rotation-once':{'landing_branches':True,'branch_scope':'rotation_speed'},'rotation-strong':{'landing_branches':True,'branch_scope':'rotation_speed','branch_actual_support':True,'branch_quality_min':.55,'branch_motion_min':.08,'branch_evidence_span':.1,'branch_evidence_frames':5},'baseline':{},'rotation':{'landing_branches':True,'branch_scope':'rotation_speed'},'single':{'landing_branches':True},'multi':{'landing_branches':True,'swing_gears':[.41683641803956556,.49880574854534915,.5848225200903135]}}


def run(root,names,video=False):
    root=Path(root).resolve();original=jump_rope.load;results=[]
    settings=json.loads((root/'docs/jump-rope/history/gear-v4-before-landing-branches/domains/hololive_dreams/models/jump_rope_phase_gear_config.json').read_text(encoding='utf-8'))
    for name in names:
        if name not in CASES:raise ValueError('unknown landing branch case')
        parameters=dict(settings,**CASES[name]);parameters['landing_branches']=CASES[name].get('landing_branches',False)
        def customized(*args,**kwargs):
            c,module,v=original(*args,**kwargs);base=module.PhaseGearVision
            class Trial(base):
                def __init__(self,c,*args):
                    c['phase_parameters']=dict(parameters)
                    super().__init__(c,*args)
            module.PhaseGearVision=Trial
            return c,module,v
        destination=root/'runtime/jump-rope/landing-branches'/name
        destination.mkdir(parents=True,exist_ok=True)
        for source in ['src/modular_agent/realtime/landing_trajectory_bank.py','src/modular_agent/realtime/trajectory_bank.py','domains/hololive_dreams/models/jump_rope/jump_rope_phase_gear.py']:
            saved=destination/'sources'/source;saved.parent.mkdir(parents=True,exist_ok=True);saved.write_bytes((root/source).read_bytes())
        try:
            jump_rope.load=customized
            result=validate(root,gear=True,annotated=video,output_dir=destination)
        finally:jump_rope.load=original
        result['parameters']=parameters
        result['sources']={p:hashlib.sha256((root/p).read_bytes()).hexdigest() for p in ['src/modular_agent/realtime/landing_trajectory_bank.py','src/modular_agent/realtime/trajectory_bank.py','domains/hololive_dreams/models/jump_rope/jump_rope_phase_gear.py']}
        (destination/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        summary=dict(case=name,frames=result['frames'],valid=result['valid_frames'],modes=result['mode_changes'],states=sum(r['expected']==r['observed'] for r in result['sparse_state_checks']),geometry={str(r['time']):round(r['median_visible_error_px'],2) for r in result['sparse_manual_checks']},cv_mean_ms=result['mean_inference_ms'],cv_p95_ms=result['p95_inference_ms'])
        results.append(summary);print(json.dumps(summary),flush=True)
    folder=root/'runtime/jump-rope/landing-branches';aggregate=[]
    for path in sorted(folder.glob('*/report.json')):
        r=json.loads(path.read_text(encoding='utf-8'));aggregate.append(dict(case=path.parent.name,valid=r['valid_frames'],modes=r['mode_changes'],states=sum(c['expected']==c['observed'] for c in r['sparse_state_checks']),geometry={str(c['time']):c['median_visible_error_px'] for c in r['sparse_manual_checks']},source_copies=(path.parent/'sources').exists()))
    (folder/'comparison.json').write_text(json.dumps(aggregate,indent=2),encoding='utf-8')
    return results


def main():
    p=argparse.ArgumentParser();p.add_argument('--project-root',default='.');p.add_argument('--case',choices=CASES,action='append');p.add_argument('--video',action='store_true');args=p.parse_args();run(args.project_root,args.case or list(CASES),args.video)

if __name__=='__main__':main()
