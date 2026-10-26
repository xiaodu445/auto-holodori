import unittest
from types import SimpleNamespace
from pathlib import Path
import cv2
import numpy as np
from modular_agent.agent.entry_observer import EntryObserver
from modular_agent.perception import KnowledgeMatcher, TemplateLibrary
from modular_agent.perception.report import ScreenReport
from modular_agent.local_models import load_greed_cards
from test_greed_cards_tree import ROOT
from test_connected_agent import Computer

class EntryObserverTests(unittest.TestCase):
 def make(self,report):
  calls=[]
  class Vision:
   def windows(self): return report.windows
   def observe(self,**kwargs): calls.append(kwargs);return report
  vision=Vision();vision.desktop=vision
  adapter=SimpleNamespace(profiles=[dict(domain='hololive_dreams',window_title_patterns=['hololive'])],
                          computer=Computer(),_vision_for=lambda domain:vision)
  return EntryObserver(adapter,load_greed_cards(ROOT),lambda s:None,clock=lambda:10),calls
 def test_ocr_is_bounded_and_uia_disabled(self):
  r=ScreenReport(frame={'target_window_handle':7},windows=[dict(handle=7,title='hololive Dreams',foreground=True)])
  observer,calls=self.make(r)
  now=[0];observer.clock=lambda:now[0]
  observer();observer();observer();observer()
  self.assertEqual(sum(c['enable_ocr'] for c in calls),0)
  now[0]=5;observer();observer()
  self.assertEqual(sum(c['enable_ocr'] for c in calls),1)
  self.assertTrue(all(not c['enable_uia'] for c in calls))
 def test_archived_map_detail_interaction_dialogue_and_ready(self):
  folder=ROOT/'domains/hololive_dreams/data/world_reference/20261017'
  library=TemplateLibrary(ROOT/'domains/hololive_dreams/vision_library')
  matcher=KnowledgeMatcher([library])
  names=[r.name for r in library.records() if r.name.startswith('entry_')]
  samples=[
   ('8e6f38a1-d645-4bb5-8941-cd90ac89b6d6',{'entry_map_arcade','entry_area'}),
   ('320db1de-9bc8-479a-a218-d2ce4b7c9115',{'entry_detail_greed','entry_move'}),
   ('71d0a821-6f9d-4a0b-ba32-cb7fda90d0d8',{'entry_interact'}),
   ('ab709d1b-1754-4fcc-9222-766a22aa604a',{'entry_dialogue'}),
   ('826b8d5c-5a0f-4762-b8c6-46652ade974b',{'entry_ready_logo','entry_ready_start'}),
  ]
  for identifier,expected in samples:
   image=cv2.imdecode(np.fromfile(str(folder/f'codex-clipboard-{identifier}.png'),dtype=np.uint8),cv2.IMREAD_COLOR)
   matches=matcher.match(image,'hololive_dreams',template_names=names)
   labels={m['label'] for m in matches}
   self.assertTrue(expected<=labels,(identifier,expected-labels))
   if 'entry_ready_logo' not in expected:
    self.assertFalse({'entry_ready_logo','entry_ready_start'}<=labels)
