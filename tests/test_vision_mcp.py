import json
import unittest
from modular_agent.perception.report import ScreenReport, Rect
try:
    from modular_agent.perception.mcp_server import build_server
    MCP_AVAILABLE=True
except ImportError: MCP_AVAILABLE=False

@unittest.skipUnless(MCP_AVAILABLE,'Optional MCP SDK not installed')
class VisionMCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_perception_tool_returns_structure_without_image(self):
        class FakeVision:
            def observe(self,monitor,environment,window_handle):
                self.args=(monitor,environment,window_handle)
                return ScreenReport(frame={'bounds':Rect(0,0,100,100).to_dict()})
        vision=FakeVision(); server=build_server(vision,'game')
        result=await server.call_tool('observe_screen',{'monitor':0,'window_handle':123})
        # SDK may wrap structured output alongside content.
        content=result[0] if isinstance(result,tuple) else result
        self.assertTrue(content)
        self.assertEqual(content[0].type,'text')
        value=json.loads(content[0].text)
        self.assertIn('buttons',value)
        self.assertNotIn('image',value)
        self.assertEqual(vision.args,(0,'game',123))

    async def test_new_tools_and_per_request_options_are_exposed(self):
        class FakeVision:
            def observe(self,monitor,environment,window_handle,**options):
                self.options=options
                return ScreenReport(frame={'bounds':Rect(0,0,100,100).to_dict()})
        vision=FakeVision();server=build_server(vision)
        tools=await server.list_tools()
        self.assertTrue({'observe_screen','find_text','find_templates','wait_for'}<={t.name for t in tools})
        await server.call_tool('observe_screen',{'enable_knowledge':False,'template_names':['map2'],'region':[0,0,50,50]})
        self.assertFalse(vision.options['enable_knowledge'])
        self.assertEqual(vision.options['region'],[0,0,50,50])

    async def test_mcp_wait_cancellation_reaches_local_polling(self):
        import asyncio
        import threading
        import time
        started=threading.Event();finished=threading.Event()
        class FakeVision:
            def wait_for(self,*args,cancelled,**options):
                started.set()
                while not cancelled(): time.sleep(.005)
                finished.set()
                return {'status':'cancelled','found':False}
        server=build_server(FakeVision())
        task=asyncio.create_task(server.call_tool('wait_for',{'kind':'text','query':['移动']}))
        self.assertTrue(await asyncio.to_thread(started.wait,1))
        task.cancel()
        with self.assertRaises(asyncio.CancelledError): await task
        self.assertTrue(await asyncio.to_thread(finished.wait,1))

if __name__=='__main__': unittest.main()
