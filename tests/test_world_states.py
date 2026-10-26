import json
import tempfile
import unittest
from modular_agent.domains.hololive_dreams.states import classify, UIState
from modular_agent.domains.hololive_dreams.trace import EntryTrace
from test_greed_cards_tree import report, HUD, BET, ROOT
from modular_agent.local_models import load_greed_cards
from test_connected_agent import Computer

class WorldStatesTests(unittest.TestCase):
 def test_overlay_precedes_background_hud(self):
  for words,state in ((['GET!'],UIState.REWARD),(['RANK UP!'],UIState.RANK_UP),
                      (['连接失败'],UIState.ERROR),
                      (['Shiori','为了抓住机会'],UIState.DIALOGUE)):
   self.assertEqual(classify(report(HUD+words)).state,state)
 def test_map_detail_and_ready_are_distinct(self):
  self.assertEqual(classify(report(['MAP','电玩巨蛋城'])).state,UIState.MAP)
  self.assertEqual(classify(report(['MAP','电玩巨蛋城','移动'])).state,UIState.LOCATION_DETAIL)
  self.assertEqual(classify(report(BET)).state,UIState.GREED_READY)
 def test_entry_refuses_background_navigation_under_rewards(self):
  self.assertEqual(load_greed_cards(ROOT).decide(report(HUD+['GET!']))['state'],'overlay')
 def test_per_run_result_and_decision_evidence(self):
  with tempfile.TemporaryDirectory() as root:
   tree=load_greed_cards(ROOT);tree.trace=EntryTrace(root)
   result=tree.run(lambda:report(BET),Computer())
   rows=[json.loads(s) for s in (tree.trace.directory/'events.jsonl').read_text(encoding='utf-8').splitlines()]
   self.assertEqual(rows[0]['event'],'decision')
   self.assertEqual(rows[0]['ui']['state'],'minigame.greed.ready')
   self.assertEqual(rows[-1]['event'],'result')
   self.assertEqual(result['trace_directory'],str(tree.trace.directory))
   self.assertTrue((tree.trace.directory/'result.json').is_file())
