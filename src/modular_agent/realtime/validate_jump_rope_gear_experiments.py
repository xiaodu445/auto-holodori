"""Offline opt-in comparison. Never overwrites default replay/report."""
import argparse
import importlib.util
import json
import hashlib
from pathlib import Path
from modular_agent.realtime import jump_rope
from modular_agent.realtime.validate_jump_rope_phase import validate, DEFAULT_RECORDING

def run(root, names=None):
    root=Path(root).resolve();recipe=json.loads((root/'domains/hololive_dreams/models/experiments/jump_rope_gear_cases.json').read_text(encoding='utf-8'))
    settings=json.loads((root/recipe['base_config']).read_text(encoding='utf-8'));cases=recipe['cases'];names=names or list(cases)
    if any(name not in cases for name in names):raise ValueError('unknown experiment')
    spec=importlib.util.spec_from_file_location('gear_evidence_experiments',root/'domains/hololive_dreams/models/experiments/jump_rope_phase_gear_evidence.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    folder=root/'runtime/jump-rope/phase-gear';folder.mkdir(parents=True,exist_ok=True);summaries=[]
    original=jump_rope.load
    try:
        for name in names:
            params=dict(settings,**cases[name]);destination=folder/'experiments'/name;destination.mkdir(parents=True,exist_ok=True)
            def customized(*args,**kwargs):
                config,models,vision=original(*args,**kwargs)
                base=module.gear_vision_type(models.PhaseStateVision)
                class Experiment(base):
                    def __init__(self,config,*args):
                        config['phase_parameters']=dict(params)
                        super().__init__(config,*args)
                models.PhaseGearVision=Experiment
                return config,models,vision
            jump_rope.load=customized
            result=validate(root,annotated=False,gear=True,output_dir=destination)
            result['experiment']=name;result['parameters']=params
            result['experiment_source_hashes']={p.relative_to(root).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in [root/recipe['base_config'],root/'domains/hololive_dreams/models/experiments/jump_rope_phase_gear_evidence.py',root/'src/modular_agent/realtime/trajectory_bank.py']}
            (destination/'report.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
            state=result.get('sparse_state_checks',[]);errors=result['sparse_manual_checks']
            summary=dict(case=name,state_correct=sum(r['expected']==r['observed'] for r in state),state_checks=len(state),geometry={str(r['time']):r['median_visible_error_px'] for r in errors},mean_geometry_error=sum(r['median_visible_error_px'] for r in errors)/len(errors),mode_changes=result['mode_changes'],cv_mean_ms=result['mean_inference_ms'],cv_p95_ms=result['p95_inference_ms'])
            summaries.append(summary);print(json.dumps(summary),flush=True)
            (folder/'experiments'/'last-batch.json').write_text(json.dumps(summaries,indent=2),encoding='utf-8')
        summarize(root)
    finally:jump_rope.load=original
    return summaries

def summarize(root):
    """Re-evaluate saved reports against current sparse labels, retaining all runs."""
    root=Path(root);folder=root/'runtime/jump-rope/phase-gear/experiments'
    label_file=root/'domains/hololive_dreams/data/jump_rope_samples/state_validation.json'
    labels=json.loads(label_file.read_text(encoding='utf-8'))['samples'] if label_file.exists() else []
    expected={r['time']:r['state'] for r in labels};rows=[]
    for path in sorted(folder.glob('*/report.json')):
        report=json.loads(path.read_text(encoding='utf-8'));checks=report.get('sparse_state_checks',[]);geometry=report.get('sparse_manual_checks',[])
        if not geometry:continue
        rows.append(dict(case=path.parent.name,state_correct=sum(expected.get(r['time'],r['expected'])==r['observed'] for r in checks),state_checks=len(checks),geometry={str(r['time']):r['median_visible_error_px'] for r in geometry},mode_changes=report.get('mode_changes'),cv_mean_ms=report.get('mean_inference_ms'),cv_p95_ms=report.get('p95_inference_ms'),has_parameters='parameters' in report,has_source_hashes='experiment_source_hashes' in report))
    (folder/'comparison.json').write_text(json.dumps(dict(limits='Sparse development-video checkpoints only; early one-off trials may lack full recipes. Current corrected labels are used for every report.',cases=rows),indent=2),encoding='utf-8')
    return rows

def main():
    p=argparse.ArgumentParser();p.add_argument('--project-root',default='.');p.add_argument('--case',action='append');a=p.parse_args();run(a.project_root,a.case)

if __name__=='__main__':main()
