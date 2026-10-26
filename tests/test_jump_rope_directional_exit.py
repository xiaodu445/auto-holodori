import json
from pathlib import Path
import unittest
from modular_agent.realtime.landing_trajectory_bank import LandingTrajectoryBank
ROOT=Path(__file__).resolve().parents[1]
def bank(entry=1):
    c=json.loads((ROOT/'domains/hololive_dreams/models/jump_rope/jump_rope_directional_exit_config.json').read_text())
    b=LandingTrajectoryBank(c,.4140625,.4);b.acquire(.2,0,entry)
    p=b.make('low_swing',.66 if entry==1 else .30,0,entry);p.entry_phase=p.phase
    b.items=[p];b.active=p.key;b.low_entry_direction=entry;b.low_turns={-1,1};b.low_played_cycles=1.2
    return b,p
class DirectionalExitTests(unittest.TestCase):
    def test_old_entry_crossing_cannot_spawn_reverse_on_front_to_back_pass(self):
        b,p=bank();p.phase=p.entry_phase-.004;b.advance(.04)
        self.assertLess(p.coordinate_velocity,0);self.assertEqual([x.mode for x in b.items],['low_swing'])
    def test_back_to_front_ground_crossing_spawns_reverse_only(self):
        b,p=bank();p.phase=b.swing_exit_boundary(p)-.004;b.advance(.04)
        children=[x for x in b.items if x.parent==p.key]
        self.assertEqual(len(children),4);self.assertTrue(all(x.mode=='rotation_reverse' for x in children))
        self.assertGreater(p.coordinate_velocity,0)
    def test_front_to_back_ground_crossing_spawns_forward_only(self):
        b,p=bank(-1);p.phase=b.swing_exit_boundary(p)-.004;b.advance(.04)
        children=[x for x in b.items if x.parent==p.key]
        self.assertEqual(len(children),4);self.assertTrue(all(x.mode=='rotation_forward' for x in children))
        self.assertLess(p.coordinate_velocity,0)
    def test_stale_reverse_and_image_recovery_blocked_after_wrong_half_turn(self):
        b,p=bank();p.phase=b.swing_exit_boundary(p)+.02
        q=b.make('rotation_reverse',.3,0,-1,parent=p.key);q.exit_supported=True;b.items.append(q)
        self.assertTrue(b.legal_successor(p,q,0))
        p.phase=.7
        self.assertFalse(b.legal_successor(p,q,0));self.assertIsNone(b.reconstruct_exit(.3,.735,.01,clock_rate=True))
    def test_mode_is_opposite_entry_not_current_swing_pass(self):
        for entry in [1,-1]:
            b,p=bank(entry);p.phase=b.swing_exit_boundary(p)+.01
            wrong='rotation_forward' if entry>0 else 'rotation_reverse'
            q=b.make(wrong,.3,0,parent=p.key);q.exit_supported=True
            self.assertFalse(b.legal_successor(p,q,0))
