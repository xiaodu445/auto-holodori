import unittest
from unittest.mock import patch
from types import SimpleNamespace
from datetime import datetime, UTC
import numpy as np
from modular_agent.perception.general import GeneralVision
from modular_agent.perception.report import Rect, ScreenReport

class WindowMaskOrderTests(unittest.TestCase):
    def test_only_console_above_game_masks_pixels(self):
        for order,expected in ((1,200),(-1,0)):
            with self.subTest(order=order):
                bounds=Rect(0,0,20,20).to_dict()
                game={'handle':1,'bounds':bounds,'minimized':False,'foreground':True,'z_order':0}
                console={'handle':2,'title':'start_agent.cmd','bounds':bounds,'minimized':False,'foreground':False,'z_order':order}
                vision=GeneralVision(desktop=SimpleNamespace(windows=lambda:[game,console]))
                frame=SimpleNamespace(left=0,top=0,width=20,height=20,captured_at=datetime.now(UTC))
                seen=[]
                def analyze(image,**kwargs):
                    seen.append(int(image[10,10,0]));return ScreenReport(frame={})
                with patch('modular_agent.perception.general.capture_monitor',return_value=(np.full((20,20,3),200,dtype=np.uint8),frame)),patch.object(vision,'analyze',side_effect=analyze):
                    vision.observe(window_handle=1)
                self.assertEqual(seen,[expected])
