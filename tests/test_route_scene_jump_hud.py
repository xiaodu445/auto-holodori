import unittest
from types import SimpleNamespace
import cv2
import numpy as np
from modular_agent.realtime.patrol import ROOT,DATA
from modular_agent.domains.hololive_dreams.patrol_vision import read_image
from modular_agent.realtime.route_scene import RouteSceneGate,JumpHudGate
from modular_agent.realtime.camera_navigation import RouteFrameGuard


class JumpHudSceneTests(unittest.TestCase):
    def image(self,name='last'):
        return read_image(DATA/f'jump-hud-regression-m019/{name}.png')

    def no_jump(self):
        image=self.image();image[500:655,1015:1185]=(80,100,110)
        return image

    def test_real_press_animation_no_longer_loses_free_scene(self):
        gate=RouteSceneGate(ROOT)
        for name in ('first','last'):
            self.assertTrue(gate.read(self.image(name))[0])
            self.assertTrue(gate.jump_available)
        self.assertEqual(gate.diagnostics['jump_hud_state'],'pressed')

    def test_pressed_template_does_not_include_ground(self):
        gate=JumpHudGate();image=self.image()
        self.assertTrue(gate.read(image)[0])
        image[645:655,1015:1185]=(0,0,0)
        image[500:530,1015:1185]=(30,170,230)
        self.assertTrue(gate.read(image)[0])

    def test_no_jump_button_keeps_world_movement_but_disables_jumping(self):
        gate=RouteSceneGate(ROOT);image=self.no_jump()
        self.assertTrue(gate.read(image)[0]);self.assertFalse(gate.jump_available)
        self.assertTrue(gate.diagnostics['persistent_world'])
        self.assertTrue(gate.movement_hud(image)[0]);self.assertFalse(gate.jump_available)

    def test_no_button_alone_does_not_prove_world(self):
        gate=RouteSceneGate(ROOT);image=self.no_jump()
        image[20:231,:260]=0
        self.assertFalse(gate.read(image)[0])
        self.assertFalse(gate.movement_hud(image)[0])
        self.assertFalse(gate.read(np.full_like(image,150))[0])

    def test_gray_disabled_normal_and_pressed_buttons_still_block(self):
        gate=RouteSceneGate(ROOT)
        for name in ('first','last'):
            image=self.image(name)
            roi=image[500:655,1015:1185]
            image[500:655,1015:1185]=cv2.cvtColor(cv2.cvtColor(roi,cv2.COLOR_BGR2GRAY),cv2.COLOR_GRAY2BGR)
            self.assertFalse(gate.read(image)[0]);self.assertFalse(gate.jump_available)
            self.assertFalse(gate.movement_hud(image)[0])

    def test_popup_vetoes_both_pressed_and_no_jump_world(self):
        gate=RouteSceneGate(ROOT)
        real_extract=gate.extract
        for image in (self.image(),self.no_jump()):
            features=real_extract(image,(0,0),ROOT)
            gate.extract=lambda *args:dict(features,reward=True)
            self.assertFalse(gate.read(image)[0])
            self.assertIn('reward',gate.diagnostics['blockers'])

    def test_short_pulse_guard_uses_same_no_jump_movement_rule_and_cancel(self):
        gate=RouteSceneGate(ROOT);image=self.no_jump();self.assertTrue(gate.read(image)[0])
        bounds=(0,0,1260,709);clock=[.1];cancelled=[False]
        capture=SimpleNamespace(bounds=lambda:bounds,grab=lambda r:(image,bounds))
        guard=RouteFrameGuard(capture,bounds,gate,lambda:cancelled[0],clock=lambda:clock[0]);guard.update(0,True)
        guard();self.assertFalse(gate.jump_available)
        cancelled[0]=True
        with self.assertRaisesRegex(RuntimeError,'cancelled'):guard()

    def test_no_jump_world_requires_independent_hud_support(self):
        gate=RouteSceneGate(ROOT);gate.extract=lambda *args:dict(hud_count=0,world_support=0)
        self.assertFalse(gate.read(self.no_jump())[0])


if __name__=='__main__':unittest.main()
