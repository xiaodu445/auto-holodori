import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import cv2
import numpy as np
from modular_agent.perception import GeneralVision, LocalOCR, TemplateLibrary, KnowledgeMatcher
from modular_agent.perception.search import SearchMixin

class QueryTests(unittest.TestCase):
    def vision(self):
        calls=[]
        def engine(image):
            calls.append(image.shape)
            return ([[[[1,1],[4,1],[4,4],[1,4]],'移动',.9]],None)
        return GeneralVision(ocr=LocalOCR(engine=engine),enable_uia=False,enable_cv_buttons=False),calls

    def test_region_preserves_physical_coordinates_and_clips(self):
        vision,calls=self.vision()
        report=vision.analyze(np.zeros((20,40,3),np.uint8),origin=(-50,10),region=[-45,12,10,8],enable_knowledge=False)
        self.assertEqual(calls,[(8,10,3)])
        self.assertEqual(report.texts[0]['bounds']['x'],-44)
        self.assertEqual(report.texts[0]['bounds']['y'],13)
        self.assertEqual(report.frame['bounds']['bbox'],[-45,12,-35,20])
        clipped=vision.analyze(np.zeros((20,40,3),np.uint8),origin=(-50,10),region=[-60,0,20,20],enable_knowledge=False)
        self.assertEqual(clipped.frame['bounds']['bbox'],[-50,10,-40,20])

    def test_module_switches_do_not_call_disabled_backends(self):
        vision,calls=self.vision()
        with patch.object(vision.knowledge,'match',side_effect=AssertionError('must not match')):
            report=vision.analyze(np.zeros((10,10,3),np.uint8),enable_ocr=False,enable_knowledge=False)
        self.assertFalse(calls)
        self.assertEqual(report.capabilities['knowledge'],'disabled')
        self.assertNotIn('knowledge',report.timings_ms)

    def test_invalid_options_fail_before_screen_capture(self):
        vision,_=self.vision()
        bad=[{'enable_ocr':1},{'region':[0,0,0,5]},{'template_names':'map2'},{'template_threshold':float('nan')},{'template_scales':[0]},{'ocr_max_side':True},{'monitor':-1}]
        with patch('modular_agent.perception.general.capture_monitor') as capture:
            for options in bad:
                with self.subTest(options=options),self.assertRaises(ValueError): vision.observe(**options)
        capture.assert_not_called()
        with self.assertRaises(ValueError): vision.analyze(np.zeros((10,10,3),np.uint8),region=[100,100,10,10])

    def test_target_templates_skip_unrequested_work_and_do_not_mutate_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);library=TemplateLibrary(root/'library')
            template=np.random.default_rng(8).integers(0,255,(12,12,3),dtype=np.uint8)
            cv2.imwrite(str(root/'template.png'),template)
            for name in ('map1','map2','smallgame'): library.add(name,root/'template.png',['game'],.95)
            matcher=KnowledgeMatcher([library]);image=np.zeros((50,50,3),np.uint8);image[20:32,20:32]=template
            with patch.object(matcher,'_template',wraps=matcher._template) as decode:
                matches=matcher.match(image,'game',template_names=['map2'],scales=[1],threshold=.8)
            self.assertEqual(decode.call_count,1)
            self.assertEqual({m['label'] for m in matches},{'map2'})
            self.assertEqual(matches[0]['threshold'],.8)
            self.assertEqual(matcher.scales,(1.0,))
            self.assertTrue(all(r.threshold==.95 for r in library.records()))
            self.assertEqual(matcher.match(image,'game',template_names=[]),[])
            self.assertEqual(matcher.match(image,'game',template_names=['missing']),[])

    def test_smallgame_resized_map_matches_configured_scales(self):
        import json
        domain=Path(__file__).resolve().parents[1]/'domains/hololive_dreams'
        image=cv2.imdecode(np.fromfile(str(domain/'data/template_sources/samples/smallgame_map_085.png'),np.uint8),cv2.IMREAD_COLOR)
        config=json.loads((domain/'launch.json').read_text(encoding='utf-8'))
        for scales in (config['template_scales'],config['perception_policy']['game_template_scales']):
            matches=KnowledgeMatcher([TemplateLibrary(domain/'vision_library')],scales=scales).match(image,'hololive_dreams',template_names=['smallgame'],origin=(100,20))
            self.assertTrue(matches)
            self.assertGreater(matches[0]['similarity'],.9)
            self.assertEqual(matches[0]['scale'],.85)
            self.assertEqual(matches[0]['bounds']['x'],959)
            self.assertEqual(matches[0]['bounds']['y'],218)

    def test_find_text_runs_only_required_stage_and_filters(self):
        vision,_=self.vision()
        def observe(**options):
            self.assertFalse(options['enable_knowledge'])
            self.assertFalse(options['enable_uia'])
            return vision.analyze(np.zeros((10,10,3),np.uint8),enable_knowledge=False)
        with patch.object(vision,'observe',side_effect=observe):
            found=vision.find_text('移 动',mode='exact')
            self.assertTrue(found['found'])
            self.assertEqual(found['matches'][0]['queries'],['移 动'])
            self.assertFalse(vision.find_text('错误目标')['found'])

    def test_closed_instances_fail_clearly(self):
        vision,_=self.vision();vision.close();vision.close()
        with self.assertRaisesRegex(RuntimeError,'closed'): vision.analyze(np.zeros((10,10,3),np.uint8))

    def test_wait_requires_stable_matches_and_all_targets(self):
        class Search(SearchMixin):
            def __init__(self): self.count=0
            def find_templates(self,names,**options):
                self.count+=1
                labels=['map2'] if self.count==1 else ['map2','smallgame']
                return {'matches':[{'id':str(self.count)+label,'label':label,'bounds':{'x':10,'y':10,'width':20,'height':20}} for label in labels]}
        now=[0]
        def sleep(seconds): now[0]+=seconds
        result=Search().wait_for('template',['map2','smallgame'],require_all=True,stable_count=2,clock=lambda:now[0],sleep=sleep)
        self.assertEqual(result['status'],'matched')
        self.assertEqual(result['attempts'],3)

    def test_wait_timeout_cancel_and_failure_are_distinct(self):
        class Search(SearchMixin):
            def find_text(self,*args,**options): return {'matches':[],'capabilities':{'ocr':'failed'}}
        now=[0]
        def sleep(seconds): now[0]+=seconds
        result=Search().wait_for('text','移动',timeout=.2,clock=lambda:now[0],sleep=sleep)
        self.assertEqual(result['status'],'timeout')
        self.assertEqual(result['last_result']['capabilities']['ocr'],'failed')
        self.assertEqual(Search().wait_for('text','移动',cancelled=lambda:True)['status'],'cancelled')
