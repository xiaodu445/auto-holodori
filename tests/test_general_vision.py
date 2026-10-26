import json
import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np
from modular_agent.perception import GeneralVision, LocalOCR, KnowledgeMatcher, TemplateLibrary
from modular_agent.perception.report import Rect

class FixedOCR:
    def recognize(self,image,origin):
        return [{'id':'text:0','text':'PLAY','confidence':.98,
            'bounds':Rect(origin[0]+40,origin[1]+35,50,20).to_dict(),
            'source':'ocr','geometry_kind':'text_polygon','button_ids':[]}]

class FakeDesktop:
    def controls(self,handles):
        return {'buttons':[{'id':'uia:b','label':'PLAY','confidence':1,
            'bounds':Rect(-80,50,120,50).to_dict(),'source':'uia','semantic_confirmed':True,
            'enabled':True,'text_ids':[]}], 'texts':[], 'warnings':[]}

class VisionTests(unittest.TestCase):
    def test_negative_origin_and_button_text_association(self):
        image=np.zeros((150,250,3),np.uint8)
        window={'handle':12,'foreground':True,'minimized':False,'bounds':Rect(-100,30,250,150).to_dict()}
        report=GeneralVision(ocr=FixedOCR(),desktop=FakeDesktop(),enable_cv_buttons=False).analyze(
            image,origin=(-100,30),windows=[window],read_controls=True)
        self.assertEqual(report.texts[0]['bounds']['x'],-60)
        self.assertEqual(report.texts[0]['button_ids'],['uia:b'])
        self.assertEqual(report.buttons[0]['text_ids'],['text:0'])
        self.assertEqual(report.frame['origin'],{'x':-100,'y':30})
        self.assertEqual(report.to_state().ocr_text,['PLAY'])
        json.dumps(report.to_dict())
    def test_ocr_rescale_coordinates(self):
        def engine(image): return ([[[[10,10],[20,10],[20,20],[10,20]],'测试',.9]],None)
        result=LocalOCR(engine=engine,max_side=100).recognize(np.zeros((100,200,3),np.uint8),(-20,50))
        self.assertEqual(result[0]['bounds']['bbox'],[0,70,20,90])
        self.assertEqual(result[0]['text'],'测试')
    def test_ocr_failure_is_reported_without_losing_other_stages(self):
        class Broken:
            def recognize(self,*unused): raise RuntimeError('model unavailable')
        report=GeneralVision(ocr=Broken()).analyze(np.zeros((100,100,3),np.uint8))
        self.assertEqual(report.capabilities['ocr'],'failed')
        self.assertEqual(report.capabilities['knowledge'],'ok')
        self.assertIn('model unavailable',report.warnings[0])
    def test_repeated_templates_and_knowledge_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            patch=np.random.default_rng(7).integers(0,255,(15,25,3),dtype=np.uint8)
            cv2.imwrite(str(root/'button.png'),patch)
            library=TemplateLibrary(root/'library')
            library.add('play',root/'button.png',['game'],.99,role='button',knowledge_file='knowledge/play.md')
            screen=np.zeros((120,200,3),np.uint8)
            screen[20:35,30:55]=patch; screen[70:85,120:145]=patch
            report=GeneralVision(enable_ocr=False,enable_cv_buttons=False,
                knowledge=KnowledgeMatcher([library])).analyze(screen,environment='game',origin=(-10,5))
            self.assertEqual(len(report.knowledge_matches),2)
            self.assertEqual({tuple(m['bounds']['bbox']) for m in report.knowledge_matches},
                {(20,25,45,40),(110,75,135,90)})
            self.assertEqual(len(report.buttons),2)
            self.assertTrue(all(m['similarity']>.99 for m in report.knowledge_matches))
            self.assertEqual(report.knowledge_matches[0]['knowledge_file'],'knowledge/play.md')
            self.assertEqual(KnowledgeMatcher([library]).match(screen,'other'),[])
    def test_multiscale_match(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); patch=np.random.default_rng(3).integers(0,255,(16,20,3),dtype=np.uint8)
            cv2.imwrite(str(root/'icon.png'),patch)
            library=TemplateLibrary(root/'library'); library.add('icon',root/'icon.png',['*'],.99)
            screen=np.zeros((100,150,3),np.uint8)
            screen[30:54,40:70]=cv2.resize(patch,(30,24))
            matches=KnowledgeMatcher([library],scales=(1,1.5)).match(screen)
            self.assertTrue(matches)
            self.assertEqual(matches[0]['bounds']['bbox'],[40,30,70,54])
    def test_constant_template_does_not_match_everywhere(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); cv2.imwrite(str(root/'white.png'),np.full((10,10,3),255,np.uint8))
            library=TemplateLibrary(root/'library'); library.add('white',root/'white.png',['*'],.99)
            self.assertEqual(KnowledgeMatcher([library]).match(np.zeros((80,80,3),np.uint8)),[])
    def test_cv_shapes_are_candidates(self):
        image=np.zeros((200,400,3),np.uint8)
        cv2.rectangle(image,(50,50),(200,100),(255,255,255),2)
        report=GeneralVision(enable_ocr=False).analyze(image)
        self.assertTrue(report.buttons)
        self.assertTrue(all(not b['semantic_confirmed'] for b in report.buttons))
    def test_uia_timeout_is_reported(self):
        class Slow:
            def controls(self,*args): raise TimeoutError('UIA timed out')
        window={'handle':1,'foreground':True,'bounds':Rect(0,0,100,100).to_dict()}
        report=GeneralVision(desktop=Slow(),enable_ocr=False).analyze(np.zeros((100,100,3),np.uint8),windows=[window],read_controls=True)
        self.assertEqual(report.capabilities['uia'],'failed')
        self.assertEqual(report.capabilities['cv_buttons'],'ok')
    def test_project_observe_does_not_create_empty_libraries(self):
        with tempfile.TemporaryDirectory() as temp:
            GeneralVision.for_project(temp,enable_ocr=False).analyze(np.zeros((50,50,3),np.uint8))
            self.assertFalse((Path(temp)/'knowledge').exists())
    def test_uia_and_ocr_labels_merge_with_glyph_bounds(self):
        class Labels(FakeDesktop):
            def controls(self,handles):
                controls=super().controls(handles)
                controls['texts']=[{'id':'uia:b:text','text':'PLAY',
                    'bounds':Rect(-80,50,120,50).to_dict(),'confidence':1,
                    'source':'uia','geometry_kind':'control_bounds','button_ids':['uia:b']}]
                return controls
        window={'handle':12,'foreground':True,'bounds':Rect(-100,30,250,150).to_dict()}
        report=GeneralVision(ocr=FixedOCR(),desktop=Labels(),enable_cv_buttons=False).analyze(
            np.zeros((150,250,3),np.uint8),origin=(-100,30),windows=[window],read_controls=True)
        self.assertEqual(len(report.texts),1)
        self.assertEqual(report.texts[0]['geometry_kind'],'text_polygon')
        self.assertEqual(report.texts[0]['additional_sources'],['uia'])
        self.assertEqual(report.buttons[0]['text_ids'],['text:0'])
    def test_invalid_image(self):
        with self.assertRaises(ValueError): GeneralVision().analyze(np.zeros((0,0,3),np.uint8))

if __name__=='__main__': unittest.main()
