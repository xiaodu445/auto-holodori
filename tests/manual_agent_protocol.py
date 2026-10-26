"""Verify real Kimi against the agent protocol without observing or operating the desktop."""
import json
from modular_agent.agent.general import SYSTEM
from modular_agent.model_client import ModelConfig,create_model_client
config=ModelConfig.from_json('config/model.json')
payload={'goal':'启动hololivedreams','screen':None,
    'execution':{'live':True,'scope':'current_user_desktop'},
    'available_skills':[{'skill':'launch_game','domain':'hololive_dreams','description':'启动游戏并验证窗口'}],
    'recent_results':[],'conversation':[]}
value=json.loads(create_model_client(config).complete(SYSTEM,json.dumps(payload,ensure_ascii=False)))
assert value.get('decision')=='observe', 'Agent did not request initial observation'
print(json.dumps({'agent_protocol':'passed','model':config.model,'decision':value['decision'],'desktop_accessed':False}))
