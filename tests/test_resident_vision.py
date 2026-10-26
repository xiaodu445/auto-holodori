import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import cv2
import numpy as np
from modular_agent.perception import GeneralVision, KnowledgeMatcher, TemplateLibrary
from modular_agent.perception.uia_process import UIAProcess
from modular_agent.agent.general import GeneralAgent
from test_connected_agent import Computer, Model, Vision, GAME, PROFILE, screen

class ResidentVisionTests(unittest.TestCase):
    def test_uia_requests_share_process_and_timeout_restarts(self):
        real_popen=subprocess.Popen
        script='import sys,json,time\ncount=0\nfor line in sys.stdin:\n r=json.loads(line);count+=1\n if r["handles"]==[999]: time.sleep(3)\n print(json.dumps({"buttons":[],"texts":[],"warnings":[],"count":count}),flush=True)'
        def spawn(*args,**kwargs): return real_popen([sys.executable,'-u','-c',script],**kwargs)
        worker=UIAProcess()
        try:
            with patch('modular_agent.perception.uia_process.subprocess.Popen',side_effect=spawn) as starts:
                self.assertEqual(worker.request([1])['count'],1)
                self.assertEqual(worker.request([2])['count'],2)
                self.assertEqual(starts.call_count,1)
                with self.assertRaises(TimeoutError): worker.request([999],timeout=.1)
                self.assertEqual(worker.request([3])['count'],1)
                self.assertEqual(starts.call_count,2)
        finally: worker.close()
        self.assertIsNone(worker.process)

    def test_templates_decoded_once_and_new_registry_detected(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            image=np.random.default_rng(1).integers(0,255,(12,12,3),dtype=np.uint8)
            (root/'template.png').write_bytes(cv2.imencode('.png',image)[1].tobytes())
            library=TemplateLibrary(root/'library');library.add('play',root/'template.png',['game'],.99)
            matcher=KnowledgeMatcher([library],scales=(1,1.5))
            real_decode=cv2.imdecode
            with patch('modular_agent.perception.knowledge.cv2.imdecode',wraps=real_decode) as decode:
                matcher.match(image,'game');matcher.match(image,'game')
                self.assertEqual(decode.call_count,1)
                library.add('another',root/'template.png',['game'],.99)
                matches=matcher.match(image,'game')
                self.assertEqual({m['label'] for m in matches},{'play','another'})

    def test_fast_ocr_restores_desktop_coordinates(self):
        from modular_agent.perception import LocalOCR
        sizes=[]
        def engine(image):
            sizes.append(image.shape)
            return ([[[[10,10],[20,10],[20,20],[10,20]],'测试',.9]],None)
        ocr=LocalOCR(engine=engine)
        report=GeneralVision(ocr=ocr,enable_uia=False,enable_cv_buttons=False).analyze(np.zeros((200,400,3),np.uint8),origin=(100,200),ocr_max_side=100)
        self.assertEqual(sizes[0][:2],(50,100))
        self.assertEqual(report.texts[0]['bounds']['bbox'],[140,240,180,280])

    def test_icons_mode_never_calls_ocr_or_uia(self):
        class Broken:
            def recognize(self,*args,**kwargs): raise AssertionError('OCR called')
            def controls(self,*args,**kwargs): raise AssertionError('UIA called')
        report=GeneralVision(ocr=Broken(),desktop=Broken()).analyze(np.zeros((100,100,3),np.uint8),read_controls=True,enable_ocr=False,enable_uia=False,enable_cv_buttons=False)
        self.assertEqual(report.capabilities['ocr'],'disabled')
        self.assertEqual(report.capabilities['uia'],'disabled')
        self.assertEqual(report.capabilities['cv_buttons'],'disabled')

    def test_model_can_request_full_game_observation(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'domains'/'hololive_dreams';folder.mkdir(parents=True)
            (folder/'launch.json').write_text(json.dumps(PROFILE))
            class Recorder(Vision):
                def __init__(self): super().__init__([[GAME]],screen());self.options=[]
                def observe(self,**kwargs): self.options.append(kwargs);return self.report
            vision=Recorder();model=Model([{'decision':'observe'},{'decision':'observe','detail':'full'},{'decision':'done','reason':'看清文字'}])
            with GeneralAgent(root,Computer(),model,domain='hololive_dreams',vision=vision) as agent: agent.execute('检查游戏')
            self.assertNotIn('enable_uia',vision.options[0])
            self.assertNotIn('ocr_max_side',vision.options[0])
            self.assertNotIn('enable_uia',vision.options[1])

class OCRCacheAndTemplatePriorityTests(unittest.TestCase):
    def test_identical_frame_ocr_cache_is_not_mutated_by_report_association(self):
        from modular_agent.perception import LocalOCR
        calls=[]
        def engine(image):
            calls.append(1)
            return ([[[[1,1],[10,1],[10,10],[1,10]],'PLAY',.9]],None)
        ocr=LocalOCR(engine=engine)
        image=np.zeros((100,100,3),np.uint8)
        first=ocr.recognize(image,(20,30))
        first[0]['button_ids'].append('mutated')
        second=ocr.recognize(image,(20,30))
        self.assertEqual(len(calls),1)
        self.assertEqual(second[0]['button_ids'],[])
        ocr.recognize(image,(21,30))
        self.assertEqual(len(calls),2)
        image[0,0]=255
        ocr.recognize(image,(21,30))
        self.assertEqual(len(calls),3)

    def test_template_priority_skips_ocr_only_on_match_and_full_keeps_it(self):
        from modular_agent.perception.report import Rect
        calls=[]
        class OCR:
            def recognize(self,*args,**kwargs): calls.append(1); return []
        class Knowledge:
            matches=[]
            def match(self,*args): return self.matches
        knowledge=Knowledge()
        vision=GeneralVision(ocr=OCR(),knowledge=knowledge,enable_uia=False,enable_cv_buttons=False)
        image=np.zeros((100,100,3),np.uint8)
        vision.analyze(image,prefer_templates=True)
        self.assertEqual(len(calls),1)
        knowledge.matches=[{'id':'p','label':'play','role':'icon','bounds':Rect(10,10,20,20).to_dict()}]
        report=vision.analyze(image,prefer_templates=True)
        self.assertEqual(len(calls),1)
        self.assertEqual(report.capabilities['ocr'],'skipped_template_match')
        vision.analyze(image,prefer_templates=False)
        self.assertEqual(len(calls),2)
        vision.analyze(image,prefer_templates=True,template_priority_exclude=('play',))
        self.assertEqual(len(calls),3)
