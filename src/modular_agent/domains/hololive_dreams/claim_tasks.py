"""Bounded, claim-only UI workflows using the daily input/journal safety layer.

No badge absence is treated as completion. Fixed navigation points require a
confirmed page; reward buttons require fresh visual evidence in the content ROI.
"""
from .states import classify, UIState
from .interaction import RetryBudget,InteractionPolicy,text_button

TEMPLATES=['claim_'+n for n in (
 'pass_page','tasks_tab','pass_tab','daily_tab','weekly_tab','season_tab',
 'all','all_task','one','available','achievement_page','event_carousel','event_page',
 'event_home','event_go','event_daily','event_free')]

def templates_for(task):
 common=['claim_all','claim_all_task','claim_one','claim_close']
 groups={'achievements':['claim_achievement_page','claim_available'],
         'task_pass':['claim_pass_page','claim_pass_page_sample'],
         'events':['claim_event_carousel','claim_event_page','claim_event_home','claim_event_home_sample','claim_event_go','claim_event_daily','claim_event_free']}
 return common+groups[task] if task in groups else TEMPLATES

class ClaimTasks:
 def __init__(self,daily):
  self.d=daily;self.claims=0;self.scans=0
  self.popup_key=None;self.popup_budget=None

 def match(self,r,name,zone=(0,0,1,1),excluded_rows=()):
  b=r.frame['bounds'];x0,y0,x1,y1=zone
  candidates=[]
  for m in r.knowledge_matches:
   labels=('claim_all','claim_all_task') if name=='all' else ('claim_'+name,'claim_'+name+'_sample')
   if m.get('label') not in labels or m.get('similarity',0)<.92:continue
   if name in ('all','one') and not m.get('claim_enabled',False):continue
   q=m['bounds'];x=(q['x']+q['width']/2-b['x'])/b['width'];y=(q['y']+q['height']/2-b['y'])/b['height']
   if name=='available' and any(abs(y-row)<.025 for row in excluded_rows):continue
   if x0<=x<=x1 and y0<=y<=y1:candidates.append(m)
  return max(candidates,key=lambda m:m['similarity']) if candidates else None

 def point(self,x,y):
  b=self.d.report.frame['bounds']
  self.d.send('click',x=b['x']+round(b['width']*x),y=b['y']+round(b['height']*y),modifiers=['alt'])

 def row_target(self,r,row,excluded):
  target=self.match(r,'available',(.82,.22,.96,.98),excluded)
  if not target:return None
  b=r.frame['bounds'];q=target['bounds'];current=(q['y']+q['height']/2-b['y'])/b['height']
  return target if abs(current-row)<.025 else None

 def navigate(self,resolve,source,*destination):
  return self.d.transition(resolve=resolve,source=source,
    completed=lambda r:any(self.match(r,n) for n in destination),recover=self.recover)

 def recover(self,r):
  state=classify(r).state
  if state in (UIState.REWARD,UIState.RANK_UP):
   key=state.value
   if self.popup_key!=key:self.popup_key=key;self.popup_budget=RetryBudget()
   if self.popup_budget.ready(self.d.clock()):
    self.d.blank();self.popup_budget.sent(self.d.clock())
   return True
  # Exact labels only, never an arbitrary GO/purchase/match confirmation.
  known=bool(r.frame.get('confirmed_popup'))
  target=text_button(r,('确定','继续','下一步','关闭'),known_page=known,zone=(.15,.15,.98,.98))
  if target:
   key=(str(r.frame['confirmed_popup']),target['label'])
   if self.popup_key!=key:self.popup_key=key;self.popup_budget=RetryBudget()
   if self.popup_budget.ready(self.d.clock()):self.d.click(target);self.popup_budget.sent(self.d.clock())
   return True
  self.popup_key=None
  return False

 def page(self,*names):
  start=self.d.clock();discoveries=0;last_discovery=start
  while self.d.clock()-start<self.d.config['transition_timeout_seconds']:
   r=self.d.capture();state=classify(r).state
   if state==UIState.ERROR:raise RuntimeError('领取流程出现错误弹窗')
   if self.recover(r):pass
   elif any(self.match(r,n) for n in names):return r
   elif state==UIState.UNKNOWN and self.d.discover_callback and discoveries<3 and self.d.clock()-last_discovery>=2:
    self.recover(self.d.capture(recovery=True));discoveries+=1;last_discovery=self.d.clock()
   self.d.wait(.4)
  raise RuntimeError('未确认领取页面：'+','.join(names))

 def scroll(self,ticks=-4):
  b=self.d.report.frame['bounds']
  self.d.send('move_to',x=b['x']+round(b['width']*.72),y=b['y']+round(b['height']*.55),modifiers=['alt'])
  self.d.send('scroll',ticks=ticks,modifiers=['alt']);self.d.wait(.6)

 def claim(self,target):
  self.d.click(target);self.d.wait(.5)
  start=self.d.clock();seen=False;closed=0;last=-100
  budget=RetryBudget(InteractionPolicy(mode='claim'));budget.sent(start)
  discoveries=0;last_discovery=start;popup_seen=False
  while self.d.clock()-start<self.d.config['transition_timeout_seconds']:
   r=self.d.capture();state=classify(r).state
   if state in (UIState.REWARD,UIState.RANK_UP) or self.d.target('daily_rewards_get',r):
    seen=True;closed=0
    if self.d.clock()-last>=1:self.d.blank();last=self.d.clock()
   elif state==UIState.ERROR:raise RuntimeError('领取奖励时出现错误弹窗')
   elif seen and any(self.match(r,n) for n in ('pass_page','achievement_page','event_page','event_home','event_carousel')):
    closed+=1
    if closed>=2:self.claims+=1;return
   else:
    closed=0
    if r.frame.get('confirmed_popup'):
     popup_seen=True;self.recover(r);self.d.wait(.35);continue
    if state==UIState.UNKNOWN and not self.match(r,'all') and not self.match(r,'one') and self.d.discover_callback and discoveries<3 and self.d.clock()-last_discovery>=2:
     fresh=self.d.capture(recovery=True);discoveries+=1;last_discovery=self.d.clock()
     if self.recover(fresh):
      popup_seen=True
      if classify(fresh).state in (UIState.REWARD,UIState.RANK_UP):seen=True
    # No reward was observed: retry only the same still-enabled button from
    # this fresh capture, corroborated by an enabled individual claim.
    # Never retry once any reward/rank layer has been seen.
    if state in (UIState.UNKNOWN,UIState.ACHIEVEMENT_DETAIL) and budget.ready(self.d.clock(),transition_seen=seen or popup_seen):
     is_all=target.get('label') in ('claim_all','claim_all_task')
     candidate=self.match(r,'all',(.72,.80,.97,.96)) if is_all else self.match(r,'one',(.77,.26,.95,.82))
     corroborated=not is_all or self.match(r,'one',(.77,.26,.95,.82)) is not None
     if candidate and corroborated:
      a=target['bounds'];b=candidate['bounds']
      same=abs(a['x']-b['x'])<=16 and abs(a['y']-b['y'])<=8
      if same:
       self.d.emit('claim_retry',attempt=budget.attempts+1,evidence='same_enabled_button_and_individual_claim_no_reward_seen')
       self.d.click(candidate);budget.sent(self.d.clock())
   self.d.wait(.35)
  raise RuntimeError('点击领取后未确认完整奖励弹层流程，不重复领取')

 def scan(self,anchors,pages=6):
  # Every page is revalidated after rewards; at most 60 claims per section.
  for page_index in range(pages):
   for _ in range(60):
    r=self.page(*anchors);self.scans+=1
    target=self.match(r,'all',(.72,.80,.97,.96)) or self.match(r,'one',(.77,.26,.95,.82))
    if not target:break
    self.claim(target)
   else:raise RuntimeError('领取次数达到安全上限')
   if page_index+1<pages:self.scroll()

 def leave(self):
  start=self.d.clock();budget=RetryBudget();fallback=RetryBudget()
  while self.d.clock()-start<self.d.config['transition_timeout_seconds']:
   r=self.d.capture()
   if self.d.free(r,allow_interaction=True):self.d.until_free(allow_interaction=True);return
   state=classify(r).state
   if state in (UIState.REWARD,UIState.RANK_UP):self.recover(r)
   elif state==UIState.ERROR:raise RuntimeError('退出领取页面时遇到错误弹窗')
   elif self.match(r,'close',(.92,.04,.99,.17)):
    if budget.ready(self.d.clock()):
     self.d.click(self.match(r,'close',(.92,.04,.99,.17)));budget.sent(self.d.clock())
    elif budget.attempts>=budget.policy.max_attempts and self.d.clock()-budget.last>=2 and fallback.ready(self.d.clock()):
     self.d.send('press',key='escape',duration=.08);fallback.sent(self.d.clock())
   elif state==UIState.LOADING:self.d.wait(.6)
   elif fallback.ready(self.d.clock()):
    self.d.send('press',key='escape',duration=.08);fallback.sent(self.d.clock())
   self.d.wait(.6)
  raise RuntimeError('未确认退出领取页面')

 def task_pass(self):
  self.page('pass_page');self.point(.32,.265);self.d.wait(.6)
  for y in (.40,.51,.63):
   self.page('pass_page');self.point(.15,y);self.d.wait(.6)
   self.scan(('pass_page',),pages=1)
  self.page('pass_page');self.point(.14,.265);self.d.wait(.6)
  self.scan(('pass_page',),pages=1)

 def achievements(self):
  for y in (.29,.41,.53,.65,.77,.88):
   self.page('achievement_page');self.point(.125,y);self.d.wait(.6)
   excluded=[];empty=0
   # Claimable entries sort to the front; never scroll the right-hand list.
   for _ in range(60):
    r=self.page('achievement_page')
    item=self.match(r,'available',(.82,.22,.96,.98),excluded)
    if not item:
     empty+=1
     if empty>=2:break
     self.d.wait(.3);continue
    empty=0
    old_y=item['bounds']['y'];self.d.wait(.2)
    r=self.page('achievement_page');item=self.match(r,'available',(.82,.22,.96,.98),excluded)
    if not item or abs(item['bounds']['y']-old_y)>8:continue
    row=(item['bounds']['y']+item['bounds']['height']/2-r.frame['bounds']['y'])/r.frame['bounds']['height']
    self.d.transition(
     resolve=lambda r:self.row_target(r,row,excluded),
     source=lambda r:bool(self.match(r,'achievement_page')),
     completed=lambda r:any(m.get('label') in ('claim_all','claim_all_task') and m.get('similarity',0)>=.92 for m in r.knowledge_matches),
     recover=self.recover)
    if not self.achievement_detail():excluded.append(row)
   else:raise RuntimeError('成就领取达到安全上限')

 def achievement_detail(self):
  start=self.d.clock();empty=0;previous=None
  while self.d.clock()-start<self.d.config['transition_timeout_seconds']:
   r=self.d.capture();state=classify(r).state
   if state in (UIState.REWARD,UIState.RANK_UP):self.d.blank();empty=0
   elif state==UIState.ERROR:raise RuntimeError('成就详情出现错误弹窗')
   else:
    target=self.match(r,'all',(.72,.80,.97,.96))
    one=self.match(r,'one',(.77,.26,.95,.82))
    if target and one:
     b=target['bounds']
     stable=previous and abs(previous['x']-b['x'])<=2 and abs(previous['y']-b['y'])<=2
     previous=b
     if stable:self.claim(target);return True
    else:previous=None
    known=state==UIState.ACHIEVEMENT_DETAIL or any(m.get('label') in ('claim_all','claim_all_task') and m.get('similarity',0)>=.92 for m in r.knowledge_matches)
    empty=empty+1 if known and not target and not one else 0
    if empty>=2:
     self.d.emit('achievement_no_claimable_reward',verification='disabled_all_and_no_enabled_single_claim')
     self.d.send('press',key='escape',duration=.08);self.d.wait(.5)
     self.page('achievement_page');return False
   self.d.wait(.3)
  raise RuntimeError('成就详情未确认可领取；停止，不点击暗按钮')

 def events(self):
  visited=[]
  for _ in range(8):
   r=self.page('event_carousel')
   card=r.frame.get('claim_search',{}).get('event_card')
   if card:
    if any(sum(abs(a-b) for a,b in zip(card,old))/len(card)<12 for old in visited):
     self.d.emit('event_scan_stopped',reason='repeated_carousel_card');return
    visited.append(card)
   go=self.match(r,'event_go',(.80,.83,.96,.96))
   if not go:raise RuntimeError('活动入口未识别，本次未处理')
   r=self.navigate(lambda r:self.match(r,'event_go',(.80,.83,.96,.96)),
                   lambda r:bool(self.match(r,'event_carousel')),'event_home','event_page')
   home=self.match(r,'event_home',(.90,.50,.98,.70))
   if home and home.get('notification_badge') is False:
    self.d.emit('event_skipped',reason='task_badge_absent_on_supported_home')
    self.d.send('press',key='escape',duration=.08);self.d.wait(.6)
    self.page('event_carousel');self.scroll(-1);continue
   if home:self.navigate(lambda r:self.match(r,'event_home',(.90,.50,.98,.70)),
                         lambda r:bool(self.match(r,'event_home')),'event_page')
   r=self.page('event_page')
   tabs=bool(self.match(r,'event_daily') or self.match(r,'event_free'))
   for x in ((.48,.80) if tabs else (None,)):
    self.page('event_page')
    if x is not None:self.point(x,.24);self.d.wait(.5)
    self.scan(('event_page',))
   for _ in range(3):
    r=self.d.capture()
    if self.match(r,'event_carousel'):break
    self.d.send('press',key='escape',duration=.08);self.d.wait(.6)
   self.page('event_carousel');self.scroll(-1)

 def run(self,task):
  self.d.current_task=task;self.d.observation_phase='claims'
  self.d.until_free(allow_interaction=True)
  self.d.capture()
  if task=='achievements':
   previous=None;stable=0
   for _ in range(4):
    value=self.d.report.frame.get('world_features',{}).get('achievement_badge')
    stable=stable+1 if type(value) is bool and value==previous else 1 if type(value) is bool else 0
    previous=value
    if stable>=2:break
    self.d.wait(.3);self.d.capture()
   if stable<2:return {'outcome':'unknown','verified':False,'message':'未确认成就感叹号，不尝试进入'}
   if value is False:return {'outcome':'skipped','verified':True,'verification':'achievement_badge_absent_two_frames','message':'成就无感叹号，本次跳过入口'}
  def entrance(r):
   b=r.frame['bounds'];x=b['x']+round(b['width']*{'events':.58,'task_pass':.765,'achievements':.825}[task]);y=b['y']+round(b['height']*.125)
   return {'label':'open_'+task,'bounds':dict(x=x-10,y=y-10,width=20,height=20)}
  destination={'events':'event_carousel','task_pass':'pass_page','achievements':'achievement_page'}[task]
  if task=='events' and self.d.free(self.d.report,True) and self.d.report.frame.get('claim_search',{}).get('activity_badge') is False:
   self.d.wait(.3);r=self.d.capture()
   if self.d.free(r,True) and r.frame.get('claim_search',{}).get('activity_badge') is False:
    return {'outcome':'skipped','verified':False,'message':'活动入口连续两帧无感叹号，本次跳过；不代表奖励全清'}
  try:
   self.navigate(entrance,lambda r:self.d.free(r,allow_interaction=True),destination)
   getattr(self,task)();self.leave()
  except RuntimeError as error:
   self.d.check()
   self.d.emit('claim_module_incomplete',task=task,message=str(error))
   try:self.leave()
   except RuntimeError as exit_error:
    raise RuntimeError(str(error)+'；退出未确认：'+str(exit_error)) from error
   return {'outcome':'unknown','verified':False,'returned_to_world':True,'message':str(error)}
  return {'outcome':'success','verified':False,'reward_episodes':self.claims,
          'scans':self.scans,'verification':'bounded_visual_scan',
          'message':'已完成有界扫描；不保证全部感叹号清空或奖励数量入账'}

def annotate_enabled(matches,image,origin):
 """Same-frame colour evidence: grayscale correlation cannot reject disabled UI."""
 for m in matches:
  if m.get('label') not in ('claim_all','claim_all_task','claim_one'):continue
  q=m['bounds'];x=q['x']-origin[0];y=q['y']-origin[1]
  patch=image[max(0,y):y+q['height'],max(0,x):x+q['width']]
  enabled=False
  if patch.size and patch.ndim==3:
   blue=(patch[:,:,0]>220)&(patch[:,:,1]>160)&(patch[:,:,2]<100)
   white=(patch.min(axis=2)>=230)&((patch.max(axis=2).astype('int16')-patch.min(axis=2))<25)
   # Exclude the checkmark/left ornament: those can stay white when text is grey.
   text=white[:,round(patch.shape[1]*.35):]
   enabled=float(blue.mean())>.35 and float(white.mean())>.08 and text.size>0 and float(text.mean())>.08
  m['claim_enabled']=enabled
 return matches
