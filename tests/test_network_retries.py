import io
import json
import os
import threading
import time
import unittest
from unittest.mock import patch
from urllib.error import HTTPError, URLError
from modular_agent.model_client import ModelConfig, create_model_client, ModelAPIError
from test_models import Response

class NetworkRetryTests(unittest.TestCase):
    def client(self, **kwargs):
        return create_model_client(ModelConfig(provider='openai_chat',api_key_env='TEST_AGENT_KEY',**kwargs))

    def test_network_and_timeout_retry_then_recover(self):
        client=self.client(); notices=[]; client.on_retry=notices.append
        with patch.dict(os.environ,{'TEST_AGENT_KEY':'test'}), patch('modular_agent.model_client._wait'), patch('modular_agent.model_client.urlopen',side_effect=[URLError('private connection detail'),TimeoutError(),Response({'choices':[{'message':{'content':'{}'}}]})]) as fetch:
            self.assertEqual(client.complete('',''),'{}')
        self.assertEqual(fetch.call_count,3)
        self.assertTrue(any('网络异常' in n for n in notices))
        self.assertTrue(any('超时' in n for n in notices))
        self.assertFalse(any('private' in n for n in notices))

    def test_server_error_retried_auth_error_not_retried(self):
        for status, expected in ((503,2),(401,1)):
            with self.subTest(status=status):
                failure=HTTPError('https://example.invalid',status,'error',{},io.BytesIO(b'{}'))
                with patch.dict(os.environ,{'TEST_AGENT_KEY':'test'}), patch('modular_agent.model_client._wait'), patch('modular_agent.model_client.urlopen',side_effect=[failure,Response({'choices':[{'message':{'content':'{}'}}]})]) as fetch:
                    if status==401:
                        with self.assertRaises(ModelAPIError): self.client().complete('','')
                    else: self.assertEqual(self.client().complete('',''),'{}')
                self.assertEqual(fetch.call_count,expected)

    def test_timeouts_are_bounded(self):
        with patch.dict(os.environ,{'TEST_AGENT_KEY':'test'}), patch('modular_agent.model_client._wait'), patch('modular_agent.model_client.urlopen',side_effect=TimeoutError()) as fetch:
            with self.assertRaisesRegex(RuntimeError,'已尝试 4 次'): self.client().complete('','')
        self.assertEqual(fetch.call_count,4)

    def test_stalled_request_has_total_deadline(self):
        release=threading.Event()
        def stalled(*args,**kwargs):
            release.wait(3)
            return Response({'choices':[{'message':{'content':'late result'}}]})
        try:
            with patch.dict(os.environ,{'TEST_AGENT_KEY':'test'}),patch('modular_agent.model_client.urlopen',side_effect=stalled):
                started=time.monotonic()
                with self.assertRaisesRegex(RuntimeError,'超时'): self.client(timeout_seconds=.1,max_retries=0).complete('','')
                self.assertLess(time.monotonic()-started,1)
        finally: release.set()

    def test_stop_cancels_waiting_request(self):
        entered=threading.Event(); release=threading.Event()
        def stalled(*args,**kwargs):
            entered.set(); release.wait(3)
            return Response({})
        client=self.client(); client.cancelled=entered.is_set
        try:
            with patch.dict(os.environ,{'TEST_AGENT_KEY':'test'}),patch('modular_agent.model_client.urlopen',side_effect=stalled):
                with self.assertRaisesRegex(RuntimeError,'停止'): client.complete('','')
        finally: release.set()
