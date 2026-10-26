import unittest,json
from pathlib import Path
from modular_agent.realtime.trajectory_bank import DirectionWarp

class AudioDecelerateAssetTests(unittest.TestCase):
    def test_source_measured_forward_rate_and_monotone_shape(self):
        root=Path(__file__).resolve().parents[1]
        profiles=json.loads((root/'domains/hololive_dreams/data/jump_rope_phase/audio_forward_decelerate_trial.json').read_text(encoding='utf-8'))
        b=profiles['stages'][2]['branches']['decelerate']
        self.assertAlmostEqual(b['clock_rate'],.5475)
        assert not b['verified']
        assert set(b['directions'])=={'rotation_forward'}
        warp=DirectionWarp(b['directions']['rotation_forward'])
        assert min(warp.evaluate(i/100)[1] for i in range(100))>0
        assert b['status']!='pending_calibration'
