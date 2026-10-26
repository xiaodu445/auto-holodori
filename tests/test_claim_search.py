import unittest
from pathlib import Path
from unittest.mock import Mock
import cv2
import numpy as np
from modular_agent.domains.hololive_dreams.claim_search import match_claims
from modular_agent.domains.hololive_dreams.claim_tasks import templates_for
from modular_agent.perception.general import GeneralVision

ROOT=Path(__file__).resolve().parents[1]

class ClaimSearchTests(unittest.TestCase):
 def test_available_is_small_roi_with_desktop_origin(self):
  m=Mock();m.match.return_value=[];m.last_diagnostics=[]
  match_claims(m,np.zeros((760,1280,3),np.uint8),'hololive_dreams',(400,200),{},['claim_available'])
  args,kw=m.match.call_args
  self.assertEqual(args[0].shape[:2],(585,179))
  self.assertEqual(args[2],(400+int(.82*1280),200+int(.22*760)))
  self.assertEqual(kw['template_names'],['claim_available'])
 def test_overlays_skip_all_claim_matching(self):
  for feature in ('reward','rank_up','dialogue'):
   m=Mock()
   result,meta=match_claims(m,np.zeros((760,1280,3),np.uint8),'hololive_dreams',(0,0),{feature:True},templates_for('achievements'))
   m.match.assert_not_called();self.assertEqual(result,[]);self.assertEqual(meta['mode'],'structure_only')
 def test_achievement_stage_excludes_event_and_task_templates(self):
  names=templates_for('achievements')
  self.assertIn('claim_available',names)
  self.assertNotIn('claim_event_page',names);self.assertNotIn('claim_pass_page',names)
 def test_user_screenshot_matches_three_words_without_ocr(self):
  p=ROOT/'domains/hololive_dreams/data/world_reference/20261018/codex-clipboard-7e04d7fc-42cf-44de-8dd6-7300a7561c45.png'
  image=cv2.imdecode(np.fromfile(str(p),np.uint8),1)
  ocr=Mock();ocr.recognize.side_effect=AssertionError('OCR must not run')
  vision=GeneralVision.for_project(ROOT,'hololive_dreams',ocr=ocr,enable_ocr=False,enable_uia=False,enable_cv_buttons=False)
  try:
   r=vision.analyze(image,environment='hololive_dreams',template_names=templates_for('achievements'),template_threshold=.92)
   matches=[m for m in r.knowledge_matches if m['label']=='claim_available']
   self.assertGreaterEqual(len(matches),5)
   self.assertEqual(r.frame['claim_search']['mode'],'regional')
   self.assertEqual(r.capabilities['ocr'],'disabled');ocr.recognize.assert_not_called()
  finally:vision.close()

if __name__=='__main__':unittest.main()
