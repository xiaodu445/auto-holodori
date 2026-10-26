import io
import json
import os
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from modular_agent.model_client import ModelConfig,create_model_client,ModelAPIError
from test_models import Response

def error(category,message='',headers=None):
    return HTTPError('https://example.invalid',429,'rate limited',headers or {},
        io.BytesIO(json.dumps({'error':{'type':category,'message':message}}).encode()))

def config(**overrides):
    return ModelConfig(provider='openai_chat',api_key_env='TEST_AGENT_KEY',**overrides)

class RateLimitTests(unittest.TestCase):
    def test_temporary_limit_retries_and_reports_progress(self):
        client=create_model_client(config()); notices=[]; client.on_retry=notices.append
        with patch.dict(os.environ,{'TEST_AGENT_KEY':'test-only-key'}),patch('modular_agent.model_client._wait') as wait,patch('modular_agent.model_client.urlopen',side_effect=[error('rate_limit_reached_error'),Response({'choices':[{'message':{'content':'{}'}}]})]) as fetch:
            self.assertEqual(client.complete('',''),'{}')
        self.assertEqual(fetch.call_count,2); self.assertEqual(wait.call_args.args[0],2)
        self.assertTrue(notices)
    def test_quota_never_retries_or_echoes_message(self):
        with patch.dict(os.environ,{'TEST_AGENT_KEY':'test-only-key'}),patch('modular_agent.model_client._wait') as wait,patch('modular_agent.model_client.urlopen',side_effect=error('exceeded_current_quota_error','account-private-details')) as fetch:
            with self.assertRaises(ModelAPIError) as captured: create_model_client(config()).complete('','')
        self.assertEqual(captured.exception.category,'quota')
        self.assertNotIn('account-private',str(captured.exception)); self.assertEqual(fetch.call_count,1); wait.assert_not_called()
    def test_retry_after_honored(self):
        with patch.dict(os.environ,{'TEST_AGENT_KEY':'test-only-key'}),patch('modular_agent.model_client._wait') as wait,patch('modular_agent.model_client.urlopen',side_effect=[error('rate_limit',headers={'Retry-After':'7'}),Response({'choices':[{'message':{'content':'{}'}}]})]):
            create_model_client(config()).complete('','')
        self.assertEqual(wait.call_args.args[0],7)
    def test_long_retry_after_does_not_retry_too_early(self):
        with patch.dict(os.environ,{'TEST_AGENT_KEY':'test-only-key'}),patch('modular_agent.model_client._wait') as wait,patch('modular_agent.model_client.urlopen',side_effect=error('rate_limit',headers={'Retry-After':'120'})) as fetch:
            with self.assertRaisesRegex(ModelAPIError,'120'): create_model_client(config()).complete('','')
        self.assertEqual(fetch.call_count,1); wait.assert_not_called()
    def test_retries_bounded(self):
        errors=[error('rate_limit') for _ in range(4)]
        with patch.dict(os.environ,{'TEST_AGENT_KEY':'test-only-key'}),patch('modular_agent.model_client._wait') as wait,patch('modular_agent.model_client.urlopen',side_effect=errors) as fetch:
            with self.assertRaises(ModelAPIError): create_model_client(config()).complete('','')
        self.assertEqual(fetch.call_count,4)
        self.assertEqual([call.args[0] for call in wait.call_args_list],[2,4,8])
    def test_stopped_session_sends_no_request(self):
        client=create_model_client(config()); client.cancelled=lambda:True
        with patch.dict(os.environ,{'TEST_AGENT_KEY':'test-only-key'}),patch('modular_agent.model_client.urlopen') as fetch:
            with self.assertRaisesRegex(RuntimeError,'停止'): client.complete('','')
        fetch.assert_not_called()
    def test_daily_limit_not_retried(self):
        with patch.dict(os.environ,{'TEST_AGENT_KEY':'test-only-key'}),patch('modular_agent.model_client.urlopen',side_effect=error('rate_limit_reached_error','request reached TPD rate limit')) as fetch:
            with self.assertRaises(ModelAPIError) as captured: create_model_client(config()).complete('','')
        self.assertEqual(captured.exception.category,'daily_limit'); self.assertEqual(fetch.call_count,1)

if __name__=='__main__': unittest.main()
