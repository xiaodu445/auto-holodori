import unittest
import cv2
import numpy as np
from modular_agent.domains.hololive_dreams.map_view import detect_zoom
from modular_agent.local_models import load_greed_cards
from test_greed_cards_tree import ROOT,report
class MapViewTests(unittest.TestCase):
 def image(self,identifier):
  p=ROOT/'domains/hololive_dreams/data/world_reference/20261017'/f'codex-clipboard-{identifier}.png'
  return cv2.imdecode(np.fromfile(str(p),np.uint8),1)
 def test_slider_positions_in_user_samples(self):
  full=self.image('97df886e-e794-4bf6-adcf-baf7c030204e')[162:911,443:1707]
  zoom=detect_zoom(full,(443,162))
  self.assertIsNotNone(zoom)
  self.assertGreater(zoom['knob']['x']-zoom['minimum']['x'],80)
  zoom=detect_zoom(self.image('6ce9b369-0be1-4b96-8a5c-6d00c6d2196a'))
  self.assertLessEqual(abs(zoom['knob']['x']-zoom['minimum']['x']),8)
 def test_bounded_map_recovery_and_no_repeated_area_click(self):
  tree=load_greed_cards(ROOT)
  r=report(['MAP','电玩巨蛋城','游玩区域'])
  r.frame['world_features']={'map_zoom':{'knob':{'x':1100,'y':700},'minimum':{'x':980,'y':700}}}
  d=tree.decide(r);self.assertEqual(d['state'],'select_area');tree.committed(d)
  for _ in range(2):
   d=tree.decide(r);self.assertEqual(d['state'],'map_zoom_out');tree.committed(d)
  for _ in range(2):
   d=tree.decide(r);self.assertEqual(d['state'],'map_pan');tree.committed(d)
  self.assertEqual(tree.decide(r)['state'],'map_target_missing')
 def test_missing_slider_never_blind_drags(self):
  tree=load_greed_cards(ROOT);tree.area_selected=True
  self.assertEqual(tree.decide(report(['MAP','电玩巨蛋城']))['outcome'],'unknown')
 def test_blank_image_has_no_slider(self):
  self.assertIsNone(detect_zoom(np.zeros((750,1264,3),np.uint8)))
