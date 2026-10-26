"""Shared game interaction protocol, never an automatic raw-input repeater.

Callers supply semantic source/target/expected-page predicates. Input delivery
is NOT acknowledgement. The default refuses passive/realtime/unsafe actions.
"""
from dataclasses import dataclass
import math
import time
from .states import classify,UIState

@dataclass(frozen=True)
class InteractionPolicy:
 timeout:float=25
 retry_interval:float=2
 max_attempts:int=3
 poll_interval:float=.3
 stable_frames:int=2
 mode:str='menu'
 def __post_init__(self):
  for name in ('timeout','retry_interval','poll_interval'):
   v=getattr(self,name)
   if type(v) not in (int,float) or not math.isfinite(v) or v<=0:raise ValueError(name)
  if type(self.max_attempts) is not int or not 1<=self.max_attempts<=10:raise ValueError('max_attempts')
  if type(self.stable_frames) is not int or not 1<=self.stable_frames<=10:raise ValueError('stable_frames')
  if self.mode not in ('menu','navigation','claim','dialogue','passive','realtime','nonrepeatable'):raise ValueError('mode')

class RetryBudget:
 def __init__(self,policy=None):
  self.policy=policy or InteractionPolicy();self.attempts=0;self.last=-math.inf
 def ready(self,now,*,source_valid=True,enabled=True,transition_seen=False):
  p=self.policy
  if p.mode in ('passive','realtime'):return False
  limit=1 if p.mode=='nonrepeatable' else p.max_attempts
  return bool(source_valid and enabled and not transition_seen and self.attempts<limit and now-self.last>=p.retry_interval)
 def sent(self,now):self.attempts+=1;self.last=now

# Every game scene must explicitly choose semantics; no key-level auto-repeat.
SCENARIOS={
 'patrol_movement':'realtime','patrol_pickup':'claim','route_navigation':'realtime','route_jump':'realtime','motion_probe':'realtime',
 'route_memory_jump':'realtime','route_teaching':'passive',
 'minimap_mapping':'passive','minimap_exploration':'realtime',
 'scratch_ticket':'claim',
 'startup':'navigation','world_navigation':'navigation','map_navigation':'navigation',
 'notifications':'navigation','holowork':'claim','gift':'claim','wheel':'claim',
 'task_pass':'claim','events':'menu','achievements':'claim','popup':'menu',
 'dialogue':'dialogue','live_menu':'menu','live_matching':'passive',
 'kitchen_loop_score_next':'menu','kitchen_loop_reward_ok':'menu','kitchen_loop_event_next':'menu','kitchen_loop_play':'menu',
 'loading':'passive','rhythm_play':'realtime','kitchen_play':'realtime','kitchen_order_continue':'menu','kitchen_result_continue':'menu','bet_or_spend':'nonrepeatable',
}

def policy_for(scene,**overrides):
 if scene not in SCENARIOS:raise ValueError('场景必须显式注册交互策略：'+scene)
 return InteractionPolicy(mode=SCENARIOS[scene],**overrides)

def assert_window(report):
 handle=report.frame.get('target_window_handle')
 w=next((w for w in report.windows if w.get('handle')==handle),None)
 if not w or w.get('minimized') or not w.get('foreground') or report.frame.get('masked_agent_regions'):
  raise RuntimeError('交互停止：窗口失焦、不可见或被遮挡')

def text_button(report,labels,*,known_page=False,zone=(0,0,1,1)):
 """Only exact allowlisted labels on a recognized popup AND enabled control.

OCR text or a CV rectangle alone does not prove enabled/clickable semantics.
An adapter may attach button enabled evidence from current pixels/UIA.
"""
 if not known_page:return None
 forbidden=('购买','充值','兑换','解锁','决定成员','确认成员','删除')
 allowed={''.join(s.split()) for s in labels}
 frame=report.frame['bounds'];candidates=[]
 for b in report.buttons:
  label=''.join(str(b.get('label','')).split())
  if label not in allowed or any(s in label for s in forbidden) or b.get('enabled') is not True:continue
  if not b.get('semantic_confirmed',False):continue
  if b.get('confidence',0)<.9:continue
  q=b['bounds'];x=(q['x']+q['width']/2-frame['x'])/frame['width'];y=(q['y']+q['height']/2-frame['y'])/frame['height']
  if zone[0]<=x<=zone[2] and zone[1]<=y<=zone[3]:candidates.append(b)
 return max(candidates,key=lambda b:b['confidence']) if candidates else None

def transition(*,observe,send,resolve,source,completed,wait,check=lambda:None,
               policy=None,recover=None,discover=None,emit=lambda *a,**k:None,clock=time.monotonic):
 """Observe -> recover popup -> verify destination -> fresh target -> input.

recover(report) handles ONLY registered popups and returns whether it handled
this frame; it must also bound its own input. discover is called at most once,
on an unrecognized page after 2s, and MUST return a fresh full report.
"""
 p=policy or InteractionPolicy();budget=RetryBudget(p)
 start=clock();stable=0;discovered=False;transition_seen=False
 while clock()-start<p.timeout:
  check();r=observe();check();assert_window(r)
  state=classify(r).state
  if state==UIState.ERROR:raise RuntimeError('交互遇到错误或购买确认，拒绝自动推进')
  if state in (UIState.REWARD,UIState.RANK_UP,UIState.DIALOGUE) or r.frame.get('confirmed_popup'):
   transition_seen=True;stable=0
   if recover:recover(r)
  elif state==UIState.LOADING:
   stable=0
  elif completed(r):
   stable+=1
   if stable>=p.stable_frames:
    emit('interaction_confirmed',attempts=budget.attempts,mode=p.mode);return r
  else:
   stable=0
   current=source(r)
   if current:
    target=resolve(r)
    enabled=target is not None and target.get('enabled') is not False and target.get('claim_enabled') is not False
    if target is not None and budget.ready(clock(),source_valid=True,enabled=enabled,transition_seen=transition_seen):
     check();send(target);budget.sent(clock())
     emit('interaction_sent',attempt=budget.attempts,mode=p.mode)
   elif state==UIState.UNKNOWN and discover and not discovered and clock()-start>=2:
    discovered=True;emit('interaction_discovery_requested',reason='unexpected_page')
    check();fresh=discover();check();assert_window(fresh)
    if recover:recover(fresh)
  wait(p.poll_interval)
 raise RuntimeError(f'交互未确认目标页面；模式{p.mode}，已发送{budget.attempts}次，未将输入成功当作完成')
