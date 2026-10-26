import unittest
from unittest.mock import Mock
import cv2
import numpy as np
from modular_agent.domains.hololive_dreams.entry_search import match_entry
from modular_agent.domains.hololive_dreams.templates import MAP,DETAIL,WORLD,READY
from modular_agent.domains.hololive_dreams.visual_features import extract
from modular_agent.perception import KnowledgeMatcher,TemplateLibrary
from modular_agent.local_models import load_greed_cards
from test_greed_cards_tree import ROOT,report,HUD

class EntrySearchTests(unittest.TestCase):
 def test_dialogue_needs_no_knowledge_scan(self):
  matcher=Mock()
  matches,mode=match_entry(matcher,np.zeros((750,1264,3),np.uint8),'hololive_dreams',(0,0),{'dialogue':True},WORLD)
  self.assertEqual(matches,[]);matcher.match.assert_not_called()
 def test_roi_targets_remain_desktop_coordinates(self):
  folder=ROOT/'domains/hololive_dreams/data/world_reference/20261017'
  matcher=KnowledgeMatcher([TemplateLibrary(ROOT/'domains/hololive_dreams/vision_library')])
  samples=[('320db1de-9bc8-479a-a218-d2ce4b7c9115',{'entry_detail_greed','entry_move'}),
           ('71d0a821-6f9d-4a0b-ba32-cb7fda90d0d8',{'entry_interact'}),
           ('826b8d5c-5a0f-4762-b8c6-46652ade974b',set(READY))]
  for identifier,expected in samples:
   image=cv2.imdecode(np.fromfile(str(folder/f'codex-clipboard-{identifier}.png'),np.uint8),1)
   found,mode=match_entry(matcher,image,'hololive_dreams',(400,200),extract(image,(400,200),ROOT),MAP+DETAIL+WORLD+READY+['smallgame','map2'])
   self.assertTrue(expected<={m['label'] for m in found},identifier)
   self.assertTrue(all(m['bounds']['x']>=400 and m['bounds']['y']>=200 for m in found))
   self.assertEqual(mode['mode'],'regional')
 def test_returned_interaction_after_dialogue_can_resume_once(self):
  tree=load_greed_cards(ROOT);tree.committed({'state':'interact'})
  self.assertEqual(tree.decide(report(HUD+['猜高低']))['action'],'wait')
  tree.committed({'state':'dialogue'})
  d=tree.decide(report(HUD+['猜高低']))
  self.assertEqual(d['state'],'reinteract')
  tree.committed(d)
  self.assertEqual(tree.decide(report(HUD+['猜高低']))['action'],'wait')
 def test_wide_search_is_explicit(self):
  matcher=Mock();matcher.match.return_value=[]
  _,mode=match_entry(matcher,np.zeros((750,1264,3),np.uint8),'hololive_dreams',(0,0),{},['entry_search_wide'])
  self.assertEqual(mode['mode'],'wide_recovery')
