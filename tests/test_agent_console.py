import os
from pathlib import Path
import subprocess
import sys
import unittest

class AgentConsoleTests(unittest.TestCase):
    def call(self,args,stdin=None):
        root=Path(__file__).resolve().parents[1]
        return subprocess.run([sys.executable,'-m','modular_agent',*args,'--model-profile','mock'],input=stdin,
            capture_output=True,text=True,encoding='utf-8',timeout=10,cwd=root,
            env={**os.environ,'PYTHONPATH':str(root/'src'),'PYTHONIOENCODING':'utf-8'})
    def test_interactive_start_and_local_goal_without_model(self):
        result=self.call(['chat','--domain','hololive_dreams'],'启动hololivedreams\n/quit\n')
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('顶层 Agent 已启动',result.stdout)
        self.assertIn('provider=mock',result.stdout)
        # Immediate /quit may cancel the asynchronous task before mock planning.
        self.assertTrue('[unknown]' in result.stdout or '[failure]' in result.stdout)
        self.assertIn('任务事实记录已保存',result.stdout)
    def test_single_goal_uses_connected_runner(self):
        result=self.call(['run','--goal','启动hololivedreams'])
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('"verified": false',result.stdout)
        self.assertNotIn('"config"',result.stdout)

if __name__=='__main__': unittest.main()
