import ast,json,unittest
from pathlib import Path
import numpy as np
HERE=Path(__file__).parent
node=next(n for n in ast.parse((HERE/'game_jump_live.py').read_text(encoding='utf-8')).body if isinstance(n,ast.ClassDef) and n.name=='StageHint')
ns={'np':np,'json':json,'HERE':HERE,'counter_glyphs':lambda image:image}
exec(compile(ast.Module(body=[node],type_ignores=[]),'StageHint','exec'),ns)
class StageConfirmationTests(unittest.TestCase):
 def hint(self):
  h=ns['StageHint']();h.stage=3
  h.refs={str(i):[np.eye(10,dtype=bool)[i]] for i in range(10)}
  return h
 def digits(self,n):return [np.eye(10,dtype=bool)[int(k)] for k in str(n)]
 def test_sparse_high_reads_do_not_skip_stage(self):
  h=self.hint();h.update(self.digits(75),0);h.update([], .03);h.update(self.digits(75),1)
  self.assertEqual(h.stage,3)
 def test_lower_read_breaks_confirmation(self):
  h=self.hint()
  for t in (0,.1,.2):h.update(self.digits(75),t)
  h.update(self.digits(35),.3);h.update(self.digits(75),.7)
  self.assertEqual(h.stage,3)
 def test_adjacent_stage_requires_continuous_confirmation(self):
  h=self.hint()
  for t in (0,.1,.21):h.update(self.digits(50),t)
  self.assertEqual(h.stage,4)
 def test_sustained_high_reads_can_resume_midgame(self):
  h=self.hint()
  for i in range(8):h.update(self.digits(75),i*.1)
  self.assertEqual(h.stage,5)
if __name__=='__main__':unittest.main()
