import copy
import unittest
from modular_agent.realtime.validate_jump_rope_gear_constraints import check

class ConstraintTests(unittest.TestCase):
    def row(self,t,phase,mode='rotation_forward',entry=None,key=1):
        return dict(time=t,observation=dict(motion_state=mode,low_swing_episode=int(entry is not None),low_entry_direction=entry,low_turns_observed=[],last_exit_recovered=False,selected_hypothesis=key,phase_estimate=dict(clock_rate=.5,speed_bounds=[.4,.6],phase_unwrapped=phase,continuation='template_playback')))
    def test_unobserved_first_frame_advances_both_directions(self):
        for mode,direction in [('rotation_forward',1),('rotation_reverse',-1),('low_swing',1)]:
            rows=[self.row(0,.3,mode,1),self.row(.02,.3+direction*.01,mode,1)]
            self.assertTrue(check(rows)['passed'])
    def test_frozen_or_out_of_bounds_clock_fails(self):
        rows=[self.row(0,.3),self.row(.02,.3)]
        self.assertFalse(check(rows)['passed'])
        rows[1]['observation']['phase_estimate']['clock_rate']=0
        self.assertEqual(check(rows)['nonpositive_clock_frames'],1)
    def test_direct_reverse_and_wrong_low_exit_fail(self):
        rows=[self.row(0,.3),self.row(.02,.4,'rotation_reverse',key=2)]
        self.assertFalse(check(rows)['passed'])
        rows=[self.row(0,.3,'low_swing',1),self.row(.02,.4,'rotation_forward',1,key=2)]
        self.assertEqual(check(rows)['wrong_exit_directions'],[.02])
    def test_visual_candidate_correction_is_not_counted_as_pure_prediction(self):
        rows=[self.row(0,.3),self.row(.02,.315)]
        rows[1]['observation']['phase_estimate']['continuation']='candidate_clock_correction'
        result=check(rows);self.assertTrue(result['passed']);self.assertEqual(result['pure_playback_checks'],0)
