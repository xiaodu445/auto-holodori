import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from modular_agent.model_client import ModelConfig,create_model_client
from modular_agent.model_profiles import ModelProfiles
from modular_agent.credentials import protect,read_key

class Response:
    def __init__(self,body): self.body=body
    def __enter__(self): return self
    def __exit__(self,*unused): pass
    def read(self): return json.dumps(self.body).encode()

class ModelClientTests(unittest.TestCase):
    def test_chat_request_parameters_and_json_content(self):
        config=ModelConfig(provider='openai_chat',model='kimi-k2.6',base_url='https://api.moonshot.cn/v1',
            api_key_env='TEST_AGENT_KEY',thinking='disabled',json_mode=True)
        with patch.dict(os.environ,{'TEST_AGENT_KEY':'test-only-key'}):
            with patch('modular_agent.model_client.urlopen',return_value=Response({'choices':[{'message':{'content':'{"decision":"observe"}'},'finish_reason':'stop'}]})) as fetch:
                result=create_model_client(config).complete('JSON','goal')
        self.assertEqual(json.loads(result)['decision'],'observe')
        request=fetch.call_args[0][0]
        self.assertEqual(request.full_url,'https://api.moonshot.cn/v1/chat/completions')
        payload=json.loads(request.data)
        self.assertEqual(payload['thinking'],{'type':'disabled'})
        self.assertNotIn('temperature',payload)
        self.assertEqual(payload['response_format'],{'type':'json_object'})
    def test_json_fence_unwrapped(self):
        with patch('modular_agent.model_client._request',return_value={'choices':[{'message':{'content':'```json\n{"decision":"observe"}\n```'}}]}):
            self.assertEqual(json.loads(create_model_client(ModelConfig(provider='openai_chat')).complete('',''))['decision'],'observe')
    def test_truncated_response_rejected(self):
        with patch('modular_agent.model_client._request',return_value={'choices':[{'message':{'content':'{'},'finish_reason':'length'}]}):
            with self.assertRaisesRegex(RuntimeError,'truncated'): create_model_client(ModelConfig(provider='openai_chat')).complete('','')
    def test_http_error_does_not_echo_credentials(self):
        error=HTTPError('https://example.invalid',401,'Unauthorized',{},io.BytesIO(b'fake-secret-in-response'))
        with patch.dict(os.environ,{'TEST_AGENT_KEY':'test-only-key'}),patch('modular_agent.model_client.urlopen',side_effect=error):
            try: create_model_client(ModelConfig(provider='openai_chat',api_key_env='TEST_AGENT_KEY')).complete('','')
            except RuntimeError as actual:
                self.assertIn('401',str(actual)); self.assertNotIn('fake-secret',str(actual)); self.assertNotIn('test-only-key',str(actual))
            else: self.fail('Expected error')
    def test_profile_selection_persists_without_key(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'config').mkdir()
            (root/'config'/'models.json').write_text(json.dumps({'profiles':{'mock':{'provider':'mock'},'kimi':{'provider':'openai_chat','model':'kimi-k2.6','api_key_file':'../runtime/secrets/moonshot.dpapi'}}}),encoding='utf-8')
            profiles=ModelProfiles(root)
            config=profiles.select('kimi')
            persisted=ModelConfig.from_json(root/'config'/'model.json')
            self.assertEqual(persisted.model,'kimi-k2.6')
            self.assertEqual(persisted.api_key_file,config.api_key_file)
            profiles.select('mock')
            self.assertEqual(ModelConfig.from_json(root/'config'/'model.json').provider,'mock')
    def test_invalid_profile_does_not_change_selection(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); profiles=ModelProfiles(root); profiles.select('mock')
            before=(root/'config'/'model.json').read_bytes()
            with self.assertRaises(ValueError): profiles.select('not-exist')
            self.assertEqual((root/'config'/'model.json').read_bytes(),before)
    def test_environment_key_takes_precedence(self):
        config=ModelConfig(api_key_env='TEST_AGENT_KEY',api_key_file='nonexistent')
        with patch.dict(os.environ,{'TEST_AGENT_KEY':'test-only-key'}): self.assertEqual(read_key(config),'test-only-key')
    @unittest.skipUnless(os.name=='nt','Windows DPAPI only')
    def test_dpapi_roundtrip_for_current_user(self):
        encrypted=protect(b'test-only-key')
        self.assertNotIn(b'test-only-key',encrypted)
        self.assertEqual(protect(encrypted,decrypt=True),b'test-only-key')
    def test_model_profile_cli_listing_and_switch(self):
        from modular_agent.agent.console import run_console
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp); (root/'config').mkdir()
            (root/'config'/'models.json').write_text(json.dumps({'profiles':{'mock':{'provider':'mock'},'other':{'provider':'mock','model':'other-model'}}}))
            args=SimpleNamespace(config='model.json',model_profile='mock',provider=None,model=None,base_url=None,api_key_env=None,live=False,domain=None,max_steps=1,command='chat')
            output=io.StringIO()
            with patch('builtins.input',side_effect=['/models','/model other','/model','/quit']),patch('sys.stdout',output): run_console(args,root)
            self.assertIn('other-model',output.getvalue())
            self.assertEqual(ModelConfig.from_json(root/'config'/'model.json').model,'other-model')

if __name__=='__main__': unittest.main()
