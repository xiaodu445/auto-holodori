import json
import tempfile
import unittest
from unittest.mock import patch
from modular_agent.agent.launcher import GameLauncher
from modular_agent.agent.general import GeneralAgent
from modular_agent.core import Action, Outcome, SkillResult
from modular_agent.perception.report import ScreenReport, Rect

PROFILE={'domain':'hololive_dreams','aliases':['hololivedreams'],
    'launch_template':'launch_icon','window_title_patterns':['hololive[ _-]*dreams'],
    'minimum_similarity':.9,'timeout_seconds':2,'poll_seconds':1}
GAME={'handle':7,'title':'hololive dreams','foreground':True,'pid':42,'process_name':'game.exe'}
class Computer:
    live=True
    def __init__(self): self.actions=[]; self.releases=0
    def perform(self,action):
        self.actions.append(action)
        return SkillResult(Outcome.SUCCESS,{'action':action.name},'dispatched')
    def release_all(self): self.releases+=1
    def run_actions(self,actions): return [self.perform(a) for a in actions]
class Vision:
    def __init__(self,windows,report): self.sequence=list(windows); self.report=report; self.desktop=self
    def windows(self):
        if len(self.sequence)>1: return self.sequence.pop(0)
        return self.sequence[0]
    def observe(self,**kwargs): return self.report
class Model:
    def __init__(self,decisions): self.decisions=iter(decisions); self.calls=[]
    def complete(self,instructions,payload): self.calls.append(json.loads(payload)); return json.dumps(next(self.decisions))

def screen(matches=None):
    return ScreenReport(frame={},knowledge_matches=matches or [],capabilities={'knowledge':'ok'})
def icon(identifier='i',score=.99):
    return {'id':identifier,'label':'launch_icon','similarity':score,
        'bounds':Rect(-100,50,72,73).to_dict(),'source':'template'}

class ConnectedAgentTests(unittest.TestCase):
    def test_startup_resizes_existing_and_new_window_and_verifies(self):
        config={**PROFILE,'window_size':{'width':1208,'height':724}}
        resized={**GAME,'bounds':Rect(10,20,1208,724).to_dict()}
        for sequence in ([[GAME],[GAME],[GAME],[resized]],[[],[GAME],[GAME],[GAME],[resized]]):
            c=Computer()
            result=GameLauncher(Vision(sequence,screen([icon()])),c,config,clock=lambda:0).run('启动')
            self.assertTrue(result['verified'])
            actions=[a for a in c.actions if a.name=='resize_window']
            self.assertEqual(len(actions),1)
            self.assertEqual(actions[0].arguments,{'handle':7,'width':1208,'height':724})

    def test_resize_dispatch_without_size_feedback_fails(self):
        c=Computer()
        result=GameLauncher(Vision([[GAME]],screen()),c,{**PROFILE,'window_size':{'width':1208,'height':724}}).run('启动')
        self.assertEqual(result['outcome'],'failure')
        self.assertFalse(result['verified'])
        self.assertIn('尺寸未达到',result['message'])

    def test_resize_action_rejects_invalid_dimensions(self):
        from modular_agent.computer.controller import validate
        for width in (True,0,99,10001,1208.5):
            with self.assertRaises(ValueError): validate(Action('resize_window',arguments={'handle':7,'width':width,'height':724}))
        validate(Action('resize_window',arguments={'handle':7,'width':1208,'height':724}))

    def test_launch_matches_clicks_and_verifies_window(self):
        c=Computer(); vision=Vision([[],[GAME],[GAME]],screen([icon()]))
        result=GameLauncher(vision,c,PROFILE,clock=lambda:0).run('启动hololivedreams')
        self.assertTrue(result['verified'])
        click=next(a for a in c.actions if a.name=='click')
        self.assertEqual(click.arguments,{'x':-64,'y':86,'count':2,'interval':.08})
        self.assertEqual([a.name for a in c.actions].count('click'),1)
        self.assertEqual(c.actions[-1].name,'focus')
    def test_existing_game_window_does_not_relaunch(self):
        c=Computer(); vision=Vision([[GAME],[GAME]],screen())
        result=GameLauncher(vision,c,PROFILE).run('启动hololivedreams')
        self.assertTrue(result['verified'])
        self.assertEqual([a.name for a in c.actions],['focus'])
    def test_missing_icon_restores_original_window(self):
        c=Computer(); original={'handle':3,'title':'Terminal','foreground':True}
        result=GameLauncher(Vision([[original]],screen()),c,PROFILE).run('启动hololivedreams')
        self.assertEqual(result['outcome'],'unknown')
        self.assertNotIn('click',[a.name for a in c.actions])
        self.assertEqual(c.actions[-1].arguments,{'handle':3})
    def test_ambiguous_icons_are_not_clicked(self):
        c=Computer()
        result=GameLauncher(Vision([[]],screen([icon(),icon('j',.98)])),c,PROFILE).run('启动hololivedreams')
        self.assertEqual(result['outcome'],'unknown')
        self.assertNotIn('click',[a.name for a in c.actions])
    def test_launch_timeout_never_reports_success_or_repeats(self):
        c=Computer(); times=iter([0,3])
        result=GameLauncher(Vision([[]],screen([icon()])),c,PROFILE,clock=lambda:next(times)).run('启动hololivedreams')
        self.assertFalse(result['verified'])
        self.assertEqual([a.name for a in c.actions].count('click'),1)
    def test_browser_title_is_not_game_evidence(self):
        c=Computer(); launcher=GameLauncher(Vision([[]],screen()),c,PROFILE)
        browser={**GAME,'process_name':'msedge.exe'}
        self.assertIsNone(launcher._window([browser]))
    def test_simulated_launch_does_not_claim_success(self):
        c=Computer(); c.live=False
        result=GameLauncher(Vision([[]],screen()),c,PROFILE).run('启动hololivedreams')
        self.assertFalse(result['verified']); self.assertEqual(c.actions,[])
    def test_model_target_translation_and_reobservation(self):
        with tempfile.TemporaryDirectory() as root:
            c=Computer(); model=Model([{'decision':'observe'},{'decision':'act','actions':[{'name':'click_target','arguments':{'id':'i'}}]}, {'decision':'done','reason':'target reached'}])
            vision=Vision([[]],screen([icon()]))
            result=GeneralAgent(root,c,model,vision=vision).execute('点击图标')
            self.assertEqual(next(a for a in c.actions if a.name=='click').arguments,{'x':-64,'y':86,'count':1})
            self.assertEqual(len(model.calls),3)
            self.assertEqual(result['verification'],'model_assessment')
            self.assertFalse(result['verified'])
            self.assertNotIn('image',model.calls[0])
    def test_entire_model_plan_validated_before_execution(self):
        with tempfile.TemporaryDirectory() as root:
            c=Computer(); model=Model([{'decision':'observe'},{'decision':'act','actions':[{'name':'press','arguments':{'key':'w'}},{'name':'press','arguments':{'key':'not-a-key'}}]}])
            result=GeneralAgent(root,c,model,vision=Vision([[]],screen())).execute('移动')
            self.assertEqual(result['outcome'],'failure'); self.assertFalse([a for a in c.actions if a.name!='wait'])
    def test_launch_goal_does_not_bypass_model(self):
        from pathlib import Path
        with tempfile.TemporaryDirectory() as root:
            path=Path(root)/'domains'/'hololive_dreams'; path.mkdir(parents=True)
            (path/'launch.json').write_text(json.dumps(PROFILE),encoding='utf-8')
            c=Computer(); model=Model([{'decision':'observe'},{'decision':'escalate','reason':'inspect result'}])
            agent=GeneralAgent(root,c,model,vision=Vision([[]],screen()))
            with patch('modular_agent.agent.general.GameLauncher.run') as launch:
                result=agent.execute('启动 hololive dreams')
            launch.assert_not_called()
            self.assertEqual(len(model.calls),2)
            self.assertIsNone(model.calls[0]['screen'])
            self.assertIsNotNone(model.calls[1]['screen'])
            self.assertEqual(result['outcome'],'unknown')

if __name__=='__main__': unittest.main()
