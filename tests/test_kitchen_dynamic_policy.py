import unittest,json,tempfile,importlib.util
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from modular_agent.realtime.kitchen_match import Item,Observation,Settings,BatchController,TrayLedger,plan,policy_state
from modular_agent.realtime.kitchen_policy import confidence_state
ROOT=Path(__file__).resolve().parents[1]
class DynamicConfidenceTests(unittest.TestCase):
    def state(self,**kw):
        values=dict(free=7,visible=1,candidates=2,last_clicks=0,previous=.25,reliable=True,floor=.12);values.update(kw)
        return confidence_state(Settings(confidence=.25),**values)
    def test_first_round_uses_normal_threshold(self):self.assertEqual(self.state(last_clicks=None)['threshold'],.25)
    def test_lowers_gradually_and_never_below_floor(self):
        previous=.25
        for _ in range(20):
            value=self.state(previous=previous)['threshold']
            self.assertGreaterEqual(value,.12);self.assertLessEqual(value,previous);self.assertLessEqual(previous-value,.040001);previous=value
        self.assertLess(previous,.15)
    def test_slot_pressure_and_uncertainty_override_other_signals(self):
        for free in range(4):self.assertGreaterEqual(self.state(free=free,previous=.13)['threshold'],.25)
        self.assertEqual(self.state(reliable=False,previous=.13)['threshold'],.25)
    def test_many_clicks_or_dense_board_keep_normal_threshold(self):
        self.assertEqual(self.state(last_clicks=6)['threshold'],.25)
        self.assertEqual(self.state(visible=10)['threshold'],.25)
        self.assertEqual(self.state(candidates=30)['threshold'],.25)
    def test_more_free_slots_cannot_lower_safety_margin(self):
        values=[self.state(free=n,previous=.12)['threshold'] for n in range(4,8)]
        self.assertEqual(values,sorted(values,reverse=True))
    def test_pressure_threshold_obeys_ceiling(self):
        s=Settings(confidence=.25,confidence_ceiling=.27,confidence_pressure_boost=.2)
        result=confidence_state(s,free=1,visible=1,candidates=1,last_clicks=0,previous=.12,reliable=True,floor=.12)
        self.assertEqual(result['threshold'],.27)
    def test_slot_weight_must_dominate(self):
        with self.assertRaises(ValueError):Settings(confidence_slot_weight=.1)
    def test_low_candidate_can_be_used_after_confidence_decreases(self):
        item=Item('a','seaweed',20,30,.17,(10,20,30,40))
        detail=dict(last_round_clicks=0,previous_confidence=.17,tail_confidence=.12,tray_capacity_reliable=True,occupied_slots=0)
        ob=Observation(1,0,0,(item,),tray=('',)*7,ui_details=detail)
        self.assertEqual(plan(ob,set(),Settings(confidence=.25),0),(item,))
        detail=dict(detail,occupied_slots=5)
        ob=replace(ob,tray=('a','b','c','d','e','',''),ui_details=detail)
        self.assertEqual(plan(ob,set(),Settings(confidence=.25),0),())
class EnhancedTailTests(unittest.TestCase):
    def observation(self,free,count):
        items=tuple(Item(str(i),'item'+str(i),20+i*40,30,.9,(10+i*40,20,35+i*40,45)) for i in range(count))
        details=dict(last_round_clicks=0,previous_confidence=.25,tail_confidence=.12,tray_capacity_reliable=True,occupied_slots=7-free)
        return Observation(1,0,0,items,tray=tuple(['stored'+str(i) for i in range(7-free)]+['']*free),ui_details=details)
    def test_several_non_triples_can_be_taken_with_two_slots_reserved(self):
        ob=self.observation(7,5);trace=[];result=plan(ob,set(),Settings(confidence=.25,max_clicks=6),0,trace)
        self.assertEqual(len(result),3);self.assertTrue(all('强化残局' in row['reason'] for row in trace if row['selected']))
    def test_raw_budget_is_never_exceeded_for_unmatched_items(self):
        for free in range(8):
            for count in range(1,10):
                result=plan(self.observation(free,count),set(),Settings(confidence=.25),0)
                self.assertLessEqual(len(result),max(0,free-2))
    def test_unreliable_slots_do_not_enable_multi_pick(self):
        ob=self.observation(7,5);ob=replace(ob,ui_details=dict(ob.ui_details,tray_capacity_reliable=False))
        self.assertLessEqual(len(plan(ob,set(),Settings(confidence=.25),0)),1)
    def test_only_targets_and_max_clicks_are_preserved(self):
        ob=self.observation(7,5)
        self.assertEqual(plan(ob,set(),Settings(confidence=.25,only_targets=True),0),())
        result=plan(ob,set(),Settings(confidence=.25,max_clicks=3,tail_max_singles=6,tail_reserve_slots=1),0)
        self.assertEqual(len(result),3)
    def test_execution_does_not_spend_future_match_removals(self):
        ob=self.observation(5,4);ledger=TrayLedger(use_vision=False);ledger.items=['stored0','stored1']
        controller=BatchController(Settings(confidence=.25,tail_max_singles=6,max_clicks=6),ledger)
        clicks=[];controller.execute(ob,set(),clock=lambda:0,wait=lambda _:False,stopped=lambda:False,guard=lambda:None,click=clicks.append,latest=lambda:ob,emit=lambda *a,**k:None)
        self.assertEqual(len(clicks),3);self.assertEqual(len(ledger.items),5)
class AdvancedPreferencesTests(unittest.TestCase):
    def test_all_advanced_values_and_switches_survive_restart(self):
        import tkinter as tk
        spec=importlib.util.spec_from_file_location('dynamic_control',ROOT/'tools/kitchen_control.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as tmp:
            module.ROOT=Path(tmp);(module.ROOT/'data/kitchen').mkdir(parents=True);(module.ROOT/'data/kitchen/runtime-profile.json').write_text(json.dumps(dict(weights='unused.pt')))
            root=tk.Tk();root.withdraw()
            try:
                app=module.Control(root);app.policy_vars['confidence_step'].set('.02');app.policy_vars['tail_max_singles'].set('4');app.adaptive_confidence.set(False);app.save_preferences()
                again=module.Control(root);self.assertEqual(again.policy_vars['confidence_step'].get(),'.02');self.assertEqual(again.policy_vars['tail_max_singles'].get(),'4');self.assertFalse(again.adaptive_confidence.get())
                again.adaptive_confidence.set(True)
                with patch.object(module.subprocess,'Popen') as process:
                    again.start();args=process.call_args.args[0];self.assertIn('--confidence-step',args);self.assertEqual(args[args.index('--tail-max-singles')+1],'4')
                    again.stop()
            finally:root.destroy()
