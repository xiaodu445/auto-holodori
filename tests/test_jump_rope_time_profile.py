import json
import tempfile
import unittest
from pathlib import Path
from modular_agent.realtime.build_jump_rope_time_profile import build

class TemporalCalibrationTests(unittest.TestCase):
    def samples(self, second_min):
        rows=[]
        for start,low in [(18.,.49),(20.4,second_min)]:
            for i in range(14):
                y=low+i*.012
                rows.append(dict(time=start+i*.045,center_y=y,coordinate=min(1,max(0,(y-.42)/.24)),template_error=.001,fit_support=.8))
        return rows

    def test_crossings_exclude_unobserved_levels(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'samples.json').write_text(json.dumps(dict(rows=self.samples(.54))))
            result=build(root,'samples.json','out.json')
            self.assertEqual(result['provenance']['levels'],[.56,.59,.62])
            self.assertTrue(all(20.4<t<21.05 for t in result['provenance']['crossing_times'][1]))
            self.assertFalse(result['verified'])

    def test_insufficient_shared_crossings_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'samples.json').write_text(json.dumps(dict(rows=self.samples(.60))))
            with self.assertRaisesRegex(ValueError,'shared crossing'):
                build(root,'samples.json','out.json')
