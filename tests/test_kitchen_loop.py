import unittest,tempfile,json
from pathlib import Path
import cv2,numpy as np
from modular_agent.realtime.kitchen_loop import LoopPageDetector,LoopMenuController,STAGES
from modular_agent.realtime.kitchen_session import LoopSessionRecorder
ROOT=Path(__file__).resolve().parents[1]
class LoopDetectionTests(unittest.TestCase):
    def setUp(self):self.folder=ROOT/'data/kitchen/loop-ui';self.detector=LoopPageDetector(self.folder)
    def test_four_reviewed_pages_and_small_brightness_change(self):
        for stage in STAGES:
            image=cv2.imread(str(self.folder/(stage+'-source.png')))
            for alpha in [1.,.95]:
                result=self.detector.read(cv2.convertScaleAbs(image,alpha=alpha))
                self.assertEqual(result['stage'],stage);self.assertTrue(result['enabled'])
    def test_disabled_button_is_never_clicked(self):
        image=cv2.imread(str(self.folder/'reward_ok-source.png'))
        image[605:680,930:1200]=cv2.cvtColor(cv2.cvtColor(image[605:680,930:1200],cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
        result=self.detector.read(image);self.assertEqual(result['stage'],'reward_ok');self.assertFalse(result['enabled'])
    def test_missing_or_delayed_button_still_blocks_food_detection(self):
        image=cv2.imread(str(self.folder/'event_next-source.png'));image[605:685,930:1200]=0
        result=self.detector.read(image);self.assertIsNotNone(result);self.assertFalse(result['enabled'])
    def test_board_and_blank_are_not_loop_menus(self):
        image=cv2.imread(str(ROOT/'data/kitchen/regression/breadcrumbs-slots-20261024.png'))
        self.assertIsNone(self.detector.read(image));self.assertIsNone(self.detector.read(np.zeros((708,1260,3),np.uint8)))
class LoopRetryTests(unittest.TestCase):
    def page(self,stage='score_next',enabled=True):return dict(stage=stage,enabled=enabled)
    def test_dropped_click_retries_only_while_source_stays(self):
        c=LoopMenuController();self.assertFalse(c.observe(self.page(),1,0));self.assertTrue(c.observe(self.page(),2,.5));c.sent(.5)
        self.assertFalse(c.observe(self.page(),3,1));self.assertTrue(c.observe(self.page(),4,2.5));c.sent(2.5)
        self.assertTrue(c.observe(self.page(),5,4.5));c.sent(4.5)
        self.assertFalse(c.observe(self.page(),6,8));self.assertTrue(c.exhausted)
    def test_next_page_does_not_repeat_previous_action(self):
        c=LoopMenuController();c.observe(self.page(),1,0);c.observe(self.page(),2,.5);c.sent(.5)
        self.assertFalse(c.observe(self.page('reward_ok'),3,.6));self.assertEqual(c.stage,'reward_ok')
        self.assertTrue(c.observe(self.page('reward_ok'),4,1.2))
    def test_delayed_disabled_control_and_cancel(self):
        c=LoopMenuController();c.observe(self.page(enabled=False),1,0)
        self.assertFalse(c.observe(self.page(enabled=False),2,1))
        self.assertFalse(c.observe(self.page(),3,1.1,stopped=True));self.assertTrue(c.observe(self.page(),4,1.2))
    def test_one_frame_flicker_does_not_reset_retry_budget(self):
        c=LoopMenuController();c.observe(self.page(),1,0);c.observe(self.page(),2,.5);c.sent(.5)
        c.observe(None,3,.6);self.assertFalse(c.observe(self.page(),4,.7));self.assertEqual(c.budget.attempts,1)
    def test_unknown_menu_waits_without_a_blind_click(self):
        c=LoopMenuController();self.assertFalse(c.observe(self.page('waiting'),1,0));self.assertFalse(c.observe(self.page('waiting'),2,2))
class LoopReplayTests(unittest.TestCase):
    def test_rounds_have_separate_readable_replays_and_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'first';r=LoopSessionRecorder(root)
            r.event('session_start',t=0,live=False,settings={});r.frame(np.zeros((80,120,3),np.uint8),0,0)
            r.rotate(5);r.frame(np.zeros((80,120,3),np.uint8),100,5.1);r.close(reason='user_stop',sends_input=False)
            index=json.loads((root/'loop-index.json').read_text());self.assertEqual(index['rounds'],2)
            for folder in index['sessions']:
                p=Path(folder);self.assertTrue((p/'manifest.json').exists());self.assertEqual(len(json.loads((p/'timestamps.json').read_text())),1)
