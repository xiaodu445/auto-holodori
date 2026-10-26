import json
import os
from pathlib import Path
import sys
import unittest
try:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    MCP_AVAILABLE=True
except ImportError:
    MCP_AVAILABLE=False

@unittest.skipUnless(MCP_AVAILABLE,'Install the optional MCP dependency')
class MCPTests(unittest.IsolatedAsyncioTestCase):
    async def test_stdio_handshake_and_simulated_action(self):
        root=Path(__file__).resolve().parents[1]
        params=StdioServerParameters(command=sys.executable,
            args=['-m','modular_agent.computer.mcp_server','--audit',str(root/'runtime/mcp-test-actions.jsonl')],
            env={**os.environ,'PYTHONPATH':str(root/'src')})
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as session:
                await session.initialize()
                tools=await session.list_tools()
                self.assertEqual({t.name for t in tools.tools},{'execute_action','execute_batch','list_windows','emergency_stop'})
                resources=await session.list_resources()
                self.assertIn('computer://actions',{str(r.uri) for r in resources.resources})
                result=await session.call_tool('execute_action',{'name':'hold','arguments':{'keys':['w'],'duration':1,'dx':20,'dy':0}})
                self.assertFalse(result.isError)
                content=json.loads(result.content[0].text)
                self.assertEqual(content['outcome'],'success')
                self.assertTrue(content['data']['dry_run'])
                result=await session.call_tool('execute_action',{'name':'press','arguments':{'key':'unsupported'}})
                self.assertEqual(json.loads(result.content[0].text)['outcome'],'failure')
                result=await session.call_tool('execute_batch',{'actions':[{'name':'press','arguments':{'key':'w'}}]})
                self.assertFalse(result.isError)
                await session.call_tool('emergency_stop')
                result=await session.call_tool('execute_action',{'name':'press','arguments':{'key':'w'}})
                self.assertEqual(json.loads(result.content[0].text)['outcome'],'failure')

if __name__ == '__main__': unittest.main()
