import unittest,json
from pathlib import Path
from modular_agent.realtime.landing_trajectory_bank import LandingTrajectoryBank
from modular_agent.realtime.audio_cues import low_entry_authorized

class PrefixRetentionTests(unittest.TestCase):
    def test_boundary_candidate_survives_prefix_delay_but_expires(self):
        root=Path(__file__).resolve().parents[1]
        settings=json.loads((root/'domains/hololive_dreams/models/jump_rope_audio_prefix_config.json').read_text(encoding='utf-8'))
        bank=LandingTrajectoryBank(settings,.5,.1);bank.acquire(.1,10.)
        active=next(p for p in bank.items if p.key==bank.active)
        candidate=bank.make('low_swing',.1,0,active.direction,.8,active.key)
        bank.items.append(candidate);bank.advance(11.)
        assert any(p.key==candidate.key for p in bank.items)
        bank.advance(11.3)
        assert all(p.key!=candidate.key for p in bank.items)
    def test_prefix_authorization_is_short_lived_and_not_obstacle(self):
        event=dict(motion_hint='low_swing',time=24.284,distance=.025,margin=.135)
        assert low_entry_authorized(event,24.356,lifetime=.4,threshold=.22,margin=.05)
        assert not low_entry_authorized(event,24.7,lifetime=.4,threshold=.22,margin=.05)
        assert not low_entry_authorized(dict(event,motion_hint=None),24.356,lifetime=.4,threshold=.22,margin=.05)
