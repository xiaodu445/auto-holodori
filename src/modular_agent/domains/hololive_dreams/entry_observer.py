"""Stage-scoped templates first; bounded OCR fallback on a fresh frame."""
import time
from modular_agent.agent.launcher import GameLauncher

from .templates import MAP, DETAIL, WORLD, READY, SEMANTICS
from .states import classify
from .trace import EntryTrace
class EntryObserver:
 def __init__(self,adapter,tree,progress=print,clock=time.monotonic):
  self.adapter=adapter;self.tree=tree;self.progress=progress;self.clock=clock
  self.last_ocr=-float('inf');self.unknown_since=None
  self.trace=EntryTrace(adapter.root) if getattr(adapter,'root',None) else None
  if self.trace:
   tree.trace=self.trace
   self.progress('入口运行记录：'+str(self.trace.directory))
 def __call__(self):
  vision=self.adapter._vision_for('hololive_dreams')
  profile=next(p for p in self.adapter.profiles if p['domain']=='hololive_dreams')
  window=GameLauncher(vision,self.adapter.computer,profile)._window(vision.desktop.windows())
  if not window or window.get('minimized'): raise RuntimeError('入口观察未找到可见游戏窗口')
  phase=getattr(self.tree,'last_state','initial')
  if phase in ('teleport','arrived','interact','dialogue','await_game','lever_teleport','lever_interact','switch_casino','keep_casino','await_lever'):
   names=WORLD+READY+MAP
  elif phase in ('select_area','select_smallgame','select_arcade','select_lobby','select_lever','wrong_detail'):
   names=MAP+DETAIL+['map2','smallgame','time']
  else: names=MAP+DETAIL+WORLD+READY+['map2','smallgame','time']
  names=list(dict.fromkeys(names+['menu','stage','task']))
  if self.unknown_since is not None and self.clock()-self.unknown_since>=2:
   names.append('entry_search_wide')
  r=vision.observe(environment='hololive_dreams',window_handle=window['handle'],
   enable_ocr=False,enable_uia=False,enable_cv_buttons=False,
   template_names=names,template_scales=[1.0])
  for m in r.knowledge_matches:
   for value in SEMANTICS.get(m['label'],[]):
    r.texts.append(dict(id=m['id']+':'+value,text=value,source='template',bounds=m['bounds']))
  labels={m['label'] for m in r.knowledge_matches}
  # Generic layout evidence stays structured; never invent OCR text for HUD.
  decision=self.tree.decide(r)
  if decision.get('outcome')=='unknown':
   now=self.clock()
   if self.unknown_since is None: self.unknown_since=now
   if now-self.unknown_since>=5 and now-self.last_ocr>=5:
    self.progress('入口模板证据不足，按需OCR复核（UIA关闭）')
    self.last_ocr=now;self.unknown_since=now
    r=vision.observe(environment='hololive_dreams',window_handle=window['handle'],
     enable_ocr=True,enable_uia=False,enable_cv_buttons=False,
     template_names=names,template_scales=[1.0])
    recognition=classify(r)
    r.frame['ui_state']=recognition.to_dict()
    if self.trace: self.trace.observation(r,recognition,True)
    return r
  else: self.unknown_since=None
  self.progress('入口模板观察：'+phase+'；OCR关闭；'+', '.join(f'{k} {v:.0f}ms' for k,v in r.timings_ms.items()))
  recognition=classify(r)
  r.frame['ui_state']=recognition.to_dict()
  if self.trace: self.trace.observation(r,recognition,False)
  return r
