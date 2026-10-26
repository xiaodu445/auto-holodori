import json
import tempfile
import unittest
from pathlib import Path
from modular_agent.realtime.validate_jump_rope_gear_experiments import summarize

class ComparisonTests(unittest.TestCase):
    def test_aggregate_keeps_all_saved_runs_and_uses_corrected_labels(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);labels=root/'domains/hololive_dreams/data/jump_rope_samples';labels.mkdir(parents=True)
            (labels/'state_validation.json').write_text(json.dumps(dict(samples=[dict(time=74,state='rotation_reverse')])))
            for name in ('earlier','latest'):
                path=root/'runtime/jump-rope/phase-gear/experiments'/name;path.mkdir(parents=True)
                (path/'report.json').write_text(json.dumps(dict(sparse_state_checks=[dict(time=74,expected='low_swing',observed='rotation_reverse')],sparse_manual_checks=[dict(time=74,median_visible_error_px=3)],mode_changes=8)))
            result=summarize(root)
            self.assertEqual(len(result),2);self.assertTrue(all(r['state_correct']==1 for r in result))
