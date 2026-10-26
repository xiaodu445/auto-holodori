import unittest, tempfile,json,importlib.util
from pathlib import Path
from dataclasses import replace
from types import SimpleNamespace
import numpy as np
from modular_agent.realtime.kitchen_match import Item,Observation,Settings,plan,BatchController,Latest
from modular_agent.realtime.kitchen_session import SessionRecorder

def item(i,cls='chili',score=.9):
    x=20+i*30
    return Item(str(i),cls,x,30,score,(x-10,20,x+10,40))
def obs(items=None,frame=1,t=0):return Observation(frame,t,t,tuple(items if items is not None else [item(i) for i in range(3)]))

class KitchenPlannerTests(unittest.TestCase):
    def test_target_triples_first_and_remainder_not_clicked(self):
        image=obs([item(i,'milk_blue',.8) for i in range(4)]+[item(i,'chili') for i in range(4,10)])
        batch=plan(image,{'milk_blue'},Settings(),0)
        self.assertEqual([p.class_id for p in batch[:3]],['milk_blue']*3)
        self.assertEqual(len(batch),9)
    def test_duplicate_instances_cannot_form_fake_triple(self):
        a=item(0);b=replace(a,instance_id='duplicate');c=item(1)
        self.assertFalse(plan(obs([a,b,c]),set(),Settings(),0))
    def test_unknown_popup_disabled_stale_and_low_confidence_are_blocked(self):
        for image,now in [(replace(obs(),scene='popup'),0),(replace(obs(),scene='unknown'),0),(replace(obs(),enabled=False),0),(obs(),1),(obs([item(i,score=.1) for i in range(3)]),0)]:
            self.assertFalse(plan(image,set(),Settings(),now))
    def test_budget_only_contains_whole_triples(self):
        self.assertEqual(len(plan(obs([item(i) for i in range(9)]),set(),Settings(max_clicks=5),0)),3)
    def test_invalid_click_outside_box_is_rejected(self):
        self.assertFalse(plan(obs([replace(item(i),x=-100) for i in range(3)]),set(),Settings(),0))
    def test_mailbox_keeps_latest_only(self):
        box=Latest();box.put(1);box.put(2);self.assertEqual(box.get(),2)

class KitchenBatchTests(unittest.TestCase):
    def execute(self,controller=None,cancel_after=None,popup_after=None,guard_error=False):
        c=controller or BatchController(Settings(verify_removal=True));now=[0.0];clicks=[];events=[]
        def wait(delay):now[0]+=delay;return False
        def guard():
            if guard_error:raise RuntimeError('focus_lost')
        c.execute(obs(),set(),clock=lambda:now[0],wait=wait,stopped=lambda:cancel_after is not None and len(clicks)>=cancel_after,guard=guard,click=lambda p:clicks.append((now[0],p)),latest=lambda:replace(obs(),scene='popup') if popup_after is not None and len(clicks)>=popup_after else obs(),emit=lambda k,**d:events.append((k,d)))
        return c,now,clicks,events
    def test_five_ms_is_minimum_between_sent_clicks(self):
        c,now,clicks,events=self.execute();self.assertEqual([round(t,3) for t,p in clicks],[0,.005,.010]);self.assertEqual(len(c.pending),3)
        self.assertFalse(events[-1][1]['verified'])
    def test_dropped_input_does_not_blindly_repeat(self):
        c,now,clicks,_=self.execute();self.assertEqual(c.reconcile(obs(frame=2,t=.3),.3),'waiting')
        self.assertEqual(c.reconcile(obs(frame=3,t=2),2),'unconfirmed_batch')
        c.execute(obs(frame=4,t=2),set(),clock=lambda:2,wait=lambda _:False,stopped=lambda:False,guard=lambda:None,click=lambda p:clicks.append(p),latest=lambda:None,emit=lambda *a,**k:None)
        self.assertEqual(len(clicks),3)
    def test_pre_batch_inference_result_cannot_confirm_disappearance(self):
        c,_,_,_=self.execute();self.assertEqual(c.reconcile(obs([],frame=2,t=.005),.3),'waiting');self.assertTrue(c.pending)
    def test_two_fresh_observations_confirm_only_visual_disappearance(self):
        c,_,_,_=self.execute()
        self.assertEqual(c.reconcile(obs([],frame=2,t=.3),.3),'waiting')
        self.assertEqual(c.reconcile(obs([],frame=2,t=.3),.4),'waiting')
        self.assertEqual(c.reconcile(obs([],frame=3,t=.5),.5),'targets_no_longer_detected');self.assertFalse(c.pending)
    def test_cancellation_and_delayed_popup_interrupt_pending_batch(self):
        for kwargs in [dict(cancel_after=1),dict(popup_after=1)]:
            c,_,clicks,events=self.execute(**kwargs);self.assertEqual(len(clicks),1);self.assertTrue(events[-1][1]['partial'])
    def test_focus_failure_sends_nothing(self):
        with self.assertRaisesRegex(RuntimeError,'focus_lost'):self.execute(guard_error=True)

class KitchenReplayTests(unittest.TestCase):
    def test_round_record_and_readonly_viewer(self):
        import tkinter as tk
        with tempfile.TemporaryDirectory() as folder:
            output=Path(folder)/'round';rec=SessionRecorder(output,30)
            for i,t in enumerate([.0,.031,.081]):rec.frame(np.zeros((100,160,3),np.uint8),i,t)
            rec.event('detection',t=.01,observation=__import__('dataclasses').asdict(obs()))
            rec.event('click_sent',t=.04,item=__import__('dataclasses').asdict(item(0)),verified=False)
            rec.close(reason='cancelled',sends_input=False);rec.close()
            self.assertTrue((output/'screen.avi').exists());self.assertEqual([s['t'] for s in json.loads((output/'timestamps.json').read_text())],[.0,.031,.081])
            self.assertFalse(json.loads((output/'summary.json').read_text())['verified'])
            spec=importlib.util.spec_from_file_location('kitchen_replay_test',Path(__file__).resolve().parents[1]/'tools/kitchen_replay.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
            root=tk.Tk();root.withdraw()
            try:
                view=m.Replay(root,output);view.step(1);self.assertEqual(view.index,1);view.toggle();view.pause();view.close()
            finally:
                try:root.destroy()
                except tk.TclError:pass
    def test_realtime_policy_refuses_menu_retry(self):
        from modular_agent.domains.hololive_dreams.interaction import policy_for,RetryBudget
        self.assertFalse(RetryBudget(policy_for('kitchen_play')).ready(1))


class KitchenPipelineTests(unittest.TestCase):
    def test_capture_continues_during_slow_inference_without_input(self):
        import time
        from unittest.mock import patch
        from modular_agent.realtime.kitchen_play import live_round
        counters=dict(captured=0,detected=0)
        class Capture:
            def __init__(self,handle):pass
            def bounds(self):return (0,0,160,100)
            def grab(self,roi):
                counters['captured']+=1
                return np.zeros((100,160,3),np.uint8),self.bounds()
            def close(self):pass
        class Detector:
            def predict(self,image,index,stamp,clock,bounds):
                time.sleep(.04);counters['detected']+=1
                return replace(obs(frame=index,t=stamp),finished=clock(),bounds=bounds)
        args=SimpleNamespace(window_handle=1,window_title='',start_delay=0,fps=60,duration=.22,live=False,max_batches=5,idle_timeout=2)
        with tempfile.TemporaryDirectory() as folder:
            rec=SessionRecorder(Path(folder)/'round')
            with patch('modular_agent.computer.windows.WindowsBackend'),patch('modular_agent.realtime.runtime.WindowCapture',Capture):
                result=live_round(args,Detector(),rec,Settings(),{'chili'})
            rec.close(**result)
            self.assertGreater(counters['captured'],counters['detected'])
            self.assertEqual(result['clicks_sent'],0)
            self.assertFalse(result['sends_input'])
            self.assertTrue(any(e['type']=='preview_plan' for e in rec.events))
    def test_live_replay_conflict_rejected_before_model_or_backend(self):
        from modular_agent.realtime.kitchen_play import main
        from unittest.mock import patch
        with patch('modular_agent.realtime.kitchen_play.KitchenDetector') as model:
            with self.assertRaises(SystemExit):main(['--live','--recording','unused'])
            model.assert_not_called()


class KitchenCurrentIntegrationTests(unittest.TestCase):
    def test_runtime_model_pin_wins_over_newer_experiment(self):
        from modular_agent.realtime.kitchen_vision import choose_weights
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'data/kitchen').mkdir(parents=True)
            fixed=root/'fixed.pt';fixed.write_bytes(b'fixture')
            (root/'data/kitchen/runtime-profile.json').write_text(json.dumps(dict(weights='fixed.pt')))
            self.assertEqual(choose_weights(root),fixed)
            fixed.unlink()
            with self.assertRaises(ValueError):choose_weights(root)
    def test_live_defaults_to_all_triples_without_manual_targets(self):
        from modular_agent.realtime.kitchen_play import main
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            with patch('modular_agent.realtime.kitchen_play.KitchenDetector'),patch('modular_agent.realtime.kitchen_play.live_round',return_value=dict(reason='mocked',sends_input=False)) as run:
                main(['--live','--weights','unused.pt','--output',str(Path(folder)/'round')])
                self.assertEqual(run.call_args.args[4],set())
    def test_control_starts_no_targets_and_stops_without_killing_process(self):
        import tkinter as tk
        from unittest.mock import patch
        spec=importlib.util.spec_from_file_location('kitchen_control_test',Path(__file__).resolve().parents[1]/'tools/kitchen_control.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as folder:
            m.ROOT=Path(folder);(m.ROOT/'data/kitchen').mkdir(parents=True)
            (m.ROOT/'data/kitchen/runtime-profile.json').write_text(json.dumps(dict(weights='fixed.pt')))
            root=tk.Tk();root.withdraw()
            try:
                app=m.Control(root);app.mode.set('live')
                with patch.object(m.subprocess,'Popen') as process:
                    app.start();args=process.call_args.args[0]
                    self.assertIn('--live',args);self.assertEqual(args[args.index('--targets')+1],'')
                    app.stop();self.assertTrue(app.stop_path.exists());process.return_value.kill.assert_not_called()
                    app.close()
            finally:
                try:root.destroy()
                except tk.TclError:pass


class KitchenBatchDelayTests(unittest.TestCase):
    def test_default_waits_half_second_and_requires_post_wait_capture(self):
        c=BatchController();c.pending=(item(0),);c.last_sent=.01;c.last_frame=1
        self.assertEqual(c.reconcile(obs(frame=2,t=.5),.5),'waiting')
        self.assertEqual(c.reconcile(obs(frame=3,t=.50),.7),'waiting')
        # Items still visible are allowed: no disappearance confirmation.
        self.assertEqual(c.reconcile(obs(frame=4,t=1.02),1.2),'batch_interval_elapsed')
        self.assertFalse(c.pending)
    def test_default_does_not_time_out_for_unchanged_targets(self):
        c=BatchController();c.pending=(item(0),);c.last_sent=0;c.last_frame=1
        self.assertEqual(c.reconcile(obs(frame=2,t=2),2),'batch_interval_elapsed')
    def test_popup_still_blocks_during_cooldown(self):
        c=BatchController();c.pending=(item(0),);c.last_sent=0
        self.assertEqual(c.reconcile(replace(obs(frame=2,t=2),scene='popup'),2),'blocked')


class KitchenRecoveryAndPointTests(unittest.TestCase):
    def test_transient_scene_pauses_and_two_fresh_frames_resume(self):
        from modular_agent.realtime.kitchen_match import ScenePauseGate
        gate=ScenePauseGate(60)
        self.assertEqual(gate.update('playing',0,0),'playing')
        self.assertEqual(gate.update('unknown',1,1),'paused')
        self.assertEqual(gate.update('unknown',2,20),'paused')
        self.assertEqual(gate.update('playing',3,21),'paused')
        self.assertEqual(gate.update('playing',3,21.1),'paused')
        self.assertEqual(gate.update('playing',4,21.2),'resumed')
        self.assertEqual(gate.update('playing',5,22),'playing')
    def test_persistent_scene_still_has_timeout(self):
        from modular_agent.realtime.kitchen_match import ScenePauseGate
        gate=ScenePauseGate(60);gate.update('unknown',0,0)
        self.assertEqual(gate.update('unknown',2,61),'timeout')
    def test_missing_or_outside_keypoint_keeps_box_with_fallback(self):
        from modular_agent.realtime.kitchen_vision import select_click_point
        for kp in [None,[0,0,0],[200,200,1],[float('nan'),15,1]]:
            x,y,score,source=select_click_point((10,10,30,30),kp)
            self.assertTrue(10<=x<30 and 10<=y<30);self.assertTrue(source.startswith('box_fallback'))
        self.assertEqual(select_click_point((10,10,30,30),[15,15,.9]),(15,15,.9,'keypoint'))
    def test_fallback_avoids_other_box_when_geometrically_possible(self):
        from modular_agent.realtime.kitchen_vision import select_click_point
        x,y,_,source=select_click_point((0,0,100,100),None,[(35,0,100,100)])
        self.assertLess(x,35);self.assertEqual(source,'box_fallback')
    def test_pipeline_records_through_popup_and_resumes(self):
        import time
        from unittest.mock import patch
        from modular_agent.realtime.kitchen_play import live_round
        class Capture:
            def __init__(self,h):pass
            def bounds(self):return (0,0,160,100)
            def grab(self,roi):return np.zeros((100,160,3),np.uint8),self.bounds()
            def close(self):pass
        class Gate:
            def __init__(self):self.n=0
            def check(self,image):self.n+=1;return not 3<=self.n<=6
        class Detector:
            def predict(self,image,index,stamp,clock,bounds):return replace(obs(frame=index,t=stamp),finished=clock(),bounds=bounds)
        args=SimpleNamespace(window_handle=1,window_title='',start_delay=0,fps=60,duration=.3,live=False,max_batches=5,idle_timeout=2,scene_timeout=1)
        with tempfile.TemporaryDirectory() as folder:
            rec=SessionRecorder(Path(folder)/'round')
            with patch('modular_agent.computer.windows.WindowsBackend'),patch('modular_agent.realtime.runtime.WindowCapture',Capture),patch('modular_agent.realtime.kitchen_play.BoardRimGate',Gate):
                result=live_round(args,Detector(),rec,Settings(),set())
            rec.close(**result);types=[e['type'] for e in rec.events]
            self.assertIn('scene_paused',types);self.assertIn('scene_resumed',types)
            self.assertEqual(result['reason'],'duration');self.assertGreater(len(rec.rows),6)


class KitchenReplaySelectionTests(unittest.TestCase):
    def test_real_session_wins_over_newer_named_offline_demo(self):
        import os
        spec=importlib.util.spec_from_file_location('replay_selection_test',Path(__file__).resolve().parents[1]/'tools/kitchen_replay.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            for name,mode,t in [('20261023-live','live',10),('zzz-offline','offline',30),('20261023-new-live','live',20)]:
                p=root/name;p.mkdir();(p/'manifest.json').write_text('{}');os.utime(p/'manifest.json',(t,t))
                (p/'summary.json').write_text(json.dumps(dict(mode=mode)));(p/'timestamps.json').write_text('[{"t":0}]');(p/'screen.avi').write_bytes(b'fixture')
            empty=root/'empty';empty.mkdir();(empty/'manifest.json').write_text('{}')
            self.assertEqual(m.latest_session(root),root/'20261023-new-live')


class KitchenTrayPlannerTests(unittest.TestCase):
    def test_existing_pair_needs_one_click_not_three(self):
        image=replace(obs([item(0)]),tray=('chili','chili','','','','',''))
        self.assertEqual(len(plan(image,set(),Settings(),0)),1)
    def test_tray_completion_precedes_order_priority(self):
        image=replace(obs([item(0,'chili')]+[item(i,'milk_blue') for i in range(1,4)]),tray=('chili','chili','','','','',''),targets=('milk_blue',))
        batch=plan(image,set(),Settings(),0)
        self.assertEqual(batch[0].class_id,'chili');self.assertEqual(len(batch),4)
    def test_unknown_occupied_slots_are_not_empty_capacity(self):
        image=replace(obs(),tray=('?','?','?','?','?','',''))
        self.assertFalse(plan(image,set(),Settings(exploratory=False),0))
    def test_early_completion_frees_capacity_for_next_completion(self):
        image=replace(obs([item(0,'chili'),item(1,'milk_blue'),item(2,'milk_blue')]),tray=('chili','chili','milk_blue','other','?','',''))
        self.assertEqual(len(plan(image,set(),Settings(),0)),3)
    def test_three_already_in_tray_waits_for_animation(self):
        image=replace(obs(),tray=('chili','chili','chili','','','',''))
        self.assertFalse(plan(image,set(),Settings(),0))
    def test_detected_orders_prioritize_complete_triples(self):
        image=replace(obs([item(i,'milk_blue',.7) for i in range(3)]+[item(i,'chili') for i in range(3,6)]),targets=('milk_blue',))
        self.assertEqual(plan(image,set(),Settings(),0)[0].class_id,'milk_blue')
    def test_hud_template_identity_is_not_board_yolo_prediction(self):
        from modular_agent.realtime.kitchen_ui import HudReader
        import cv2
        root=Path(__file__).resolve().parents[1];reader=HudReader(root/'data/kitchen/ui-icons')
        for file,expected in [('tray-live-0.png','milk_blue'),('tray-live-1.png','Spider'),('target-live-1.png','fish_fillet_board')]:
            key,score,margin=reader.classify(cv2.imread(str(root/'data/kitchen/ui-icons'/file)))
            self.assertEqual(key,expected);self.assertGreater(score,.99)


class KitchenExplorationTests(unittest.TestCase):
    def test_single_plate_can_be_clicked_with_space(self):
        image=replace(obs([item(0,'rice_plate')]),tray=('','','','','','',''))
        self.assertEqual(len(plan(image,set(),Settings(),0)),1)
    def test_reserve_three_slots_and_count_unknown_as_occupied(self):
        image=replace(obs([item(i,'rice_plate') for i in range(2)]+[item(i,'other'+str(i)) for i in range(2,5)]),tray=('?','?','?','','','',''))
        self.assertEqual(len(plan(image,set(),Settings(),0)),1)
        self.assertFalse(plan(replace(image,tray=('?','?','?','?','','','')),set(),Settings(),0))
        image=replace(image,tray=('?','?','?','?','?','?',''))
        self.assertFalse(plan(image,set(),Settings(),0))
    def test_complete_triple_still_allowed_to_release_nearly_full_tray(self):
        image=replace(obs([item(0)]),tray=('chili','chili','other1','other2','other3','other4',''))
        self.assertEqual(len(plan(image,set(),Settings(),0)),1)
    def test_exploration_never_reuses_planned_instance(self):
        image=replace(obs([item(i,'rice_plate') for i in range(4)]),tray=('','','','','','',''))
        batch=plan(image,set(),Settings(),0)
        self.assertEqual(len(batch),4);self.assertEqual(len({p.instance_id for p in batch}),4)
    def test_exploration_prefers_existing_tray_class(self):
        image=replace(obs([item(0,'rice_plate',.6),item(1,'milk_blue',.99)]),tray=('rice_plate','','','','','',''))
        self.assertEqual(plan(image,set(),Settings(),0)[0].class_id,'rice_plate')
    def test_no_exploration_without_known_hud_or_when_disabled(self):
        self.assertFalse(plan(obs([item(0)]),set(),Settings(),0))
        image=replace(obs([item(0)]),tray=('','','','','','',''))
        self.assertFalse(plan(image,set(),Settings(exploratory=False),0))


class KitchenTrayLedgerTests(unittest.TestCase):
    def test_real_history_prioritizes_pan_and_milk_despite_wrong_hud(self):
        from modular_agent.realtime.kitchen_match import TrayLedger
        root=Path(__file__).resolve().parents[1]
        fixture=json.loads((root/'data/kitchen/regression/tray-ledger-20261023.json').read_text(encoding='utf-8'))
        ledger=TrayLedger(False)
        for cls in fixture['history']:ledger.on_sent(cls)
        self.assertEqual(ledger.items.count('milk_blue'),2);self.assertEqual(ledger.items.count('noodle_pan'),2)
        d=fixture['observation'];d['items']=tuple(Item(**p) for p in d['items']);image=Observation(**d)
        ledger.observe(image.tray)  # wrong HUD must not erase sent history
        batch=plan(replace(image,tray=ledger.slots()),set(),Settings(),image.captured)
        self.assertEqual([p.class_id for p in batch[:2]],fixture['expected_plan'])
        occupancy=list(ledger.items)
        for p in batch:
            occupancy.append(p.class_id)
            if occupancy.count(p.class_id)==3:occupancy=[v for v in occupancy if v!=p.class_id]
            self.assertLessEqual(len(occupancy),6)
    def test_sent_click_updates_ledger_and_three_remove_projected_class(self):
        from modular_agent.realtime.kitchen_match import TrayLedger
        ledger=TrayLedger(False)
        for cls in ['milk_blue','noodle_pan','milk_blue','noodle_pan','milk_blue']:ledger.on_sent(cls)
        self.assertEqual(ledger.items,['noodle_pan','noodle_pan'])
    def test_only_first_ui_seed_is_used_after_clicks_begin(self):
        from modular_agent.realtime.kitchen_match import TrayLedger
        ledger=TrayLedger(True);self.assertFalse(ledger.observe(('?',)*7))
        self.assertTrue(ledger.observe(('milk_blue','','','','','','')))
        ledger.on_sent('milk_blue');ledger.observe(('',)*7)
        self.assertEqual(ledger.items,['milk_blue','milk_blue'])
    def test_failed_delivery_does_not_advance_ledger(self):
        from modular_agent.realtime.kitchen_match import TrayLedger
        ledger=TrayLedger(False);controller=BatchController(ledger=ledger)
        def fail(item):raise RuntimeError('send failed')
        with self.assertRaises(RuntimeError):
            controller.execute(obs(),set(),clock=lambda:0,wait=lambda _:False,stopped=lambda:False,guard=lambda:None,click=fail,latest=lambda:obs(),emit=lambda *a,**k:None)
        self.assertEqual(ledger.sent,0);self.assertFalse(ledger.items)
    def test_disabling_tray_vision_preserves_target_reader(self):
        from modular_agent.realtime.kitchen_ui import HudReader
        reader=HudReader(Path(__file__).resolve().parents[1]/'data/kitchen/ui-icons');reader.use_tray_vision=False
        tray,targets,detail=reader.read(np.zeros((708,1258,3),np.uint8))
        self.assertEqual(tray,());self.assertEqual(len(detail['targets']),3)


class KitchenOneInferencePerRoundTests(unittest.TestCase):
    def test_one_token_until_batch_finishes_and_fresh_frame_after_delay(self):
        from modular_agent.realtime.kitchen_match import RoundVisionGate
        gate=RoundVisionGate();self.assertTrue(gate.claim(0))
        for t in [.01,.1,.5]:self.assertFalse(gate.claim(t))
        gate.schedule(1.5)
        self.assertFalse(gate.claim(1.49));self.assertTrue(gate.claim(1.5));self.assertFalse(gate.claim(1.6))
    def test_priority_pairs_then_remaining_snapshot_can_be_consumed(self):
        image=replace(obs([item(0,'milk_blue'),item(1,'noodle_pan')]+[item(i,'White_Egg') for i in range(2,5)]),tray=('milk_blue','milk_blue','noodle_pan','noodle_pan','Spider','can',''))
        batch=plan(image,set(),Settings(),0)
        self.assertEqual({p.class_id for p in batch[:2]},{'milk_blue','noodle_pan'})
        self.assertEqual([p.class_id for p in batch[2:]],['White_Egg']*3)


class KitchenRecipeResetTests(unittest.TestCase):
    def test_new_recipe_clears_old_capacity_and_allows_non_target_triples(self):
        from modular_agent.realtime.kitchen_match import TrayLedger,RecipeTracker
        ledger=TrayLedger();tracker=RecipeTracker()
        tracker.update(('White_Egg','tuna_can'),('',)*7,ledger)
        for c in ('onion','White_Egg','tuna_can','flour_bag','poteto','poteto'):ledger.on_sent(c)
        tracker.transition()
        self.assertFalse(tracker.update(('gravy_boat','chili'),('',)*7,ledger))
        self.assertTrue(tracker.update(('gravy_boat','chili'),('',)*7,ledger))
        image=replace(obs([item(i,'onion') for i in range(3)]),tray=ledger.slots(),targets=('gravy_boat','chili'))
        self.assertEqual([p.class_id for p in plan(image,set(),Settings(),0)],['onion']*3)
        self.assertEqual(ledger.sent,6)
    def test_empty_or_partial_hud_never_erases_same_recipe_history(self):
        from modular_agent.realtime.kitchen_match import TrayLedger,RecipeTracker
        ledger=TrayLedger();tracker=RecipeTracker()
        tracker.update(('onion','chili','milk_blue'),('',)*7,ledger);ledger.on_sent('onion')
        tracker.transition()
        for targets in [(),('onion','chili'),('onion','chili'),('gravy_boat','Spider'),('onion','chili')]:
            self.assertFalse(tracker.update(targets,('',)*7,ledger))
        self.assertEqual(ledger.items,['onion'])
    def test_without_transition_or_with_occupied_slots_does_not_reset(self):
        from modular_agent.realtime.kitchen_match import TrayLedger,RecipeTracker
        ledger=TrayLedger();tracker=RecipeTracker();tracker.update(('a','b'),('',)*7,ledger)
        ledger.on_sent('a')
        for _ in range(3):self.assertFalse(tracker.update(('c','d'),('',)*7,ledger))
        tracker.transition()
        for _ in range(3):self.assertFalse(tracker.update(('c','d'),('?',)*7,ledger))
        self.assertEqual(ledger.items,['a'])
    def test_no_tray_vision_still_resets_on_stable_recipe_transition(self):
        from modular_agent.realtime.kitchen_match import TrayLedger,RecipeTracker
        ledger=TrayLedger(False);tracker=RecipeTracker();tracker.update(('a','b'),(),ledger)
        ledger.on_sent('a');tracker.transition()
        self.assertFalse(tracker.update(('c','d'),(),ledger))
        self.assertTrue(tracker.update(('c','d'),(),ledger));self.assertEqual(ledger.items,[])
    def test_large_single_precedes_small_target_and_high_confidence(self):
        large=replace(item(0,'Spider',.6),bbox=(0,0,100,100))
        small=item(5,'chili',.99)
        image=replace(obs([small,large]),tray=('',)*7,targets=('chili',))
        self.assertEqual(plan(image,set(),Settings(),0)[0].class_id,'Spider')


class KitchenCachedBatchDurationTests(unittest.TestCase):
    def test_slow_batch_finishes_cached_plan_beyond_initial_freshness_window(self):
        now=[.08];clicks=[];events=[]
        def wait(delay):now[0]+=delay;return False
        controller=BatchController(Settings(click_interval=.1,max_age=.6))
        image=obs([item(i) for i in range(9)])
        controller.execute(image,set(),clock=lambda:now[0],wait=wait,stopped=lambda:False,guard=lambda:None,click=clicks.append,latest=lambda:image,emit=lambda kind,**data:events.append((kind,data)))
        self.assertEqual(len(clicks),9);self.assertGreater(now[0],.6)
        self.assertFalse(events[-1][1]['partial'])
    def test_stale_snapshot_cannot_start_new_cached_batch(self):
        clicks=[]
        BatchController().execute(obs(),set(),clock=lambda:1,wait=lambda _:False,stopped=lambda:False,guard=lambda:None,click=clicks.append,latest=lambda:obs(),emit=lambda *a,**k:None)
        self.assertEqual(clicks,[])


class KitchenOrderPageTests(unittest.TestCase):
    def test_order_title_handles_different_panel_colors(self):
        import cv2
        from modular_agent.realtime.kitchen_vision import OrderTransitionGate
        root=Path(__file__).resolve().parents[1]
        gate=OrderTransitionGate(root/'data/kitchen/order-transition-title.png')
        image=np.zeros((708,1260,3),np.uint8);image[140:567]=[150,100,210]
        title=cv2.imread(str(root/'data/kitchen/order-transition-title.png'))
        image[80:166,450:810]=title
        self.assertTrue(gate.check(image))
        image[80:166,450:810]=0;self.assertFalse(gate.check(image))
        image[:]=0;image[80:166,450:810]=title;self.assertTrue(gate.check(image))


class KitchenBlueOrderRegressionTests(unittest.TestCase):
    def test_real_blue_order_page_detected_and_board_rejected(self):
        import cv2
        from modular_agent.realtime.kitchen_vision import OrderTransitionGate
        root=Path(__file__).resolve().parents[1]
        gate=OrderTransitionGate(root/'data/kitchen/order-transition-title.png')
        image=cv2.imread(str(root/'data/kitchen/regression/order-blue.jpg'))
        self.assertTrue(gate.check(image))
        image[:100]=0;self.assertFalse(gate.check(image))


class KitchenOrderFadeRecoveryTests(unittest.TestCase):
    def test_fade_does_not_become_permanent_board_reference(self):
        from modular_agent.realtime.kitchen_vision import BoardRimGate
        gate=BoardRimGate();gate.begin_recovery()
        for value in range(0,160,10):self.assertFalse(gate.check(np.full((90,160,3),value,np.uint8)))
        root=Path(__file__).resolve().parents[1]
        import cv2
        board=cv2.imread(str(root/'data/kitchen/regression/board-clear.jpg'))
        self.assertTrue(gate.check(board));self.assertTrue(gate.check(board))


class KitchenConservativeExplorationTests(unittest.TestCase):
    def test_empty_tray_explores_only_one_then_waits_for_new_observation(self):
        image=replace(obs([item(i,'class'+str(i)) for i in range(8)]),tray=('',)*7)
        self.assertEqual(len(plan(image,set(),Settings(),0)),1)
    def test_full_triple_cannot_use_reserved_capacity(self):
        image=replace(obs(),tray=('a','b','c','d','','',''))
        self.assertFalse(plan(image,set(),Settings(exploratory=False),0))
    def test_completing_existing_pair_can_release_overfull_legacy_ledger(self):
        image=replace(obs([item(0)]),tray=('chili','chili','a','b','c','d',''))
        self.assertEqual(len(plan(image,set(),Settings(),0)),1)


class KitchenOrderIngredientsAndFastRecoveryTests(unittest.TestCase):
    def test_gray_order_targets_and_clear_basket_recovery(self):
        import cv2
        from modular_agent.realtime.kitchen_ui import HudReader
        from modular_agent.realtime.kitchen_vision import OrderTransitionGate,BoardRimGate
        root=Path(__file__).resolve().parents[1];folder=root/'data/kitchen/regression'
        order=cv2.imread(str(folder/'order-gray.jpg'))
        gate=OrderTransitionGate(root/'data/kitchen/order-transition-title.png')
        self.assertTrue(gate.check(order))
        targets,_=HudReader(root/'data/kitchen/ui-icons').read_order(order)
        self.assertEqual(targets,('noodle_pan','can','seaweed'))
        rim=BoardRimGate();rim.begin_recovery()
        self.assertFalse(rim.check(cv2.imread(str(folder/'board-intro.jpg'))))
        self.assertTrue(rim.check(cv2.imread(str(folder/'board-clear.jpg'))))
        self.assertFalse(gate.check(cv2.imread(str(folder/'board-clear.jpg'))))


class KitchenTargetPriorityScopeTests(unittest.TestCase):
    def test_target_does_not_affect_single_selection_even_when_same_size(self):
        ordinary=item(0,'ordinary',.9);target=item(1,'target',.7)
        image=replace(obs([ordinary,target]),tray=('',)*7,targets=('target',))
        self.assertEqual(plan(image,set(),Settings(),0)[0].class_id,'ordinary')
        self.assertEqual(plan(replace(image,targets=()),{'target'},Settings(),0)[0].class_id,'ordinary')
    def test_large_ordinary_item_precedes_small_target(self):
        large=replace(item(0,'ordinary',.6),bbox=(0,0,100,100))
        image=replace(obs([large,item(5,'target',.99)]),tray=('',)*7,targets=('target',))
        self.assertEqual(plan(image,set(),Settings(),0)[0].class_id,'ordinary')


class KitchenLastClickCooldownTests(unittest.TestCase):
    def test_single_and_long_batch_both_wait_from_last_click(self):
        for last_sent in (1.,5.):
            controller=BatchController(Settings(batch_interval=.5))
            controller.pending=(item(0),);controller.last_sent=last_sent;controller.last_frame=1
            self.assertEqual(controller.reconcile(obs(frame=2,t=last_sent+.49),last_sent+.6),'waiting')
            self.assertEqual(controller.reconcile(obs(frame=3,t=last_sent+.5),last_sent+.5),'batch_interval_elapsed')


class KitchenOrderContinueTests(unittest.TestCase):
    def test_delayed_page_waits_five_seconds_and_exit_cancels_retry(self):
        from modular_agent.realtime.kitchen_match import OrderContinueController
        gate=OrderContinueController()
        self.assertFalse(gate.ready('playing',0,0))
        self.assertFalse(gate.ready('order_transition',1,2))
        self.assertFalse(gate.ready('order_transition',2,6.99))
        self.assertTrue(gate.ready('order_transition',3,7));gate.sent(7)
        self.assertFalse(gate.ready('playing',4,8))
        self.assertFalse(gate.ready('unknown',5,13))
    def test_dropped_input_retry_is_bounded_and_requires_page_still_visible(self):
        from modular_agent.realtime.kitchen_match import OrderContinueController
        gate=OrderContinueController();gate.ready('order_transition',0,0)
        for i,t in enumerate((5,10,15),1):
            self.assertTrue(gate.ready('order_transition',i,t));gate.sent(t)
            self.assertFalse(gate.ready('order_transition',i,t+.1))
        self.assertFalse(gate.ready('order_transition',4,20))
    def test_disabled_control_and_cancellation_cannot_send(self):
        from modular_agent.realtime.kitchen_match import OrderContinueController
        gate=OrderContinueController();gate.ready('order_transition',0,0)
        self.assertFalse(gate.ready('order_transition',1,5,enabled=False))
        self.assertFalse(gate.ready('order_transition',2,6,stopped=True))
        self.assertEqual(gate.budget.attempts,0)


class KitchenResultContinueTests(unittest.TestCase):
    def test_result_page_title_recognized_but_board_is_not_result(self):
        import cv2
        from modular_agent.realtime.kitchen_vision import ResultTransitionGate
        root=Path(__file__).resolve().parents[1]
        gate=ResultTransitionGate(root/'data/kitchen/result-transition-title.png')
        self.assertTrue(gate.check(cv2.imread(str(root/'data/kitchen/regression/result-page.jpg'))))
        self.assertFalse(gate.check(cv2.imread(str(root/'data/kitchen/regression/board-clear.jpg'))))
    def test_result_waits_one_second_then_bounded_retry_stops_on_page_exit(self):
        from modular_agent.realtime.kitchen_match import OrderContinueController
        gate=OrderContinueController('result_transition',delay=1)
        self.assertFalse(gate.ready('unknown',0,0))
        self.assertFalse(gate.ready('result_transition',1,2))
        self.assertFalse(gate.ready('result_transition',2,2.9))
        self.assertFalse(gate.ready('result_transition',3,3,enabled=False))
        self.assertFalse(gate.ready('result_transition',4,3,stopped=True))
        for i,t in enumerate((3,8,13),5):
            self.assertTrue(gate.ready('result_transition',i,t));gate.sent(t)
        self.assertFalse(gate.ready('result_transition',8,18))
        self.assertFalse(gate.ready('order_transition',9,19))


class KitchenMovingIntroRegressionTests(unittest.TestCase):
    def test_moving_cards_pause_then_uncovered_board_resumes(self):
        import cv2
        from modular_agent.realtime.kitchen_vision import intro_cards_visible,BoardRimGate
        root=Path(__file__).resolve().parents[1]/'data/kitchen/regression'
        intro=cv2.imread(str(root/'moving-intro-cards.jpg'));board=cv2.imread(str(root/'board-after-moving-cards.jpg'))
        self.assertTrue(intro_cards_visible(intro));self.assertFalse(intro_cards_visible(board))
        gate=BoardRimGate();gate.begin_recovery();self.assertTrue(gate.check(board))
    def test_result_continue_delay_is_one_and_half_seconds(self):
        from modular_agent.realtime.kitchen_match import OrderContinueController
        gate=OrderContinueController('result_transition',delay=1.5)
        gate.ready('result_transition',0,0)
        self.assertFalse(gate.ready('result_transition',1,1.49))
        self.assertTrue(gate.ready('result_transition',2,1.5))


class KitchenTailCleanupTests(unittest.TestCase):
    def test_two_visible_items_are_taken_once_to_reveal_hidden_item(self):
        image=replace(obs([item(0,'rice_plate'),item(1,'rice_plate')]),tray=('',)*7)
        self.assertEqual(len(plan(image,set(),Settings(),0)),2)
    def test_tail_sweep_strictly_leaves_one_physical_slot_and_counts_unknowns(self):
        image=replace(obs([item(0,'a'),item(1,'b')]),tray=('',)*7,ui_details={'occupied_slots':5})
        self.assertEqual(len(plan(image,set(),Settings(),0)),0)
        image=replace(image,ui_details={'occupied_slots':4})
        self.assertEqual(len(plan(image,set(),Settings(),0)),2)
    def test_executor_accepts_tail_without_reusing_freed_slot_budget(self):
        from modular_agent.realtime.kitchen_match import TrayLedger
        ledger=TrayLedger(False);ledger.items=['w','x','y','z']
        image=replace(obs([item(0,'a'),item(1,'b')]),tray=ledger.slots())
        now=[0.];sent=[]
        def wait(delay):now[0]+=delay;return False
        BatchController(Settings(),ledger).execute(image,set(),clock=lambda:now[0],wait=wait,stopped=lambda:False,guard=lambda:None,click=sent.append,latest=lambda:image,emit=lambda *a,**k:None)
        self.assertEqual(len(sent),2);self.assertEqual(len(ledger.items),6)


class KitchenCategoryQueueTests(unittest.TestCase):
    def test_two_triples_of_same_class_stay_together_without_extra_wait(self):
        items=[item(i,'a',.99 if i<3 else .7) for i in range(6)]+[item(i,'b',.9) for i in range(6,9)]
        batch=plan(obs(items),set(),Settings(),0)
        self.assertEqual([p.class_id for p in batch],['a']*6+['b']*3)


class KitchenOnlyTargetsTests(unittest.TestCase):
    def test_non_target_triples_and_stored_pair_are_filtered(self):
        image=replace(obs([item(0,'other')]+[item(i,'chili') for i in range(1,4)]),tray=('other','other','','','','',''),targets=('chili',))
        batch=plan(image,set(),Settings(only_targets=True),0)
        self.assertTrue(batch);self.assertTrue(all(p.class_id=='chili' for p in batch))
    def test_unknown_targets_never_fall_back_to_all_classes(self):
        trace=[];image=replace(obs(),tray=('',)*7)
        self.assertEqual(plan(image,set(),Settings(only_targets=True),0,trace),())
        self.assertTrue(all('只点击指定' in r['reason'] for r in trace))
    def test_target_single_allowed_but_non_target_tail_sweep_not_allowed(self):
        image=replace(obs([item(0,'chili'),item(1,'other')]),tray=('',)*7)
        self.assertEqual([p.class_id for p in plan(image,{'chili'},Settings(only_targets=True),0)],['chili'])
    def test_disabled_switch_preserves_normal_all_class_triples(self):
        self.assertEqual(len(plan(obs(),set(),Settings(),0)),3)
