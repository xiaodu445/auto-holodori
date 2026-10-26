import unittest
from pathlib import Path
import cv2
import numpy as np
from modular_agent.domains.hololive_dreams.visual_features import extract
from modular_agent.domains.hololive_dreams.states import classify,UIState
from modular_agent.perception.report import ScreenReport
from modular_agent.local_models import load_greed_cards
from test_greed_cards_tree import ROOT

class RobustWorldTests(unittest.TestCase):
 def load(self,identifier):
  p=ROOT/'domains/hololive_dreams/data/world_reference/20261017'/('codex-clipboard-'+identifier+'.png')
  return cv2.imdecode(np.fromfile(str(p),np.uint8),1)
 def state(self,image):
  features=extract(image,(0,0),ROOT)
  return classify(ScreenReport(frame={'world_features':features})).state
 def test_held_out_world_views_and_brightness_scale(self):
  for identifier in ('bb221f68-ab28-4349-ae45-85834c8837b7','d22387d7-d0d7-4fb6-b88e-647dce1d5ff6','54f291d1-67ac-45b1-89ac-72091daa8d04','71d0a821-6f9d-4a0b-ba32-cb7fda90d0d8','127322ce-d5e3-4fcc-b472-7a04f952c450'):
   image=self.load(identifier)
   for scale,brightness in ((1,1),(.9,.8),(1.03,1.1)):
    changed=cv2.convertScaleAbs(cv2.resize(image,None,fx=scale,fy=scale),alpha=brightness)
    self.assertEqual(self.state(changed),UIState.WORLD,identifier)
 def test_new_actor_and_new_dialogue_is_not_free_world(self):
  image=self.load('c7f97db7-665d-4e84-ab54-bf431076d47a')[43:801,318:1596]
  self.assertEqual(self.state(image),UIState.DIALOGUE)
  r=ScreenReport(frame={'world_features':extract(image,(0,0),ROOT)})
  decision=load_greed_cards(ROOT).decide(r)
  self.assertEqual(decision['state'],'dialogue')
  self.assertEqual(decision['key'],'e')
 def test_structural_map_and_overlays(self):
  samples=[
   ('7be9e448-7b6f-4a25-8a4f-fc705a07467d',UIState.OPTIONS),
   ('320db1de-9bc8-479a-a218-d2ce4b7c9115',UIState.MAP),
   ('13225c2e-73c0-4ca4-b400-ed9b4970d493',UIState.MAP),
   ('176ca6d9-7836-4e3e-867b-85ad052919de',UIState.REWARD),
   ('4aa3cfbb-cdf8-466e-8444-5b29863d4afd',UIState.REWARD),
   ('e1575559-6b3b-4a78-b537-f4db47e786f6',UIState.RANK_UP),
  ]
  for identifier,state in samples: self.assertEqual(self.state(self.load(identifier)),state,identifier)
 def test_target_detail_does_not_require_map_name_template(self):
  r=ScreenReport(frame={},knowledge_matches=[
   dict(label='entry_detail_greed'),dict(label='entry_move')])
  self.assertEqual(classify(r).state,UIState.LOCATION_DETAIL)

 def test_menu_rewards_and_game_pages_are_not_free_world(self):
  for identifier in ('34ef3779-8637-4f12-b031-482d4178e61f','6e0332fd-bd4f-4953-99b7-f17f23a9f3ba',
                     '9643959d-137c-4073-8a62-11d6770d5e91','0176249d-4f19-4fa9-a935-d91054896620',
                     'fa0ad74d-1844-420c-b209-c505d9aa7160','049a80a7-aa25-44ca-bb15-81f4d487d435',
                     '8aa2acca-3e60-4c4d-9117-2bfada427150'):
   self.assertNotEqual(self.state(self.load(identifier)),UIState.WORLD,identifier)

 def test_notification_with_rows_is_not_empty(self):
  features=extract(self.load('347c7a2a-03dd-4724-9d90-5f9a5c020577'),(0,0),ROOT)
  self.assertTrue(features['notification_panel'])
  self.assertGreaterEqual(features['notification_rows'],5)
  self.assertEqual(classify(ScreenReport(frame={'world_features':features})).state,UIState.NOTIFICATION)

 def test_shiori_gift_prompt_from_failure_screenshot(self):
  p=ROOT/'domains/hololive_dreams/data/world_reference/20261018/codex-clipboard-4328b6fa-9541-41c8-8987-32c8b632fef5.png'
  image=cv2.imdecode(np.fromfile(str(p),np.uint8),1)[74:807,415:1679]
  f=extract(image,(415,74),ROOT)
  self.assertTrue(f['gift_prompt'])
  self.assertEqual(classify(ScreenReport(frame={'world_features':f})).state,UIState.INTERACTION)
