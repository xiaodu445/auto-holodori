import json
import unittest
import tempfile
from pathlib import Path
import numpy as np
from modular_agent.realtime.build_measured_rope_library import build

class MeasuredLibraryTests(unittest.TestCase):
    def test_future_rejection_semantics_and_independent_reverse_curve(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup);tmp_path=Path(temporary.name)
        fit=dict(direction=-1,rate=1.2,a=.2,b=-.4,train_score=.8,future_check_score=.8,runner_margin=.2,cycles=3)
        good=dict(start=20,end=24,count_stage_hint=2,source_time_origin=20.01,future_interval=[23,24],best=fit)
        bad=dict(good,start=24,end=28,best=dict(fit,future_check_score=.1))
        windows=tmp_path/'windows.json';atlas=tmp_path/'atlas.json';out=tmp_path/'out.json'
        windows.write_text(json.dumps(dict(recording='test',windows=[good,bad])))
        atlas.write_text(json.dumps(dict(provenance=dict(source_window=[9,19]))))
        r=build(windows,atlas,out)
        assert len(r['templates'])==1 and len(r['rejected_windows'])==1
        f=r['templates'][0]
        assert f['skill_role'] is None and f['effective_speed_stage'] is None
        assert f['source_time_origin']==20.01
        assert np.all(np.array(f['image_phase_velocity_cycles_per_second'])<0)
        u=np.array(f['clock_nodes']);phase=np.array(f['angle_nodes'])
        expected=-np.gradient(phase,u)*f['clock_rate']
        assert np.allclose(expected[1:-1],f['image_phase_velocity_cycles_per_second'][1:-1],atol=.001)
