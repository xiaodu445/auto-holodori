"""Existing open ticket only; no purchase/exchange or fresh E interaction."""
from .states import classify,UIState
from .interaction import RetryBudget,policy_for

def target(report):
 if classify(report).state!=UIState.SCRATCH_TICKET:return None
 anchor=report.frame.get('world_features',{}).get('anchors',{}).get('scratch_open')
 if not anchor or anchor.get('score',0)<=.90:return None
 return {'label':'scratch_open','bounds':anchor['bounds'],'source':'stable_text_anchor'}

class ScratchTicket:
 def __init__(self):self.budget=RetryBudget(policy_for('scratch_ticket'));self.departed=False
 def update(self,report,click,now,emit=lambda *a,**k:None):
  t=target(report)
  if t is None:
   if self.budget.attempts and classify(report).state in (UIState.REWARD,UIState.RANK_UP,UIState.DIALOGUE,UIState.WORLD,UIState.INTERACTION):self.departed=True
   return False
  if self.departed:return True
  if self.budget.ready(now):
   click(t);self.budget.sent(now)
   emit('scratch_open_attempt',attempt=self.budget.attempts,verification='await_reward_or_transition')
  return True
