"""Print only official service model IDs or sanitized error classification."""
import json
import re
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from modular_agent.model_client import ModelConfig
from modular_agent.credentials import read_key
config=ModelConfig.from_json('config/model.json')
request=Request(config.base_url.rstrip('/')+'/models',headers={'Authorization':'Bearer '+read_key(config)})
try:
    with urlopen(request,timeout=30) as response: result=json.loads(response.read())
    print(json.dumps({'models':[item['id'] for item in result.get('data',[])]}))
except HTTPError as error:
    try:
        info=json.loads(error.read()).get('error',{})
        message=re.sub(r'sk-[A-Za-z0-9_-]+','[redacted]',str(info.get('message','')))
        print(json.dumps({'http':error.code,'type':info.get('type'),'message':message[:200]}))
    except Exception: print(json.dumps({'http':error.code}))
