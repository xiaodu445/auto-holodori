import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from modular_agent.realtime.validate_jump_rope_gear_experiments import run

class ExperimentIsolationTests(unittest.TestCase):
    def fixture(self,root):
        folder=root/'domains/hololive_dreams/models/experiments';folder.mkdir(parents=True)
        (root/'base.json').write_text('{}')
        source=root/'src/modular_agent/realtime';source.mkdir(parents=True)
        (source/'trajectory_bank.py').write_text('# fixture')
        (folder/'jump_rope_gear_cases.json').write_text(json.dumps(dict(base_config='base.json',cases={'trial':{}})))
        (folder/'jump_rope_phase_gear_evidence.py').write_text('def gear_vision_type(base):return base')
        out=root/'runtime/jump-rope/phase-gear';out.mkdir(parents=True)
        for name in ('replay.json','report.json'):(out/name).write_text('original '+name)
        return out
    def test_failure_restores_default_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=self.fixture(root)
            def fail(*args,**kwargs):
                destination=kwargs['output_dir'];(destination/'replay.json').write_text('changed');(destination/'report.json').write_text('changed')
                raise RuntimeError('failed trial')
            with patch('modular_agent.realtime.validate_jump_rope_gear_experiments.validate',side_effect=fail):
                with self.assertRaisesRegex(RuntimeError,'failed trial'):run(root,['trial'])
            for name in ('replay.json','report.json'):self.assertEqual((out/name).read_text(),'original '+name)
    def test_success_isolates_experiment_and_restores_outputs(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);out=self.fixture(root)
            def success(*args,**kwargs):
                destination=kwargs['output_dir'];(destination/'replay.json').write_text('[]');(destination/'report.json').write_text('{}')
                return dict(sparse_state_checks=[],sparse_manual_checks=[dict(time=1,median_visible_error_px=2)],mode_changes=0,mean_inference_ms=1,p95_inference_ms=2)
            with patch('modular_agent.realtime.validate_jump_rope_gear_experiments.validate',side_effect=success):run(root,['trial'])
            self.assertEqual((out/'replay.json').read_text(),'original replay.json')
            self.assertEqual((out/'experiments/trial/replay.json').read_text(),'[]')
