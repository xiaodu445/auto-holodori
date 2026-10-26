import unittest
from pathlib import Path
from types import SimpleNamespace
import cv2
from modular_agent.realtime.runtime import run_loop
from modular_agent.realtime.fishing_loop import LoopObserver, load_tree

ROOT = Path(__file__).resolve().parents[1]

class WaitingBoundaryTests(unittest.TestCase):
    def test_waiting_probe_yields_and_releases_without_frame_input(self):
        events = []
        capture = SimpleNamespace(close=lambda:events.append('closed'))
        computer = SimpleNamespace(stopped=False, release_all=lambda:events.append('released'))
        program = SimpleNamespace(state='waiting')
        boundary = dict(state='continue', point=(900,550), bounds=(0,0,1000,600))
        result = run_loop(capture, program, computer, dict(timeout=1,fps=60,minimum_hold=0),
                          boundary_probe=lambda:boundary)
        self.assertEqual(result['reason'], 'waiting_boundary_detected')
        self.assertEqual(result['boundary_observation'], boundary)
        self.assertEqual(result['frames'], 0)
        self.assertEqual(events, ['released','closed'])

    def test_waiting_reward_probe_uses_crop_and_desktop_origin_without_ocr(self):
        image = cv2.imread(str(ROOT/'domains/hololive_dreams/data/fishing_samples/reward-continue.png'))
        h,w = image.shape[:2]
        bounds = (500,300,w,h)
        observer = object.__new__(LoopObserver)
        observer.initial_bounds = bounds
        rois = []
        def grab(roi):
            rois.append(roi)
            return image[:,round(.6*w):], bounds
        observer.capture = SimpleNamespace(grab=grab,bounds=lambda:bounds)
        result = observer.probe_waiting()
        self.assertEqual(result['state'], 'continue')
        self.assertEqual(result['bounds'], bounds)
        self.assertGreater(result['point'][0], 500+w*.75)
        self.assertGreater(result['point'][1], 300+h*.8)
        self.assertEqual(rois, [[.6,0,1,1]])

    def test_waiting_boundary_returns_to_continue_handling_without_counting_round(self):
        tree = load_tree(ROOT)(timeout=5)
        button = dict(state='continue', point=(850,550),bounds=(0,0,1000,600))
        computer = SimpleNamespace(stopped=False,release_all=lambda:None)
        result = tree.run(lambda:button,
            lambda phase,remaining:dict(reason='waiting_boundary_detected',boundary_observation=button),
            lambda target:self.fail('dry run must not click'),computer,phase='waiting',live=False)
        self.assertEqual(result['reason'], 'would_click_continue')
        self.assertEqual(result['rounds'], [])

class RewardDismissTests(unittest.TestCase):
    def test_catalog_reward_prompt_yields_without_ocr(self):
        image=cv2.imread(str(ROOT/'domains/hololive_dreams/data/fishing_samples/catalog-reward-overlay.png'))
        h,w=image.shape[:2]; bounds=(501,488,w,h)
        target=LoopObserver.find_dismiss_prompt(image,bounds)
        self.assertIsNotNone(target)
        self.assertEqual(target['state'],'dismiss')
        observer=object.__new__(LoopObserver); observer.initial_bounds=bounds
        def grab(roi):
            l,t,r,b=roi
            return image[round(t*h):round(b*h),round(l*w):round(r*w)],bounds
        observer.capture=SimpleNamespace(grab=grab,bounds=lambda:bounds)
        self.assertEqual(observer.probe_waiting()['state'],'dismiss')
        self.assertEqual(observer.probe_waiting()['bounds'],bounds)

    def test_dismiss_is_clicked_then_continue_is_rechecked(self):
        tree=load_tree(ROOT)(timeout=5,poll_interval=.05)
        bounds=(0,0,1200,700)
        dismiss=dict(state='dismiss',point=(600,620),bounds=bounds)
        button=dict(state='continue',point=(1050,650),bounds=bounds)
        clock=[0.0]; actions=[]
        computer=SimpleNamespace(stopped=False,release_all=lambda:None)
        def reader(): return dismiss if not actions else button
        def click_continue(target):
            actions.append(target['state']); computer.stopped=True
        result=tree.run(lambda:button,
            lambda phase,remaining:dict(reason='waiting_boundary_detected',boundary_observation=dismiss),
            click_continue,computer,phase='waiting',live=True,
            observe_recovery=reader,click_recovery=lambda target:actions.append(target['state']),
            clock=lambda:clock[0],sleep=lambda dt:clock.__setitem__(0,clock[0]+dt))
        self.assertEqual(actions,['dismiss','continue'])
        self.assertEqual(result['reason'],'cancelled')
        self.assertEqual(result['recovery_actions'][0]['action'],'dismiss')

class CloseGlyphTests(unittest.TestCase):
    def test_normal_waiting_back_arrow_is_not_close(self):
        image=cv2.imread(str(ROOT/'domains/hololive_dreams/data/fishing_samples/waiting-back-arrow.png'))
        h,w=image.shape[:2]
        self.assertIsNone(LoopObserver.find_close_icon(image,(0,0,w,h)))
        observer=object.__new__(LoopObserver)
        observer.initial_bounds=(622,585,w,h)
        observer.capture=SimpleNamespace(bounds=lambda:observer.initial_bounds,
            grab=lambda roi:(image[:,round(.6*w):],observer.initial_bounds))
        self.assertIsNone(observer.probe_waiting())

    def test_catalog_x_on_connected_cyan_background(self):
        image=cv2.imread(str(ROOT/'domains/hololive_dreams/data/fishing_samples/catalog-after-reward.png'))
        h,w=image.shape[:2]; bounds=(417,407,w,h)
        target=LoopObserver.find_close_icon(image,bounds)
        self.assertIsNotNone(target)
        self.assertEqual(target['state'],'close')
        self.assertLess(abs(target['point'][0]-1620),8)
        self.assertLess(abs(target['point'][1]-462),8)
        observer=object.__new__(LoopObserver); observer.initial_bounds=bounds
        def grab(roi):
            l,t,r,b=roi
            return image[round(t*h):round(b*h),round(l*w):round(r*w)],bounds
        observer.capture=SimpleNamespace(grab=grab,bounds=lambda:bounds)
        self.assertEqual(observer.probe_waiting()['state'],'close')

    def test_actual_x_is_recognized_at_multiple_scales(self):
        import numpy as np
        template=cv2.imread(str(ROOT/'domains/hololive_dreams/data/fishing_samples/catalog-close.png'))
        for size in (60,80,100):
            with self.subTest(size=size):
                image=np.zeros((700,1200,3),np.uint8)
                image[20:20+size,1100:1100+size]=cv2.resize(template,(size,size))
                target=LoopObserver.find_close_icon(image,(500,300,1200,700))
                self.assertIsNotNone(target)
                self.assertEqual(target['state'],'close')
                self.assertGreater(target['point'][0],1600)

if __name__ == '__main__': unittest.main()
