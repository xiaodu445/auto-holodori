"""Provider-neutral text model clients. API credentials never enter public config."""
from __future__ import annotations
from dataclasses import asdict,dataclass
import json
from pathlib import Path
import re
import math
import time
import threading
from http.client import HTTPException
from email.utils import parsedate_to_datetime
from typing import Any, Protocol
from urllib.error import HTTPError,URLError
from urllib.request import Request,urlopen
from .credentials import read_key

@dataclass(frozen=True)
class ModelConfig:
    provider: str='mock'
    model: str='mock-general-agent'
    base_url: str='https://api.openai.com/v1'
    api_key_env: str='OPENAI_API_KEY'
    timeout_seconds: int=60
    store: bool=False
    api_key_file: str | None=None
    max_tokens: int=2048
    temperature: float | None=None
    thinking: str | None=None
    json_mode: bool=False
    max_retries: int=3
    retry_base_seconds: float=2
    retry_max_seconds: float=30
    min_request_interval_seconds: float=0

    @classmethod
    def from_dict(cls,data,base_directory=None):
        data=dict(data)
        if data.get('api_key_file') and base_directory and not Path(data['api_key_file']).is_absolute():
            data['api_key_file']=str((Path(base_directory)/data['api_key_file']).resolve())
        return cls(**data)
    @classmethod
    def from_json(cls,path):
        path=Path(path)
        return cls.from_dict(json.loads(path.read_text(encoding='utf-8-sig')),path.parent)
    def public_dict(self) -> dict[str,Any]: return asdict(self)

class ModelClient(Protocol):
    def complete(self,instructions:str,input_text:str)->str: ...

class MockModelClient:
    def __init__(self,config): self.config=config
    def complete(self,instructions,input_text):
        return json.dumps({'decision':'escalate','reason':'Mock provider never performs live planning.',
            'goal':input_text,'next_action':None},ensure_ascii=False)

class ModelAPIError(RuntimeError):
    def __init__(self,status,category,message):
        super().__init__(f'Model API HTTP {status}: {message}')
        self.status=status
        self.category=category

def _category(error):
    # Inspect details locally, but never print the raw response, account IDs or headers.
    try:
        body=json.loads(error.read(16384))
        detail=body.get('error',{}) if isinstance(body,dict) else {}
        words=' '.join(str(detail.get(k,'')) for k in ('type','code','message')).lower()
    except Exception: words=''
    if any(v in words for v in ('insufficient_quota','exceeded_current_quota','insufficient balance','balance is insufficient','余额不足','欠费')):
        return 'quota'
    if any(v in words for v in ('tpd','tokens per day','daily token','daily quota')): return 'daily_limit'
    if any(v in words for v in ('tpm','tokens per minute','token rate')): return 'token_rate'
    if any(v in words for v in ('rpm','requests per minute','request rate')): return 'request_rate'
    if 'concurrent' in words: return 'concurrency'
    if any(v in words for v in ('overload','capacity')): return 'overload'
    return 'rate_limit'

def _retry_after(headers):
    value=headers.get('Retry-After') if headers else None
    if not value: return None
    try: seconds=float(value)
    except (ValueError,TypeError):
        try: seconds=parsedate_to_datetime(value).timestamp()-time.time()
        except (ValueError,TypeError,OverflowError): return None
    return max(0,seconds) if math.isfinite(seconds) else None

def _wait(seconds,cancelled):
    deadline=time.monotonic()+seconds
    while True:
        if cancelled(): raise RuntimeError('操作会话已停止，取消模型重试。')
        remaining=deadline-time.monotonic()
        if remaining<=0: return
        time.sleep(min(.1,remaining))

def _fetch(request, timeout, progress, cancelled):
    """Bound waiting for the entire response, including a server that trickles bytes."""
    finished=threading.Event()
    result={}
    def work():
        try:
            with urlopen(request,timeout=timeout) as response:
                result['body']=json.loads(response.read().decode('utf-8'))
        except Exception as error:
            result['error']=error
        finally:
            finished.set()
    threading.Thread(target=work,name='model-http',daemon=True).start()
    started=time.monotonic()
    next_notice=10
    while not finished.wait(.1):
        if cancelled(): raise RuntimeError('操作会话已停止，取消等待模型返回。')
        elapsed=time.monotonic()-started
        if elapsed>=timeout:
            raise TimeoutError('Model response deadline exceeded')
        if elapsed>=next_notice:
            progress(f'仍在等待模型响应：已等待 {elapsed:.0f} 秒，本次最多等待 {timeout:g} 秒……')
            next_notice+=10
    if cancelled(): raise RuntimeError('操作会话已停止，忽略模型返回。')
    if 'error' in result: raise result['error']
    return result['body']

def _request(config,suffix,payload,*,progress=lambda message:None,cancelled=lambda:False):
    if type(config.max_retries) is not int or not 0<=config.max_retries<=5:
        raise ValueError('max_retries must be 0..5')
    for value in (config.retry_base_seconds,config.retry_max_seconds):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<value<=60:
            raise ValueError('Retry delays must be finite and within 0..60 seconds')
    timeout=config.timeout_seconds
    if isinstance(timeout,bool) or not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or not .1<=timeout<=600:
        raise ValueError('timeout_seconds must be finite and within 0.1..600')
    key=read_key(config)
    request=Request(config.base_url.rstrip('/')+suffix,
        data=json.dumps(payload).encode('utf-8'),method='POST',
        headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
    categories={'quota':'账号余额、代金券或额度不足；请检查模型服务控制台，不自动重试。',
        'daily_limit':'已达到每日 Token 限额；等待额度重置或检查账号限额。',
        'token_rate':'每分钟 Token 限流', 'request_rate':'每分钟请求次数限流',
        'concurrency':'并发请求限流', 'overload':'服务暂时过载', 'rate_limit':'临时限流（具体原因未明确）'}
    for attempt in range(config.max_retries+1):
        if cancelled(): raise RuntimeError('操作会话已停止，不再发送模型请求。')
        progress(f'发送模型请求（第 {attempt+1}/{config.max_retries+1} 次，本次超时 {timeout:g} 秒）……')
        try:
            return _fetch(request,timeout,progress,cancelled)
        except HTTPError as error:
            if error.code in (402,403,429):
                category=_category(error)
                if category in ('quota','daily_limit'):
                    raise ModelAPIError(error.code,category,categories[category]) from None
            if error.code==429 or error.code in (408,500,502,503,504):
                if error.code!=429:
                    category='overload'
                if attempt>=config.max_retries:
                    raise ModelAPIError(error.code,category,categories[category]+'；有限重试后仍未恢复，请稍后再试或检查账号限额。') from None
                instructed=_retry_after(error.headers)
                if instructed is not None and instructed>config.retry_max_seconds:
                    raise ModelAPIError(error.code,category,f'{categories[category]}；服务要求等待至少 {math.ceil(instructed)} 秒，请稍后重新提交。') from None
                delay=instructed if instructed is not None else min(config.retry_max_seconds,config.retry_base_seconds*2**attempt)
                progress(f'{categories[category]}：等待 {delay:g} 秒后重试（{attempt+1}/{config.max_retries}）……')
                _wait(delay,cancelled)
                continue
            if error.code==401: detail='Authentication failed; check API key and service endpoint'
            elif error.code in (402,403): detail='权限或账号额度异常，请检查控制台。'
            else: detail='Provider rejected the request; check model and request parameters'
            raise ModelAPIError(error.code,'provider',detail) from None
        except (URLError,TimeoutError,ConnectionError,OSError,HTTPException) as error:
            detail='模型响应超时' if isinstance(error,TimeoutError) or (isinstance(error,URLError) and isinstance(error.reason,TimeoutError)) else '模型连接中断或网络异常'
            if attempt>=config.max_retries:
                raise RuntimeError(f'{detail}；已尝试 {attempt+1} 次，停止本任务。可以检查网络后重新提交。') from None
            delay=min(config.retry_max_seconds,config.retry_base_seconds*2**attempt)
            progress(f'{detail}：等待 {delay:g} 秒后重试（{attempt+1}/{config.max_retries}）……')
            _wait(delay,cancelled)

def _pace(client):
    interval=client.config.min_request_interval_seconds
    if isinstance(interval,bool) or not isinstance(interval,(int,float)) or not math.isfinite(interval) or not 0<=interval<=60:
        raise ValueError('min_request_interval_seconds must be 0..60')
    if client._last_request is not None:
        _wait(max(0,interval-(time.monotonic()-client._last_request)),client.cancelled)
    client._last_request=time.monotonic()

class OpenAIResponsesClient:
    def __init__(self,config):
        self.config=config
        self.on_retry=lambda message:None
        self.cancelled=lambda:False
        self._last_request=None
    def complete(self,instructions,input_text):
        _pace(self)
        return _extract_output_text(_request(self.config,'/responses',{
            'model':self.config.model,'instructions':instructions,'input':input_text,'store':self.config.store},progress=self.on_retry,cancelled=self.cancelled))

class ChatCompletionsClient:
    """Kimi/Moonshot and other OpenAI-compatible chat completion services."""
    def __init__(self,config):
        self.config=config
        self.on_retry=lambda message:None
        self.cancelled=lambda:False
        self._last_request=None
    def complete(self,instructions,input_text):
        _pace(self)
        payload={'model':self.config.model,'messages':[
            {'role':'system','content':instructions},{'role':'user','content':input_text}],
            'stream':False,'max_tokens':self.config.max_tokens}
        if self.config.temperature is not None: payload['temperature']=self.config.temperature
        if self.config.thinking is not None: payload['thinking']={'type':self.config.thinking}
        if self.config.json_mode: payload['response_format']={'type':'json_object'}
        body=_request(self.config,'/chat/completions',payload,progress=self.on_retry,cancelled=self.cancelled)
        try:
            choice=body['choices'][0]
            if choice.get('finish_reason')=='length': raise RuntimeError('Model output was truncated; increase max_tokens')
            content=choice['message']['content']
            if not isinstance(content,str) or not content.strip(): raise ValueError('Empty content')
        except (KeyError,IndexError,TypeError,ValueError):
            raise RuntimeError('Model response contained no assistant text') from None
        # Strip a complete enclosing JSON fence, without extracting arbitrary substrings.
        match=re.fullmatch(r'\s*```(?:json)?\s*\n?(.*?)\s*```\s*',content,re.S)
        return match.group(1).strip() if match else content.strip()

def _extract_output_text(body):
    chunks=[]
    for item in body.get('output',[]):
        for content in item.get('content',[]):
            if content.get('type')=='output_text': chunks.append(content.get('text',''))
    if not chunks: raise RuntimeError('Model response contained no output_text')
    return '\n'.join(chunks)

def create_model_client(config):
    clients={'mock':MockModelClient,'openai_responses':OpenAIResponsesClient,'openai_chat':ChatCompletionsClient}
    if config.provider not in clients: raise ValueError('Supported providers: '+', '.join(clients))
    return clients[config.provider](config)
