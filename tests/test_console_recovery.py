import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from modular_agent.agent.console import _run_console
from modular_agent.model_client import ModelConfig, create_model_client

class ConsoleRecoveryTests(unittest.TestCase):
    def test_failed_task_returns_idle_and_accepts_another_goal(self):
        ready=threading.Event(); output=[]
        class Log:
            path='test.log'
            def emit(self,message='',**kwargs):
                output.append(str(message))
                if message=='任务已结束，可以输入新任务。': ready.set()
        index=0
        def user_input(prompt):
            nonlocal index
            index+=1
            if index==1: return '第一个任务'
            if index in (2,4):
                if not ready.wait(3): raise RuntimeError('任务没有释放')
                ready.clear()
                return '/status'
            if index==3: return '第二个任务'
            return '/quit'
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder); config=ModelConfig()
            args=SimpleNamespace(live=False,domain=None,max_steps=2,command='chat',log_window=False)
            failure={'outcome':'failure','verified':False,'message':'模拟网络失败'}
            with patch('builtins.input',side_effect=user_input),patch('modular_agent.agent.console.GeneralAgent.execute',return_value=failure) as execute:
                _run_console(args,root,config,create_model_client(config),Log())
            self.assertEqual([c.args[0] for c in execute.call_args_list],['第一个任务','第二个任务'])
            self.assertEqual(output.count('空闲，可以输入新任务。'),2)
            self.assertEqual(output.count('Agent > '),0)  # Input editor owns the prompt.
            self.assertTrue((root/'runtime'/'last-agent-result.json').exists())
