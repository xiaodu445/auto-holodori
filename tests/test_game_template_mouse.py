import json
from pathlib import Path
import tempfile
import unittest
import cv2
import numpy as np
from modular_agent.computer import ActionComputer
from modular_agent.core import Action, Outcome
from modular_agent.agent.general import GeneralAgent
from modular_agent.perception.template_import import import_game_templates
from modular_agent.perception.template_library import TemplateLibrary
from modular_agent.perception.report import Rect
from test_computer import FakeBackend
from test_connected_agent import Computer, Model, Vision, GAME, PROFILE, screen

class GameTemplateMouseTests(unittest.TestCase):
    def test_alt_is_pressed_before_position_and_released_after_click(self):
        backend=FakeBackend()
        with ActionComputer(live=True,backend=backend) as computer:
            result=computer.perform(Action('click',arguments={'x':50,'y':60,'modifiers':['alt']}))
            self.assertEqual(result.outcome,Outcome.SUCCESS)
            self.assertFalse(computer.keys)
        self.assertLess(backend.events.index(('key','alt',True)),backend.events.index(('position',50,60)))
        self.assertGreater(backend.events.index(('key','alt',False)),backend.events.index(('button','left',False)))

    def test_mouse_failure_releases_alt(self):
        class Broken(FakeBackend):
            def move_to(self,x,y): raise OSError('mouse failure')
        backend=Broken()
        with ActionComputer(live=True,backend=backend) as computer:
            result=computer.perform(Action('click',arguments={'x':50,'y':60,'modifiers':['alt']}))
            self.assertEqual(result.outcome,Outcome.FAILURE)
            self.assertFalse(computer.keys)
        self.assertIn(('key','alt',False),backend.events)

    def test_existing_alt_hold_not_released_by_single_mouse_action(self):
        backend=FakeBackend()
        with ActionComputer(live=True,backend=backend) as computer:
            computer.perform(Action('key_down',arguments={'key':'alt'}))
            computer.perform(Action('move_to',arguments={'x':50,'y':60,'modifiers':['alt']}))
            self.assertIn('alt',computer.keys)
        self.assertEqual(backend.events.count(('key','alt',True)),1)
        self.assertEqual(backend.events.count(('key','alt',False)),1)

    def test_game_policy_does_not_modify_desktop_or_camera_motion(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'domains'/'hololive_dreams';folder.mkdir(parents=True)
            profile={**PROFILE,'interaction_policy':{'mouse_modifiers':['alt']}}
            (folder/'launch.json').write_text(json.dumps(profile))
            agent=GeneralAgent(root,Computer(),Model([]),domain='hololive_dreams',vision=Vision([[]],screen()))
            report=screen();report.windows=[{**GAME,'bounds':Rect(0,0,800,600).to_dict()}]
            actions=[Action('click',arguments={'x':50,'y':50}),Action('click',arguments={'x':900,'y':50}),Action('move_relative',arguments={'dx':10,'dy':0})]
            prepared=agent._apply_mouse_policy(actions,report,'hololive_dreams')
            self.assertEqual(prepared[0].arguments['modifiers'],['alt'])
            self.assertNotIn('modifiers',prepared[1].arguments)
            self.assertNotIn('modifiers',prepared[2].arguments)
            report.windows[0]['foreground']=False
            self.assertNotIn('modifiers',agent._apply_mouse_policy(actions,report,'hololive_dreams')[0].arguments)
            focused=agent._apply_mouse_policy([Action('focus',arguments={'handle':7}),actions[0]],report,'hololive_dreams')
            self.assertEqual(focused[1].arguments['modifiers'],['alt'])

    def test_import_crop_notes_and_deduplicate(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'domains'/'hololive_dreams'/'data'/'template_sources'/'in_game'/'buttons'
            folder.mkdir(parents=True)
            image=np.random.default_rng(2).integers(0,255,(16,20,3),dtype=np.uint8)
            (folder/'quest_button.png').write_bytes(cv2.imencode('.png',image)[1].tobytes())
            (folder/'quest_button.json').write_text(json.dumps({'notes':'任务入口，点击后应出现任务面板'},ensure_ascii=False),encoding='utf-8')
            (folder/'quest_button.md').write_text('只在主界面点击。',encoding='utf-8')
            first=import_game_templates(Path(root),'hololive_dreams')
            self.assertEqual(first['imported'],['quest_button'])
            library=TemplateLibrary(Path(root)/'domains'/'hololive_dreams'/'vision_library')
            self.assertEqual(library.records()[0].role,'button')
            self.assertIn('任务入口',library.records()[0].notes)
            self.assertEqual(import_game_templates(Path(root),'hololive_dreams')['skipped'],['quest_button'])
            self.assertEqual(len(library.records()),1)
            (folder/'quest_button.md').write_text('先检查焦点。',encoding='utf-8')
            self.assertEqual(import_game_templates(Path(root),'hololive_dreams')['updated'],['quest_button'])
            document=Path(root)/library.records()[0].knowledge_file
            self.assertIn('先检查焦点',document.read_text(encoding='utf-8'))

    def test_unicode_source_and_invalid_template_do_not_break_batch(self):
        with tempfile.TemporaryDirectory() as root:
            folder=Path(root)/'domains'/'hololive_dreams'/'data'/'template_sources'/'in_game'/'icons'
            folder.mkdir(parents=True)
            image=np.random.default_rng(4).integers(0,255,(20,20,3),dtype=np.uint8)
            (folder/'任务.png').write_bytes(cv2.imencode('.png',image)[1].tobytes())
            (folder/'任务.json').write_text('{"name":"quest_icon"}',encoding='utf-8')
            (folder/'bad.png').write_text('not an image')
            result=import_game_templates(Path(root),'hololive_dreams')
            self.assertEqual(result['imported'],['quest_icon'])
            self.assertEqual(len(result['errors']),1)
