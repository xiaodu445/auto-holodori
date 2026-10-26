"""Pure, JSON-safe daily-task planning. Never sends input."""
from dataclasses import asdict,dataclass

NOTIFICATION_TASKS=('holowork','holo_home','the_cell','kaogan','wheel')

@dataclass(frozen=True)
class TaskSpec:
 id:str
 description:str
 phase:int=0
 dependencies:tuple[str,...]=()

CATALOG={
 'holowork':TaskSpec('holowork','领取Holowork，可选择是否重新推荐派遣'),
 'holo_home':TaskSpec('holo_home','holo之家礼物'),
 'the_cell':TaskSpec('the_cell','The Cell再临礼物'),
 'kaogan':TaskSpec('kaogan','颜岩山礼物'),
 'wheel':TaskSpec('wheel','恰玛红心大转盘'),
 'greed_cards_entry':TaskSpec('greed_cards_entry','仅进入强欲之牌准备页',10),
 'greed_cards_play':TaskSpec('greed_cards_play','调用已有玩法程序',20,('greed_cards_entry',)),
 'achievements':TaskSpec('achievements','领取已达成成就，不追做目标',30),
 'events':TaskSpec('events','扫描活动并领取已有奖励',40),
 'task_pass':TaskSpec('task_pass','领取每日/每周/季度Pt及通行证奖励',40),
}
FUTURE_TASKS=('expiry_notice',)


def effective_config(config, request=None, *, root=None):
 from copy import deepcopy
 from modular_agent.agent.capabilities import CapabilityCatalog,validate_schema
 # Reuse the public contract for per-run overrides; never write user defaults.
 request={} if request is None else request
 if not isinstance(request,dict):raise ValueError('每日请求必须为对象')
 overrides=request.get('config_overrides',{})
 from pathlib import Path
 if 'config_overrides' in request:
  root=Path(root) if root is not None else Path(__file__).resolve().parents[4]
  schema=CapabilityCatalog(root).read('hololive_dreams.daily_tasks')['input_schema']['properties']['request']['properties']['config_overrides']
  overrides=validate_schema(overrides,schema,'config_overrides')
 merged={**deepcopy(config),**overrides}
 from modular_agent.domains.hololive_dreams.daily_tasks import validate_config
 validate_config(merged)
 return merged

def catalog():
 return {'schema_version':1,'supported':[asdict(s) for s in CATALOG.values()],
         'not_implemented':list(FUTURE_TASKS)}

def build_plan(config,request=None,extra_tasks=()):
 request={} if request is None else dict(request)
 allowed={'selected_tasks','record_rewards','redispatch_holowork','max_rounds','max_loss','unknown_notification_policy','config_overrides'}
 if request.keys()-allowed: raise ValueError('未知每日计划字段：'+','.join(sorted(request.keys()-allowed)))
 specs=dict(CATALOG)
 for name in extra_tasks:
  if name in specs: raise ValueError('扩展任务不能覆盖内置任务：'+name)
  specs[name]=TaskSpec(name,'注册的扩展任务',30)
 selected=request.get('selected_tasks',config.get('selected_tasks'))
 if selected is None:
  selected=list(NOTIFICATION_TASKS)
  if config['play_greed_cards']: selected+=['greed_cards_entry','greed_cards_play']
 if not isinstance(selected,(list,tuple)) or any(not isinstance(n,str) for n in selected):
  raise ValueError('selected_tasks必须是任务ID列表，空列表表示不执行')
 if len(set(selected))!=len(selected): raise ValueError('任务列表不能重复')
 unknown=set(selected)-specs.keys()
 if unknown: raise ValueError('未实现或未注册的每日任务：'+','.join(sorted(unknown)))
 expanded=list(selected);added=[]
 for name in list(selected):
  for dep in specs[name].dependencies:
   if dep not in expanded: expanded.append(dep);added.append(dep)
 # Stable phase order: notification work, navigation, play, trusted extensions.
 expanded.sort(key=lambda n:specs[n].phase)
 plan={'schema_version':1,'requested_tasks':list(selected),'tasks':expanded,'added_dependencies':added}
 policy=request.get('unknown_notification_policy',config.get('unknown_notification_policy','ignore_run'))
 if policy not in ('ignore_run','stop'):raise ValueError('unknown_notification_policy需ignore_run或stop')
 plan['unknown_notification_policy']=policy
 for key,default in (('record_rewards',False),('redispatch_holowork',True)):
  value=request.get(key,config.get(key,default))
  if type(value) is not bool: raise ValueError(key+'必须为布尔值')
  plan[key]=value
 for key,minimum,maximum in (('max_rounds',1,1000),('max_loss',50,10000000)):
  value=request.get(key,config[key])
  if type(value) is not int or not minimum<=value<=maximum: raise ValueError(key+'超出允许范围')
  plan[key]=value
 return plan
