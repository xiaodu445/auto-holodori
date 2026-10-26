import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
from modular_agent.perception import GeneralVision
from modular_agent.perception.models import CapturedFrame
from modular_agent.perception.report import Rect
from modular_agent.agent.general import GeneralAgent
from test_connected_agent import Computer, Model, Vision, GAME, PROFILE, screen

class AgentPerceptionTests(unittest.TestCase):
    def test_own_windows_masked_before_ocr_without_erasing_game(self):
        seen=[]
        class OCR:
            def recognize(self,image,origin): seen.append(image.copy()); return []
        game={**GAME,'bounds':Rect(-5,0,65,80).to_dict(),'minimized':False}
        log={'handle':8,'title':'Agent 日志（关闭窗口即可隐藏）','bounds':Rect(70,0,30,80).to_dict()}
        terminal={'handle':9,'title':'start_agent.cmd - 快捷方式','bounds':Rect(40,50,20,20).to_dict()}
        class Desktop:
            def windows(self): return [game,log,terminal]
        vision=GeneralVision(ocr=OCR(),desktop=Desktop(),enable_uia=False,enable_cv_buttons=False)
        with patch('modular_agent.perception.general.capture_monitor',return_value=(np.full((80,100,3),255,np.uint8),CapturedFrame(100,80,0))):
            report=vision.observe()
        self.assertTrue(np.all(seen[0][:,70:]==0))
        self.assertTrue(np.all(seen[0][50:70,40:60]==0))
        self.assertTrue(np.all(seen[0][:40,:60]==255))
        self.assertEqual([w['handle'] for w in report.windows],[7])
        self.assertEqual(report.frame['excluded_agent_windows'],[8,9])

    def test_game_observation_targets_window_and_provides_hint(self):
        class RecordingVision(Vision):
            def observe(self,**kwargs): self.options=kwargs; return self.report
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'domains'/'hololive_dreams';folder.mkdir(parents=True)
            (folder/'launch.json').write_text(json.dumps({**PROFILE,'navigation_hint':'可尝试中央单击一次'}))
            vision=RecordingVision([[GAME]],screen())
            model=Model([{'decision':'observe'},{'decision':'done','reason':'检查完成'}])
            GeneralAgent(root,Computer(),model,domain='hololive_dreams',vision=vision).execute('进入游戏')
            self.assertEqual(vision.options['window_handle'],7)
            self.assertEqual(model.calls[1]['navigation_hint'],'可尝试中央单击一次')
