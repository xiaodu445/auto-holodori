import json
import queue
import tempfile
import threading
import unittest
from test_connected_agent import Computer, Model
from test_model_loop import CountingVision
from modular_agent.agent.general import GeneralAgent


class GuidanceTests(unittest.TestCase):
    def test_guidance_before_request_is_user_context(self):
        with tempfile.TemporaryDirectory() as root:
            messages=[['先检查窗口，不要点击'],[]]
            model=Model([{'decision':'observe'},{'decision':'done','reason':'窗口检查完成'}])
            agent=GeneralAgent(root,Computer(),model,vision=CountingVision())
            result=agent.execute('打开游戏',guidance=lambda:messages.pop(0) if messages else [])
            self.assertEqual(result['outcome'],'success')
            self.assertEqual(model.calls[0]['human_guidance'][0]['text'],'先检查窗口，不要点击')
            self.assertEqual(model.calls[1]['human_guidance'][0]['sequence'],1)

    def test_guidance_during_model_call_discards_stale_click(self):
        entered=threading.Event(); resume=threading.Event(); pending=queue.Queue()
        class BlockingModel(Model):
            def complete(self,system,prompt):
                if len(self.calls)==1:
                    entered.set()
                    if not resume.wait(3): raise RuntimeError('test timeout')
                return super().complete(system,prompt)
        def drain():
            items=[]
            while True:
                try: items.append(pending.get_nowait())
                except queue.Empty: return items
        with tempfile.TemporaryDirectory() as root:
            computer=Computer()
            model=BlockingModel([{'decision':'observe'},
                {'decision':'act','actions':[{'name':'click_target','arguments':{'id':'i'}}]},
                {'decision':'observe'},{'decision':'done','reason':'按新指示完成检查'}])
            agent=GeneralAgent(root,computer,model,vision=CountingVision())
            results=[]
            worker=threading.Thread(target=lambda:results.append(agent.execute('启动游戏',guidance=drain)))
            worker.start()
            try:
                self.assertTrue(entered.wait(3))
                pending.put('不要点击，只检查窗口')
            finally:
                resume.set()
                worker.join(3)
            self.assertFalse(worker.is_alive())
            self.assertEqual(results[0]['outcome'],'success')
            self.assertFalse(any(a.name=='click' for a in computer.actions))
            self.assertIsNone(model.calls[2]['screen'])
            self.assertEqual(model.calls[2]['human_guidance'][-1]['text'],'不要点击，只检查窗口')
