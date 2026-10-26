import unittest,json,cv2
from pathlib import Path
from modular_agent.realtime.kitchen_match import TrayLedger,Item,Observation,Settings,BatchController
from modular_agent.realtime.kitchen_slot_watch import SlotWatcher
ROOT=Path(__file__).resolve().parents[1]

class TrayCorrectionTests(unittest.TestCase):
    def packet(self,prefix,t=2):return dict(prefix=prefix,captured=t)
    def test_prefix_is_idempotent_and_replaces_unknown(self):
        ledger=TrayLedger();ledger.initialized=True;ledger.items=['?']
        self.assertTrue(ledger.confirm_prefix(self.packet(['can']),2.1));self.assertEqual(ledger.items,['can'])
        self.assertFalse(ledger.confirm_prefix(self.packet(['can']),2.1))
    def test_recent_click_does_not_add_extra_delay_after_round_wait(self):
        ledger=TrayLedger();ledger.initialized=True
        for _ in range(3):ledger.on_sent('can',1.7)
        self.assertTrue(ledger.confirm_prefix(self.packet(['can']),2.1));self.assertEqual(ledger.items,['can'])
    def test_stale_and_previous_recipe_reports_cannot_resurrect_objects(self):
        ledger=TrayLedger();ledger.reset(2)
        self.assertFalse(ledger.confirm_prefix(self.packet(['can'],1.9),2.1))
        self.assertFalse(ledger.confirm_prefix(self.packet(['can'],2.1),3))
    def test_unknown_only_consumes_capacity_and_does_not_form_match(self):
        ledger=TrayLedger();ledger.initialized=True
        self.assertTrue(ledger.confirm_prefix(self.packet(['?','?']),2.1));self.assertEqual(ledger.items,['?','?'])
    def test_real_reviewed_can_and_hands_can_be_recognized(self):
        folder=ROOT/'runtime/kitchen/sessions/20261023-214309-bb3f360f'
        if not (folder/'review-issues.json').exists():self.skipTest('local review unavailable')
        issues=json.loads((folder/'review-issues.json').read_text(encoding='utf-8'))
        for index,expected in [(6,'can'),(8,'Hand')]:
            image=cv2.imread(str(folder/issues[index]['screenshot']));watcher=SlotWatcher(ROOT/'data/kitchen/ui-icons')
            packet=watcher.observe(image,0,0,full_slots=True)
            self.assertEqual(packet['slots'][0]['value'],expected)
            self.assertEqual(len(packet['prefix']),max(0,packet['occupied_count']-3))
    def test_new_residual_breaks_cached_batch_before_capacity_overflow(self):
        ledger=TrayLedger();ledger.initialized=True
        items=tuple(Item(str(i),'chili',20+i*30,30,.9,(10+i*30,20,30+i*30,40)) for i in range(3))
        ob=Observation(1,0,0,items,tray=('',)*7);sent=[]
        def guard():ledger.items=['a','b','c','d']
        BatchController(Settings(),ledger).execute(ob,set(),clock=lambda:0,wait=lambda _:False,stopped=lambda:False,guard=guard,click=sent.append,latest=lambda:ob,emit=lambda *a,**k:None)
        self.assertEqual(sent,[])


class CooldownFeedbackTests(unittest.TestCase):
    def test_feedback_only_updates_ledger_outside_active_click_queue(self):
        ledger=TrayLedger();ledger.initialized=True;controller=BatchController(ledger=ledger);controller.last_sent=1.
        packet=dict(prefix=['onion','onion'],captured=2.)
        controller.executing=True
        self.assertFalse(controller.apply_tray_feedback(packet,2.1));self.assertEqual(ledger.items,[])
        controller.executing=False;controller.pending=(Item('x','other',10,10,1,(0,0,20,20)),)
        self.assertTrue(controller.apply_tray_feedback(packet,2.1));self.assertEqual(ledger.items,['onion','onion'])
    def test_pre_last_click_picture_cannot_overwrite_newer_batch(self):
        ledger=TrayLedger();ledger.initialized=True;controller=BatchController(ledger=ledger);controller.last_sent=2.
        self.assertFalse(controller.apply_tray_feedback(dict(prefix=['Hand','Hand'],captured=1.99),2.1))
        self.assertEqual(ledger.items,[])


class OccupiedMinusThreeTests(unittest.TestCase):
    def test_each_occupied_count_uses_first_n_minus_three_without_stability_wait(self):
        import numpy as np
        from unittest.mock import patch
        for count in range(8):
            watcher=SlotWatcher(ROOT/'data/kitchen/ui-icons')
            # Distinct constant slot images with occupancy supplied by the visual descriptor.
            values=iter([np.ones(5) if i<count else None for i in range(7)])
            with patch('modular_agent.realtime.kitchen_slot_watch.descriptor',side_effect=lambda p:next(values)):
                watcher.reader.empties=[];watcher.reader.classify=lambda p:('rice_bowl',.99,.2)
                packet=watcher.observe(np.zeros((708,1258,3),np.uint8),1,0)
            self.assertEqual(packet['occupied_count'],count)
            self.assertEqual(packet['prefix'],['rice_bowl']*max(0,count-3))
    def test_cooldown_is_the_only_time_delay(self):
        ledger=TrayLedger();ledger.initialized=True;controller=BatchController(Settings(batch_interval=.35),ledger);controller.last_sent=1.
        packet=dict(prefix=['rice_bowl','rice_bowl'],captured=1.34)
        self.assertFalse(controller.apply_tray_feedback(packet,1.349))
        self.assertTrue(controller.apply_tray_feedback(packet,1.35))
        self.assertEqual(ledger.items,['rice_bowl','rice_bowl'])
        self.assertFalse(controller.apply_tray_feedback(packet,1.36))


class BeanCanIconRegressionTests(unittest.TestCase):
    def test_user_confirmed_transparent_cans_not_unknown_in_neighboring_frame(self):
        from modular_agent.realtime.kitchen_ui import HudReader,crop_rect,TRAY_RECTS
        reader=HudReader(ROOT/'data/kitchen/ui-icons')
        image=cv2.imread(str(ROOT/'data/kitchen/regression/bean-cans-20261024.png'))
        for rect in TRAY_RECTS[:2]:
            key,score,margin=reader.classify(crop_rect(image,rect))
            self.assertEqual(key,'can');self.assertGreaterEqual(score,.78);self.assertGreaterEqual(margin,.025)


class LowClickRoundRefreshTests(unittest.TestCase):
    def test_two_single_rounds_read_full_slots_not_n_minus_three(self):
        ledger=TrayLedger();ledger.initialized=True;controller=BatchController(ledger=ledger)
        controller.last_sent=1.;controller.recent_batch_counts=[1,1]
        packet=dict(captured=1.6,prefix=[],slots=[dict(value=c) for c in ['rice_bowl','rice_bowl','','','','','']])
        self.assertTrue(controller.apply_tray_feedback(packet,1.61));self.assertEqual(ledger.items,['rice_bowl','rice_bowl'])
    def test_exactly_three_keeps_existing_rule_and_cooldown_blocks_early_read(self):
        ledger=TrayLedger();ledger.initialized=True;controller=BatchController(ledger=ledger);controller.last_sent=1.
        packet=dict(captured=1.1,prefix=[],slots=[dict(value='onion')]*2+[dict(value='')]*5)
        controller.recent_batch_counts=[1,1]
        self.assertFalse(controller.apply_tray_feedback(packet,1.2))
        controller.recent_batch_counts=[1,2];packet['captured']=1.6
        self.assertFalse(controller.apply_tray_feedback(packet,1.61));self.assertEqual(ledger.items,[])
    def test_full_read_can_remove_ghost_and_unknown_still_occupies_slot(self):
        ledger=TrayLedger();ledger.items=['Hand','onion'];ledger.initialized=True
        packet=dict(captured=2.,slots=[dict(value='?')]+[dict(value='')]*6)
        self.assertTrue(ledger.refresh_slots(packet,2.1));self.assertEqual(ledger.items,['?'])


class ZeroClickRoundsTests(unittest.TestCase):
    def test_two_no_plan_rounds_also_trigger_full_refresh(self):
        controller=BatchController();controller.record_round(3);controller.record_round(0)
        self.assertEqual(controller.tray_feedback_mode(),'occupied_minus_three')
        controller.record_round(0);self.assertEqual(controller.tray_feedback_mode(),'full_slots')


class SnapshotReplacementTests(unittest.TestCase):
    def test_empty_prefix_clears_old_projection(self):
        ledger=TrayLedger();ledger.items=['hamburger_patty']
        self.assertTrue(ledger.confirm_prefix(dict(captured=2.,prefix=[]),2.1))
        self.assertEqual(ledger.items,[])
    def test_prefix_replaces_wrong_counts_and_class(self):
        ledger=TrayLedger();ledger.items=['flour_bag']*4
        self.assertTrue(ledger.confirm_prefix(dict(captured=2.,prefix=['meat_pack','?']),2.1))
        self.assertEqual(ledger.items,['meat_pack','?'])
    def test_full_snapshot_replaces_wrong_identity(self):
        ledger=TrayLedger();ledger.items=['flour_bag']*4
        values=['meat_pack','meat_pack','flour_bag','flour_bag','','','']
        self.assertTrue(ledger.refresh_slots(dict(captured=2.,slots=[dict(value=c) for c in values]),2.1))
        self.assertEqual(ledger.items,values[:4])


class ScallionSlotRegressionTests(unittest.TestCase):
    def test_neighbor_frame_recognizes_both_scallions(self):
        image=cv2.imread(str(ROOT/'data/kitchen/regression/scallion-slots-20261024.png'))
        packet=SlotWatcher(ROOT/'data/kitchen/ui-icons').observe(image,2472,0)
        self.assertEqual([r['value'] for r in packet['slots'][:2]],['scallion','scallion'])
        self.assertEqual(packet['slots'][5]['value'],'')


class PrefixOnlyClassificationTests(unittest.TestCase):
    def test_rightmost_three_objects_are_not_classified(self):
        import numpy as np
        from unittest.mock import patch,Mock
        watcher=SlotWatcher(ROOT/'data/kitchen/ui-icons');watcher.reader.empties=[]
        watcher.reader.classify=Mock(return_value=('scallion',.99,.2))
        values=iter([np.ones(5)]*5+[None]*2)
        with patch('modular_agent.realtime.kitchen_slot_watch.descriptor',side_effect=lambda p:next(values)):
            packet=watcher.observe(np.zeros((708,1258,3),np.uint8),1,0)
        self.assertEqual(watcher.reader.classify.call_count,2)
        self.assertEqual(packet['prefix'],['scallion','scallion'])
        self.assertEqual([r['classified'] for r in packet['slots']],[True,True,False,False,False,False,False])
    def test_full_refresh_waits_for_full_classification_packet(self):
        ledger=TrayLedger();ledger.items=['can'];controller=BatchController(ledger=ledger)
        controller.last_sent=1;controller.recent_batch_counts=[0,0]
        packet=dict(captured=2,prefix=[],classification_scope='residual_prefix',slots=[dict(value='?')]*7)
        self.assertFalse(controller.apply_tray_feedback(packet,2.1))
        self.assertEqual(ledger.items,['can'])


class NearFullTrayMatchTests(unittest.TestCase):
    def test_one_free_slot_can_complete_existing_pair(self):
        from modular_agent.realtime.kitchen_match import plan
        item=Item('a','can',10,10,.99,(0,0,20,20))
        tray=('can','can','onion','onion','ham','ham','')
        ob=Observation(1,0,0,(item,),tray=tray,ui_details=dict(occupied_slots=6,tray_capacity_reliable=True))
        self.assertEqual(plan(ob,set(),Settings(reserve_slots=3),0),(item,))
    def test_reliable_three_free_slots_allow_complete_triple(self):
        from modular_agent.realtime.kitchen_match import plan
        items=tuple(Item(str(i),'can',10+30*i,10,.99,(30*i,0,30*i+20,20)) for i in range(3))
        tray=('onion','onion','ham','ham','','','')
        ob=Observation(1,0,0,items,tray=tray,ui_details=dict(occupied_slots=4,tray_capacity_reliable=True))
        self.assertEqual(plan(ob,set(),Settings(reserve_slots=3),0),items)
        ob=Observation(1,0,0,items,tray=tray,ui_details=dict(occupied_slots=5,tray_capacity_reliable=True))
        self.assertEqual(plan(ob,set(),Settings(reserve_slots=3),0),())


class FixedTrayClassRegressionTests(unittest.TestCase):
    def test_confirmed_classes_on_neighbor_frames_not_used_as_templates(self):
        for stamp,expected in [('41.759',['seaweed','seaweed','cereal']),('56.409',['onion','onion','rice_plate']),('72.483',['meat_pack','meat_pack','Source'])]:
            image=cv2.imread(str(ROOT/'data/kitchen/regression'/('tray-classes-'+stamp+'.png')))
            packet=SlotWatcher(ROOT/'data/kitchen/ui-icons').observe(image,0,0,full_slots=True)
            self.assertEqual([r['value'] for r in packet['slots'][:3]],expected)


class WholeTrayBankAuditTests(unittest.TestCase):
    def test_every_catalog_class_has_a_real_tray_template(self):
        bank=ROOT/'data/kitchen/ui-icons'
        meta=json.loads((bank/'index.json').read_text(encoding='utf-8'))
        catalog=json.loads((ROOT/'data/kitchen/manual-classes.json').read_text(encoding='utf-8'))
        keys={row['class_id'] for row in meta['icons'] if row.get('region')=='tray'}
        self.assertEqual({row['id'] for row in catalog['classes']}-keys,set())
        self.assertNotIn('tray-reviewed-49.png',[r['file'] for r in meta['icons']])
        self.assertIn('tray-reviewed-49.png',meta['empty_icons'])
    def test_reviewed_other_frame_icons_meet_acceptance_threshold(self):
        from modular_agent.realtime.kitchen_ui import HudReader
        reader=HudReader(ROOT/'data/kitchen/ui-icons');folder=ROOT/'data/kitchen/regression/tray-bank-20261024'
        for row in json.loads((folder/'index.json').read_text()):
            with self.subTest(class_id=row['class_id']):
                key,score,margin=reader.classify(cv2.imread(str(folder/row['file'])))
                self.assertEqual(key,row['class_id']);self.assertGreaterEqual(score,.78);self.assertGreaterEqual(margin,.025)


class RicePlateBackgroundRegressionTests(unittest.TestCase):
    def test_light_slot_background_keeps_both_rice_plates(self):
        image=cv2.imread(str(ROOT/'data/kitchen/regression/rice-plate-slots-20261024.png'))
        packet=SlotWatcher(ROOT/'data/kitchen/ui-icons').observe(image,0,0,full_slots=True)
        self.assertEqual([r['value'] for r in packet['slots'][:2]],['rice_plate','rice_plate'])


class PaleIngredientOccupancyTests(unittest.TestCase):
    def test_visible_pale_udon_is_never_reported_empty(self):
        image=cv2.imread(str(ROOT/'data/kitchen/regression/pale-udon-slots-20261024.png'))
        packet=SlotWatcher(ROOT/'data/kitchen/ui-icons').observe(image,203,0)
        self.assertTrue(all(row['occupied'] for row in packet['slots'][:2]))
        self.assertTrue(all(row['value']!='' for row in packet['slots'][:2]))


class FixedSlotPatternFallbackTests(unittest.TestCase):
    def test_existing_templates_recognize_clear_breadcrumbs_without_new_references(self):
        image=cv2.imread(str(ROOT/'data/kitchen/regression/breadcrumbs-slots-20261024.png'))
        watcher=SlotWatcher(ROOT/'data/kitchen/ui-icons')
        packet=watcher.observe(image,0,0,full_slots=True)
        self.assertEqual([r['value'] for r in packet['slots'][:5]],['milk_blue','milk_blue','breadcrumbs','breadcrumbs','cereal'])
    def test_flat_patch_does_not_get_forced_to_a_known_class(self):
        import numpy as np
        from modular_agent.realtime.kitchen_ui import HudReader
        reader=HudReader(ROOT/'data/kitchen/ui-icons')
        key,score,margin=reader.classify_tray(np.full((64,64,3),200,np.uint8))
        self.assertFalse(key and score>=.78 and margin>=.025)
