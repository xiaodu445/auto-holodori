"""B029 stable difficulty-bar confirmation without waiting for top titles."""
from pathlib import Path
import unittest
from unittest.mock import Mock
import cv2
import numpy as np
from modular_agent.domains.hololive_dreams.multi_live_vision import LiveVision
import test_multi_live as fixtures
from test_multi_live import Simulation,frame

ROOT=Path(__file__).resolve().parents[1]


class SettingsBottomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.vision=LiveVision(ROOT);cls.reference=fixtures.ReferenceTests()
    def image(self):return self.reference.image('296118')
    def test_no_top_title_still_recognizes_enabled_decide(self):
        image=self.image();image[:90,500:760]=0
        f=self.vision.detect(image)
        self.assertEqual(f.state,'settings');self.assertEqual(f.evidence,'settings_bottom_controls')
        self.assertIn('decide',f.targets)
    def test_difficulty_values_are_not_state_constants(self):
        image=self.image();image[:90,500:760]=0;image[600:651,700:1000]=0
        self.assertEqual(self.vision.detect(image).state,'settings')
    def test_gray_decide_not_clickable_even_with_bottom_labels(self):
        image=self.image();image[:90,500:760]=0;image[608:674,1050:1220]//=2
        f=self.vision.detect(image)
        self.assertEqual(f.state,'settings');self.assertNotIn('decide',f.targets)
    def test_decide_text_alone_does_not_authorize_settings(self):
        image=self.image();image[:90,500:760]=0;image[646:690,690:1008]=0
        self.assertNotEqual(self.vision.detect(image).state,'settings')
    def test_other_reference_pages_never_settings(self):
        for prefix in ('355deb','55bc73','bb7dc','b9bd9','ae214','ed5df','34d0e','7fb66','2117f','9d0c8','019012','c5635','b8916','81b1a','aadff'):
            with self.subTest(prefix=prefix):
                self.assertNotEqual(self.vision.detect(self.reference.image(prefix)).state,'settings')
    def test_pickup_then_flickering_title_decides_promptly(self):
        game=Simulation();game.index=4;original=game.observe;polls=[0]
        def observe(**kwargs):
            if game.states[game.index]=='settings':
                image=self.image();polls[0]+=1
                if polls[0]%2:image[:90,500:760]=0
                return self.vision.detect(image)
            return original(**kwargs)
        session=game.session();session.observe=observe
        self.assertEqual(session.run()['outcome'],'success')
        pickup=next(t for state,label,t in game.calls if state=='song')
        decide=next(t for state,label,t in game.calls if state=='settings')
        self.assertLessEqual(decide-pickup,.61);self.assertEqual(game.plays,1)
    def test_two_pixel_target_jitter_does_not_restart_stable_count(self):
        game=Simulation();game.index=5;original=game.observe;polls=[0]
        def observe(**kwargs):
            if game.states[game.index]=='settings':
                polls[0]+=1;f=frame('settings');f.targets['decide']['bounds']['x']+=polls[0]%2
                return f
            return original(**kwargs)
        session=game.session();session.observe=observe
        self.assertEqual(session.run()['outcome'],'success')
        self.assertLessEqual(next(t for s,l,t in game.calls if s=='settings'),.21)
    def test_cancel_after_pickup_before_settings_click(self):
        game=Simulation();game.index=4;session=game.session()
        def check():
            if game.index==5:raise RuntimeError('cancelled')
        session.check=check
        self.assertEqual(session.run()['reason'],'cancelled')
        self.assertEqual([(s,l) for s,l,t in game.calls],[('song','pickup')]);self.assertEqual(game.plays,0)


if __name__=='__main__':unittest.main()
