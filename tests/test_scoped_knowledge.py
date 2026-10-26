import json
import tempfile
import unittest
from pathlib import Path
from modular_agent.memory.agent_knowledge import AgentKnowledge
from modular_agent.agent.general import GeneralAgent
from test_connected_agent import Computer, Model, Vision, screen, PROFILE

class ScopedKnowledgeTests(unittest.TestCase):
    def fixture(self,root):
        root=Path(root)
        files={'knowledge/global/rules.md':'# 通用规则\n启动经验',
            'domains/hololive_dreams/knowledge/minigames/cards.md':'# 强欲之牌\n电玩巨蛋城赌场路线',
            'domains/other_game/knowledge/secret.md':'# 其他游戏\n强欲之牌',
            'runtime/memory/task_sessions/log.md':'# 历史任务\n強欲之牌 强欲之牌 历史坐标',
            'runtime/memory/experience.md':'# 已归档经验\n启动反馈'}
        for name,text in files.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8')
        return AgentKnowledge(root,'hololive_dreams')

    def test_default_index_excludes_other_domains_and_session_logs(self):
        with tempfile.TemporaryDirectory() as root:
            k=self.fixture(root);index=k.index()
            paths=[e['path'] for e in index['entries']]
            self.assertEqual(len(paths),3)
            self.assertFalse(any('other_game' in p or 'task_sessions' in p for p in paths))
            self.assertFalse(any('content' in e for e in index['entries']))
            self.assertEqual(k.index(scope='history')['total_files'],1)

    def test_directory_search_and_chinese_query(self):
        with tempfile.TemporaryDirectory() as root:
            k=self.fixture(root)
            results=k.search('帮我打开强欲之牌',scope='domain',directory='domains/hololive_dreams/knowledge/minigames')
            self.assertEqual(len(results),1)
            self.assertIn('cards.md',results[0]['path'])
            with self.assertRaises(ValueError): k.search('规则',scope='domain',directory='knowledge/global')
            with self.assertRaises(ValueError): k.index(directory='../config')

    def test_bounded_search_and_document_pagination(self):
        with tempfile.TemporaryDirectory() as root:
            k=self.fixture(root)
            path=Path(root)/'knowledge/global/long.md';path.write_text('启动经验'+('文字'*5000),encoding='utf-8')
            results=k.search('启动',max_chars=500,entry_chars=500)
            self.assertLessEqual(sum(len(e['content']) for e in results),500)
            first=k.read_document('knowledge/global/long.md',limit=300)
            second=k.read_document('knowledge/global/long.md',offset=first['next_offset'],limit=300)
            self.assertEqual(first['offset'],0)
            self.assertEqual(second['offset'],300)
            self.assertEqual(first['content']+second['content'],path.read_text(encoding='utf-8')[:600])
            with self.assertRaises(ValueError): k.read_document('runtime/memory/task_sessions/log.md')
            self.assertIn('历史任务',k.read_document('runtime/memory/task_sessions/log.md',scope='history')['content'])
            with self.assertRaises(ValueError): k.read_document('config/model.json')

    def test_agent_can_list_directory_then_read_a_page(self):
        with tempfile.TemporaryDirectory() as root:
            self.fixture(root)
            folder=Path(root)/'domains/hololive_dreams'
            (folder/'launch.json').write_text(json.dumps(PROFILE))
            model=Model([{'decision':'list_knowledge','scope':'domain'},
                {'decision':'read_knowledge','scope':'domain','path':'domains/hololive_dreams/knowledge/minigames/cards.md'},
                {'decision':'list_skills','domain':'hololive_dreams'},{'decision':'escalate'}])
            GeneralAgent(root,Computer(),model,domain='hololive_dreams',vision=Vision([[]],screen())).execute('查询强欲之牌路线')
            self.assertEqual(model.calls[1]['recent_results'][-1]['index']['total_files'],1)
            self.assertIn('赌场',model.calls[2]['recent_results'][-1]['document']['content'])
            self.assertEqual(model.calls[3]['recent_results'][-1]['entries'][0]['skill'],'launch_game')

    def test_old_read_feedback_is_budgeted_without_mutating_trace(self):
        trace=[{'decision':'read_knowledge','entries':[{'content':'a'*6000}]},{'decision':'read_knowledge','document':{'content':'b'*6000}}]
        output=GeneralAgent._knowledge_trace(trace)
        self.assertEqual(len(output[1]['document']['content']),6000)
        self.assertEqual(len(output[0]['entries'][0]['content']),4000)
        self.assertEqual(len(trace[0]['entries'][0]['content']),6000)

    def test_initial_knowledge_payload_has_small_budget(self):
        with tempfile.TemporaryDirectory() as root:
            self.fixture(root)
            folder=Path(root)/'domains/hololive_dreams';(folder/'launch.json').write_text(json.dumps(PROFILE))
            (folder/'knowledge/minigames/cards.md').write_text('强欲之牌\n'+'赌场'*5000,encoding='utf-8')
            model=Model([{'decision':'escalate'}])
            GeneralAgent(root,Computer(),model,domain='hololive_dreams',vision=Vision([[]],screen())).execute('打开强欲之牌')
            self.assertLessEqual(len(model.calls[0]['relevant_knowledge']),2)
            self.assertLessEqual(sum(len(x['content']) for x in model.calls[0]['relevant_knowledge']),3000)
