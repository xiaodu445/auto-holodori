"""Holodori scenario policies, page classification and popup target semantics."""
import time
from .states import classify, UIState
from modular_agent.agent.interaction import (
 InteractionPolicy, RetryBudget, TransitionState, assert_window,
 transition as run_transition,
)

# Every game scene must explicitly choose semantics; no key-level auto-repeat.
SCENARIOS={
 'patrol_movement':'realtime','patrol_pickup':'claim','route_navigation':'realtime','route_jump':'realtime','motion_probe':'realtime',
 'route_memory_jump':'realtime','route_teaching':'passive',
 'minimap_mapping':'passive','minimap_exploration':'realtime',
 'scratch_ticket':'claim','return_to_free':'navigation',
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

def interaction_state(report):
 """Map Holodori evidence to the common runner's small control vocabulary."""
 state=classify(report).state
 if state==UIState.ERROR:return TransitionState.BLOCKED
 if state in (UIState.REWARD,UIState.RANK_UP,UIState.DIALOGUE):return TransitionState.OVERLAY
 if state==UIState.LOADING:return TransitionState.LOADING
 if state==UIState.UNKNOWN:return TransitionState.UNKNOWN
 return TransitionState.READY


def transition(*,observe,send,resolve,source,completed,wait,check=lambda:None,
               policy=None,recover=None,discover=None,emit=lambda *a,**k:None,clock=time.monotonic):
 """Holodori adapter over the game-independent transition runner."""
 return run_transition(observe=observe,send=send,resolve=resolve,source=source,
  completed=completed,wait=wait,state_of=interaction_state,check=check,policy=policy,
  recover=recover,discover=discover,emit=emit,clock=clock)
