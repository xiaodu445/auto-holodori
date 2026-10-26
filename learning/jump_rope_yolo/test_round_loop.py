import csv,json,tempfile,unittest
from pathlib import Path
import numpy as np
from round_loop import RoundLoop,ScreenReader
class FakeReader:
 def __init__(self):self.name=None;self.value=63;self.play=False
 def classify(self,image):return self.name,{}
 def score(self,image):return self.value,[]
 def gameplay(self,image):return self.play
class LoopTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.reader=FakeReader();self.loop=RoundLoop(self.tmp.name,reader=self.reader);self.image=np.zeros((10,10,3),np.uint8)
 def screen(self,name,start,duration=1.5):
  self.reader.name=name;actions=[]
  for i in range(round(duration/.1)+1):actions.append(self.loop.update(self.image,start+i*.1))
  return actions
 def test_full_sequence_and_single_score(self):
  for n,name in enumerate(('result','rewards','event','menu')):
   actions=self.screen(name,n*3);self.assertEqual(sum(a['click'] is not None for a in actions),1)
   self.assertTrue(all(a['block_jump'] for a in actions))
  rows=[json.loads(s) for s in (Path(self.tmp.name)/'scores.jsonl').read_text().splitlines()]
  self.assertEqual(len(rows),1);self.assertEqual(rows[0]['score'],63)
  self.reader.name=None;self.reader.play=True
  self.loop.update(self.image,12);action=self.loop.update(self.image,12.6)
  self.assertTrue(action['new_round']);self.assertFalse(action['block_jump'])
 def test_transition_never_blind_clicks(self):
  self.screen('rewards',0);self.reader.name=None
  action=self.loop.update(self.image,6)
  self.assertIsNone(action['click']);self.assertTrue(action['block_jump'])
 def test_uncertain_score_keeps_screenshot(self):
  self.reader.value=None;self.screen('result',0)
  row=json.loads((Path(self.tmp.name)/'scores.jsonl').read_text())
  self.assertIsNone(row['score']);self.assertEqual(row['score_status'],'needs_review');self.assertTrue((Path(self.tmp.name)/row['screenshot']).exists())
 def test_one_frame_flash_does_not_click(self):
  self.reader.name='result';self.assertIsNone(self.loop.update(self.image,0)['click'])
  self.reader.name=None;self.loop.update(self.image,.1)
  self.reader.name='result';self.assertIsNone(self.loop.update(self.image,2)['click'])
 def test_retries_stop_after_three(self):
  actions=self.screen('menu',0,12)
  self.assertEqual(sum(a['click'] is not None for a in actions),3)
 def test_new_round_can_record_next_score(self):
  self.screen('result',0);self.screen('menu',3);self.reader.name=None;self.reader.play=True
  self.loop.update(self.image,6);self.loop.update(self.image,6.6)
  self.reader.value=321;self.screen('result',9)
  rows=[json.loads(s) for s in (Path(self.tmp.name)/'scores.jsonl').read_text().splitlines()]
  self.assertEqual([r['score'] for r in rows],[63,321])
if __name__=='__main__':unittest.main()
