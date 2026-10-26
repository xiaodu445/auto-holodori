import unittest,importlib.util,json,tempfile,os,shutil
from pathlib import Path
from modular_agent.realtime.kitchen_diagnostics import snapshot
from modular_agent.realtime.kitchen_match import Item,Observation,Settings,plan
from dataclasses import asdict
ROOT=Path(__file__).resolve().parents[1]

class DiagnosticsTests(unittest.TestCase):
    def test_snapshot_does_not_use_future_events(self):
        events=[dict(type='session_start',t=0,settings={}),dict(type='tray_ledger',t=1,logical_tray=['chili']+['']*6),dict(type='click_sent',t=3,item=dict(class_id='milk_blue'),logical_tray=['milk_blue']+['']*6)]
        state=snapshot(events,2)
        self.assertEqual(state['logical_tray'][0],'chili');self.assertIsNone(state['last_click'])
    def test_trace_explains_capacity_and_does_not_change_output(self):
        items=tuple(Item(str(i),'chili',20+i*30,30,.9,(10+i*30,20,30+i*30,40)) for i in range(3))
        ob=Observation(1,0,0,items,tray=('a','b','c','d','','',''))
        trace=[];self.assertEqual(plan(ob,set(),Settings(),0,trace),plan(ob,set(),Settings(),0))
        self.assertEqual(len(trace),3);self.assertTrue(all('预留' in r['reason'] for r in trace))
    def test_recorded_decision_has_priority_over_reconstruction(self):
        ob=Observation(1,0,0,())
        events=[dict(type='session_start',t=0,settings={}),dict(type='detection',t=.1,observation=asdict(ob)),dict(type='decision',t=.2,frame_id=1,items=[],logical_tray=['chili']+['']*6)]
        state=snapshot(events,.3);self.assertEqual(state['source'],'当时实际决策日志');self.assertEqual(state['decision_tray'][0],'chili')
    def test_real_replay_ui_and_issue_export(self):
        import tkinter as tk
        spec=importlib.util.spec_from_file_location('diagnostic_replay',ROOT/'tools/kitchen_replay.py');mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
        source=mod.latest_session(ROOT/'runtime/kitchen/sessions')
        if source is None:self.skipTest('no local replay')
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)
            for name in ['timestamps.json','events.jsonl']:shutil.copyfile(source/name,target/name)
            try:os.link(source/'screen.avi',target/'screen.avi')
            except OSError:shutil.copyfile(source/'screen.avi',target/'screen.avi')
            root=tk.Tk();root.withdraw()
            try:
                app=mod.Replay(root,target);app.draw(len(app.stamps)//2)
                app.note.insert('1.0','应该先补齐香肠');app.save_issue()
                saved=json.loads((target/'review-issues.json').read_text(encoding='utf-8'))
                self.assertEqual(saved[0]['note'],'应该先补齐香肠');self.assertTrue((target/saved[0]['screenshot']).exists())
                app.seek_decision(-1);app.close()
            except Exception:
                root.destroy();raise


class SlotEvidenceTimelineTests(unittest.TestCase):
    def test_slot_evidence_and_correction_are_separate_and_never_future(self):
        packet=dict(captured=1.,frame_id=1,prefix=[],slots=[],occupied_count=0)
        events=[dict(type='tray_correction',t=1.1,evidence=packet,before=['can'],logical_tray=[]),dict(type='tray_visual_evidence',t=2.,evidence=dict(packet,captured=1.9)),dict(type='tray_correction',t=3.,evidence=packet,logical_tray=['can'])]
        state=snapshot(events,2.1)
        self.assertEqual(state['slot_reading']['t'],2.)
        self.assertEqual(state['slot_correction']['t'],1.1)
        self.assertEqual(state['logical_tray'],[])


class DynamicPolicyDisplayTests(unittest.TestCase):
    def test_recorded_threshold_has_priority_over_reconstruction(self):
        from dataclasses import asdict
        from modular_agent.realtime.kitchen_match import Observation
        observation=Observation(1,0,0,())
        policy=dict(threshold=.17,reason='空槽充足',free=7,visible=1,last_clicks=0)
        events=[dict(type='session_start',t=0,settings={}),dict(type='detection',t=.1,observation=asdict(observation)),dict(type='decision',t=.2,frame_id=1,items=[],logical_tray=['']*7,confidence_policy=policy)]
        self.assertEqual(snapshot(events,.3)['confidence_policy'],policy)
