"""Reusable UI transition runner; domain adapters provide observation semantics.

No templates, game state classifier or registered game scenarios live here.
"""
from dataclasses import dataclass
from enum import StrEnum
import math
import time


class TransitionState(StrEnum):
    READY = 'ready'
    UNKNOWN = 'unknown'
    LOADING = 'loading'
    OVERLAY = 'overlay'
    BLOCKED = 'blocked'


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

def assert_window(report, *, unavailable_message="交互停止：窗口失焦、不可见或被遮挡", obscured_message=None):
 handle=report.frame.get('target_window_handle')
 w=next((w for w in report.windows if w.get('handle')==handle),None)
 if not w or w.get('minimized') or not w.get('foreground'):
  raise RuntimeError(unavailable_message)
 if report.frame.get('masked_agent_regions'):
  raise RuntimeError(obscured_message or unavailable_message)

def transition(*,observe,send,resolve,source,completed,wait,state_of,check=lambda:None,
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
  state=state_of(r)
  if state==TransitionState.BLOCKED:raise RuntimeError('交互遇到错误或购买确认，拒绝自动推进')
  if state==TransitionState.OVERLAY or r.frame.get('confirmed_popup'):
   transition_seen=True;stable=0
   if recover:recover(r)
  elif state==TransitionState.LOADING:
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
   elif state==TransitionState.UNKNOWN and discover and not discovered and clock()-start>=2:
    discovered=True;emit('interaction_discovery_requested',reason='unexpected_page')
    check();fresh=discover();check();assert_window(fresh)
    if recover:recover(fresh)
  wait(p.poll_interval)
 raise RuntimeError(f'交互未确认目标页面；模式{p.mode}，已发送{budget.attempts}次，未将输入成功当作完成')
