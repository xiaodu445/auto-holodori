import tempfile
import unittest
from modular_agent.agent.general import GeneralAgent, compact
from modular_agent.perception.report import ScreenReport
from test_connected_agent import Computer, Model, Vision, screen

class FullObservationContractTests(unittest.TestCase):
    def test_all_screen_texts_and_candidates_are_exported(self):
        report=ScreenReport(frame={},texts=[{'id':str(i),'text':'text'} for i in range(90)],buttons=[{'id':'candidate','source':'cv_shape','semantic_confirmed':False}])
        exported=compact(report)
        self.assertEqual(len(exported['texts']),90)
        self.assertEqual(exported['buttons'],report.buttons)

    def test_current_ocr_text_can_be_clicked_without_fake_button_id(self):
        with tempfile.TemporaryDirectory() as root:
            agent=GeneralAgent(root,Computer(),Model([]),vision=Vision([[]],screen()))
            report=ScreenReport(frame={},texts=[{'id':'ocr:move','source':'ocr','text':'移动','bounds':{'x':100,'y':200,'width':60,'height':30}}])
            action=agent._translate({'name':'click_target','arguments':{'id':'ocr:move'}},report)
            self.assertEqual(action.arguments,{'x':130,'y':215,'count':1})
            with self.assertRaises(ValueError): agent._translate({'name':'click_target','arguments':{'id':'old:move'}},report)

    def test_smallgame_click_requires_current_match_and_geometry(self):
        from modular_agent.core import Action
        with tempfile.TemporaryDirectory() as root:
            computer=Computer()
            agent=GeneralAgent(root,computer,Model([]),vision=Vision([[]],screen()))
            action=Action('click',arguments={'x':1046,'y':789})
            reason='当前已展示多个smallgame，应点击右侧smallgame图标。'
            with self.assertRaisesRegex(ValueError,'没有 smallgame'):
                agent._validate_current_template_target([action],reason,screen())
            report=ScreenReport(frame={},knowledge_matches=[{'label':'smallgame','bounds':{'x':100,'y':100,'width':60,'height':60}}])
            with self.assertRaisesRegex(ValueError,'边界内'):
                agent._validate_current_template_target([action],reason,report)
            agent._validate_current_template_target([Action('click',arguments={'x':130,'y':130})],reason,report)
            agent._validate_current_template_target([action],'本次未匹配到smallgame，点击游玩区域',screen())
            self.assertFalse(computer.actions)

    def test_unconfirmed_shape_uses_unique_current_navigation_text(self):
        with tempfile.TemporaryDirectory() as root:
            agent=GeneralAgent(root,Computer(),Model([]),vision=Vision([[]],screen()))
            report=ScreenReport(frame={},buttons=[{'id':'cv-button:33','source':'cv_shape','semantic_confirmed':False,'text_ids':['ocr:move'],'bounds':{'x':0,'y':0,'width':500,'height':500}}],texts=[{'id':'ocr:move','source':'ocr','text':'移动','button_ids':['cv-button:33'],'bounds':{'x':100,'y':200,'width':60,'height':30}}])
            action=agent._translate({'name':'click_target','arguments':{'id':'cv-button:33'}},report)
            self.assertEqual(action.arguments,{'x':130,'y':215,'count':1})
            report.texts=[]
            with self.assertRaisesRegex(ValueError,'Unconfirmed button shape'):
                agent._translate({'name':'click_target','arguments':{'id':'cv-button:33'}},report)
