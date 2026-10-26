"""Template-led daily notification dispatcher. Inputs are grounded in fresh captures."""
import math
import time
from modular_agent.agent.ui_actions import send_action, target_center
from modular_agent.agent.interaction import assert_window
from modular_agent.domains.hololive_dreams.states import classify, UIState
from modular_agent.domains.hololive_dreams.daily_journal import RewardRecorder
from modular_agent.domains.hololive_dreams.interaction import InteractionPolicy,transition

NOTICES=('holowork','holo_home','the_cell','kaogan','wheel')
WORK=('daily_work_claim_all','daily_work_claim_summary','daily_rewards_get',
      'daily_work_setup_all','daily_work_recommend','daily_work_decide','daily_back')
TEMPLATES=['attention','menu','stage','task',*('daily_notice_'+n for n in NOTICES),
           *WORK,'daily_work_setup_all_sample','daily_gift_interact','daily_wheel_interact']


def validate_config(config):
    threshold=config.get('template_threshold',.6)
    if type(threshold) not in (int,float) or not math.isfinite(threshold) or not 0<threshold<=1:
        raise ValueError('template_threshold需0至1之间')
    for name in ('nearby_walk_step_seconds','nearby_walk_max_seconds','teleport_wait_seconds',
                 'click_interval_seconds','transition_timeout_seconds'):
        v=config[name]
        if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<v<=120:
            raise ValueError('每日配置无效：'+name)
    if config['nearby_walk_step_seconds']>30 or config['teleport_wait_seconds']>30:
        raise ValueError('单次按键或等待不能超过30秒')
    for item in config['holo_home_route']:
        if item.get('key') not in ('w','a','s','d') or not isinstance(item.get('seconds'),(int,float)) or not 0<item['seconds']<=30:
            raise ValueError('holo之家路线需W/A/S/D和0至30秒时长')
    if type(config['notification_scroll_pages']) is not int or not 1<=config['notification_scroll_pages']<=10:
        raise ValueError('通知扫描页数需1至10')
    if type(config['play_greed_cards']) is not bool: raise ValueError('play_greed_cards需true或false')
    if config.get('unknown_notification_policy','ignore_run') not in ('ignore_run','stop'):
        raise ValueError('unknown_notification_policy需ignore_run或stop')
    if type(config['max_rounds']) is not int or not 1<=config['max_rounds']<=1000: raise ValueError('max_rounds无效')
    if type(config['max_loss']) is not int or config['max_loss']<0: raise ValueError('max_loss无效')
    fixed=config.get('attention_fixed_region',{'enabled':True,'x_ratio':.205,'y_ratio':.125})
    if not isinstance(fixed,dict) or set(fixed)!={'enabled','x_ratio','y_ratio'} or type(fixed['enabled']) is not bool:
        raise ValueError('attention_fixed_region配置无效')
    for key in ('x_ratio','y_ratio'):
        v=fixed[key]
        if type(v) not in (int,float) or not math.isfinite(v) or not .02<=v<=.98:raise ValueError('attention固定区域比例无效')
    return config


class DailyTasks:
    def __init__(self,config,observe,computer,progress=print,should_yield=lambda:False,clock=time.monotonic,*,selected_tasks=None,record_rewards=False,redispatch_holowork=True,on_event=None,reward_reader=None,unknown_notification_policy=None,discover=None):
        self.config=validate_config(config);self.observe=observe;self.computer=computer
        self.progress=progress;self.should_yield=should_yield;self.clock=clock
        self.items={};self.report=None
        self.selected_tasks=tuple(NOTICES if selected_tasks is None else selected_tasks)
        if any(n not in NOTICES for n in self.selected_tasks): raise ValueError('通知分支含未知任务')
        self.redispatch_holowork=redispatch_holowork
        self.on_event=on_event;self.current_task=None
        self.observation_phase='notifications'
        self.reward_recorder=RewardRecorder(record_rewards,reward_reader,on_event)
        self.unknown_notification_policy=unknown_notification_policy or config.get('unknown_notification_policy','ignore_run')
        if self.unknown_notification_policy not in ('ignore_run','stop'):raise ValueError('未知通知策略无效')
        self.notification_run_result=None
        self.discover_callback=discover

    def emit(self,event,**data):
        if self.on_event:self.on_event(event,**data)

    def check(self):
        if getattr(self.computer,'stopped',False): raise RuntimeError('用户停止每日任务')
        if self.should_yield(): raise RuntimeError('收到人工引导，释放每日任务控制权')

    def capture(self,recovery=False):
        self.check();r=self.discover_callback() if recovery and self.discover_callback else self.observe();self.check()
        assert_window(r,
            unavailable_message='游戏不在前台，暂停每日任务；请切回游戏后重新运行',
            obscured_message='游戏被其他窗口遮挡')
        self.report=r
        ui=classify(r)
        self.emit('observation',task=self.current_task,ui_state=ui.to_dict(),report=r.to_dict())
        reward=ui.state==UIState.REWARD or self.target('daily_rewards_get',r) is not None
        self.reward_recorder.observe(r,reward,self.current_task)
        return r

    def send(self,name,**arguments):
        send_action(self.computer,name,arguments,check=self.check,emit=self.emit,
                    context={'task':self.current_task})

    def wait(self,seconds): self.send('wait',duration=seconds)

    def transition(self,*,resolve,source,completed,mode='navigation',recover=None,discover=None):
        discovery=discover or ((lambda:self.capture(recovery=True)) if self.discover_callback else None)
        return transition(observe=self.capture,send=self.click,resolve=resolve,source=source,
            completed=completed,wait=self.wait,check=self.check,clock=self.clock,
            policy=InteractionPolicy(timeout=self.config['transition_timeout_seconds'],mode=mode),
            recover=recover,discover=discovery,emit=self.emit)

    def recover_popup(self,report):
        if not hasattr(self,'_popup_recovery'):
            from modular_agent.domains.hololive_dreams.claim_tasks import ClaimTasks
            self._popup_recovery=ClaimTasks(self)
        return self._popup_recovery.recover(report)

    def target(self,label,r=None):
        r=r or self.report
        matches=[m for m in r.knowledge_matches if m.get('label') in (label,label+'_sample') and m.get('similarity',0)>=self.config.get('template_threshold',.6)]
        if label=='daily_back':
            frame=r.frame['bounds']
            matches=[m for m in matches if
                m['bounds']['x']+m['bounds']['width']/2>=frame['x']+frame['width']*.75 and
                frame['y']<=m['bounds']['y']+m['bounds']['height']/2<=frame['y']+frame['height']*.25]
        return max(matches,key=lambda m:m['similarity']) if matches else None

    def click(self,target):
        x,y=target_center(target,self.report.frame['bounds'])
        self.progress('每日点击：'+target['label'])
        self.send('click',x=x,y=y,modifiers=['alt'])

    def blank(self):
        b=self.report.frame['bounds']
        self.send('click',x=b['x']+round(b['width']*.90),y=b['y']+round(b['height']*.88),modifiers=['alt'])

    def attention_target(self,r):
        matched=self.target('attention',r)
        if matched:return matched
        fixed=self.config.get('attention_fixed_region',{'enabled':True,'x_ratio':.205,'y_ratio':.125})
        if not fixed['enabled'] or not self.free(r,allow_interaction=True):return None
        b=r.frame['bounds']
        if b['width']<800 or not 1.4<=b['width']/max(1,b['height'])<=2.0:return None
        x=b['x']+round(b['width']*fixed['x_ratio']);y=b['y']+round(b['height']*fixed['y_ratio'])
        target={'label':'attention_fixed_region','source':'configured_region',
                'bounds':{'x':x-12,'y':y-12,'width':24,'height':24}}
        self.emit('fixed_region_fallback',target=target,verification='click_then_confirm_notification_panel')
        return target

    def free(self,r,allow_interaction=False):
        labels={m.get('label') for m in r.knowledge_matches if m.get('similarity',0)>=self.config.get('template_threshold',.6)}
        # A generic back arrow can match world geometry; it is not page evidence.
        labels.discard('daily_back')
        # Daily pages/reward/interaction take priority over HUD visible behind an overlay.
        if allow_interaction: labels-={'daily_gift_interact','daily_wheel_interact'}
        ui=classify(r)
        if ui.state in (UIState.REWARD,UIState.RANK_UP,UIState.DIALOGUE,UIState.OPTIONS,UIState.MAP,UIState.LOCATION_DETAIL,UIState.ERROR,UIState.LOADING):return False
        ready=ui.state==UIState.WORLD or (allow_interaction and ui.state==UIState.INTERACTION)
        return ready and not any(n.startswith('daily_') for n in labels)

    def until_free(self,click=False,allow_interaction=False,require_transition=False):
        self.progress('每日状态：等待自由界面'+('，点击推进' if click else ''))
        start=self.clock();stable=0;probes=0;last_probe=start;transition_seen=not require_transition
        from modular_agent.domains.hololive_dreams.scratch_ticket import ScratchTicket
        scratch=ScratchTicket()
        while self.clock()-start<self.config['transition_timeout_seconds']:
            r=self.capture()
            if not click and getattr(self,'active_gift',None) and (self.target('entry_lever_interact',r) or any(''.join(t.get('text','').split())=='切换操纵杆' for t in r.texts)):
                self.recover_transfer(self.active_gift,r);stable=0;continue
            candidate=self.free(r,allow_interaction)
            if not candidate:transition_seen=True
            stable=stable+1 if candidate and transition_seen else 0
            if stable>=3: return
            if not stable and click:
                ui=classify(r)
                if ui.state==UIState.ERROR:raise RuntimeError('收尾出现错误/确认弹窗，停止推进')
                if getattr(self,'active_gift',None)=='wheel' or self.current_task=='wheel':
                    if scratch.update(r,self.click,self.clock(),self.emit):
                        self.wait(self.config['click_interval_seconds']);continue
                if ui.state==UIState.DIALOGUE:self.send('press',key='e',duration=.08)
                elif ui.state in (UIState.REWARD,UIState.RANK_UP):self.blank()
                elif ui.state==UIState.UNKNOWN and probes<2 and self.clock()-last_probe>=2:
                    if self.discover_callback:
                        self.emit('popup_discovery',task=self.current_task)
                        self.recover_popup(self.capture(recovery=True))
                    else:
                        self.emit('bounded_blank_probe',task=self.current_task)
                        self.blank()
                    probes+=1;last_probe=self.clock()
            self.wait(self.config['click_interval_seconds'])
        raise RuntimeError('未确认回到自由界面，停止推进')

    def holowork(self):
        self.observation_phase='holowork'
        index=0;last_click=-100.;attempts=0;start=self.clock();reward_pending=False;reward_attempts=0;reward_last=-100.
        while index<len(WORK):
            r=self.capture()
            # GET is an overlay, not a button. Keep handling it until a new
            # observation confirms it closed, even if the flow expected setup.
            if classify(r).state in (UIState.REWARD,UIState.RANK_UP) or self.target('daily_rewards_get',r):
                if not reward_pending:start=self.clock();reward_attempts=0
                reward_pending=True
                if self.clock()-reward_last>=2:
                    if reward_attempts>=3:raise RuntimeError('Holowork奖励层点击空白三次仍未关闭')
                    self.blank();reward_last=self.clock();reward_attempts+=1
                if self.clock()-start>self.config['transition_timeout_seconds']:raise RuntimeError('Holowork奖励层关闭超时')
                self.wait(self.config['click_interval_seconds']);continue
            if reward_pending:
                index=max(index,3);reward_pending=False;attempts=0;start=self.clock()
            if not self.redispatch_holowork and (index>=3 or self.target('daily_work_setup_all',r) or self.target('daily_work_recommend',r)):
                back=self.target('daily_back',r)
                if back:self.click(back)
                else:self.send('press',key='escape',duration=.08)
                self.until_free();return
            # A later page can advance the chain directly; never replay an earlier step.
            candidates=[(i,self.target(label,r)) for i,label in enumerate(WORK) if i>=index]
            candidates=[(i,t) for i,t in candidates if t and not (i==1 and self.target('daily_work_recommend',r)) and (i!=6 or ((index==6 or (index==5 and attempts>0)) and not self.target('daily_work_decide',r) and not self.target('daily_work_recommend',r)))]
            if candidates:
                i,t=min(candidates,key=lambda p:p[0])
                if i>index: index=i;attempts=0;start=self.clock()
                if attempts==0 or self.clock()-last_click>=2:
                    if attempts>=3: raise RuntimeError('Holowork按钮重复三次仍未推进：'+WORK[index])
                    self.click(t);last_click=self.clock();attempts+=1
                    # GET close and recommendation deliberately advance only after dispatch.
                    if index==4: index+=1;attempts=0;start=self.clock()
                # All other states advance only when the next button appears.
            elif index==6 and self.free(r):
                self.until_free();return
            if self.clock()-start>self.config['transition_timeout_seconds']:
                raise RuntimeError('Holowork等待超时：'+WORK[index])
            self.wait(self.config['click_interval_seconds'])

    def gift(self,name):
        self.active_gift=name
        self.observation_phase='gift'
        self.wait(self.config['teleport_wait_seconds'])
        label='daily_wheel_interact' if name=='wheel' else 'daily_gift_interact'
        # Require a free arrival scene before walking, never move during a loading page.
        self.until_free(allow_interaction=True)
        if name=='holo_home':
            for segment in self.config['holo_home_route']:
                self.capture()
                if self.target(label) or (name!='wheel' and self.report.frame.get('world_features',{}).get('gift_prompt')): break
                self.send('press',key=segment['key'],duration=segment['seconds'])
        walked=0;unknown_since=None
        while True:
            r=self.capture();t=self.target(label,r)
            features=r.frame.get('world_features',{})
            generic_gift=features.get('wheel_prompt') if name=='wheel' else features.get('gift_prompt')
            if t or generic_gift:
                if name=='wheel' or generic_gift: self.send('press',key='e',duration=.08)
                else: self.click(t)
                self.wait(.5);self.until_free(click=True,allow_interaction=True,require_transition=True);self.active_gift=None;return
            if walked>=self.config['nearby_walk_max_seconds']: raise RuntimeError('未找到礼物/转盘交互，请调整移动路线：'+name)
            if not self.free(r,allow_interaction=True):
                if classify(r).state==UIState.ERROR:raise RuntimeError('移动途中出现错误弹窗')
                if unknown_since is None:unknown_since=self.clock()
                if self.clock()-unknown_since>=self.config['transition_timeout_seconds']:raise RuntimeError('移动过程中等待界面恢复超时')
                self.wait(self.config['click_interval_seconds']);continue
            unknown_since=None
            step=min(self.config['nearby_walk_step_seconds'],self.config['nearby_walk_max_seconds']-walked)
            self.send('press',key='w',duration=step);walked+=step

    def recover_transfer(self,name,r=None):
        """A notice teleport can land at the area lever instead of its destination."""
        from modular_agent.domains.hololive_dreams.entry_flow import GreedCardsEntry
        from modular_agent.domains.hololive_dreams.interaction import RetryBudget,policy_for
        r=r or self.capture()
        def lever(frame):
            return self.target('entry_lever_interact',frame) is not None or any(
                ''.join(t.get('text','').split())=='切换操纵杆' for t in frame.texts)
        for replay in range(2):
            if not lever(r):return
            self.emit('transfer_interrupted',task=name,replay=replay+1)
            flow=GreedCardsEntry();budgets={};start=self.clock();chosen=False;stable=0
            while self.clock()-start<self.config['transition_timeout_seconds']:
                decision=flow.decide(r);state=decision['state']
                if state in ('lever_interact','dialogue','switch_casino','keep_casino'):
                    budget=budgets.setdefault(state,RetryBudget(policy_for('world_navigation')))
                    if budget.ready(self.clock()):
                        if decision['action']=='click':self.click(decision['target'])
                        else:self.send('press',key=decision['key'],duration=decision['duration'])
                        budget.sent(self.clock());flow.committed(decision)
                        chosen=chosen or state in ('switch_casino','keep_casino')
                    stable=0
                elif chosen and self.free(r,allow_interaction=True) and not lever(r):
                    stable+=1
                    if stable>=2:break
                else:stable=0
                self.wait(.3)
                r=self.capture(recovery=self.discover_callback is not None)
            else:raise RuntimeError('切换场地未确认完成，停止重放移动')
            # Re-resolve the original notification; never reuse its old screen coordinate.
            self.transition(resolve=self.attention_target,source=lambda f:self.free(f,True),
                completed=lambda f:self.target('daily_notice_'+name,f) is not None)
            self.click(self.target('daily_notice_'+name));self.wait(self.config['teleport_wait_seconds'])
            r=self.capture()
        if lever(r):raise RuntimeError('切换场地后移动仍到达操纵杆，停止重复传送')

    def notifications(self):
        if not self.computer.live: return {'outcome':'unknown','verified':False,'message':'模拟模式不会操作；请使用--live'}
        if self.notification_run_result is not None:return self.notification_run_result
        if not self.selected_tasks:return {'outcome':'success','verified':True,'items':{},'message':'未选择通知任务，未操作游戏'}
        try:
            self.until_free(allow_interaction=True)
            while True:
                self.observation_phase='notifications'
                if all(n in self.items for n in self.selected_tasks):
                    return {'outcome':'success','verified':True,'items':self.items,'message':'所选通知任务本轮均已处理；不代表全部通知清空'}
                r=self.capture();attention=self.attention_target(r)
                if not attention: raise RuntimeError('没有定位到attention通知入口')
                self.click(attention);self.wait(.5)
                # Absence of a match does not prove an empty notification list.
                # Opening animation and scene changes routinely outlast 0.5s.
                opened=self.clock();first_page=None;panel_stable=0;last_rows=None
                while self.clock()-opened<min(8,self.config['transition_timeout_seconds']):
                    page_report=self.capture()
                    if any(self.target('daily_notice_'+n,page_report) for n in NOTICES):
                        first_page=page_report;break
                    features=page_report.frame.get('world_features',{})
                    rows=features.get('notification_rows')
                    confirmed=features.get('notification_panel') and type(rows) is int and rows>=0
                    panel_stable=panel_stable+1 if confirmed and rows==last_rows and self.clock()-opened>=2 else 0
                    last_rows=rows
                    if panel_stable>=2:
                        first_page=page_report
                        self.emit('notification_panel_confirmed',rows=rows,evidence='panel_title_stable_row_count')
                        break
                    if classify(page_report).state==UIState.ERROR:raise RuntimeError('打开通知时出现错误弹窗')
                    self.wait(self.config['click_interval_seconds'])
                if first_page is None:
                    raise RuntimeError('通知打开后未识别到条目，不能证明通知已清空；暂停后续玩法')
                selected=None
                unhandled_rows=False
                for page in range(self.config['notification_scroll_pages']):
                    r=first_page if page==0 else self.capture()
                    selected=next(((n,self.target('daily_notice_'+n,r)) for n in self.selected_tasks
                                   if n not in self.items and self.target('daily_notice_'+n,r)),None)
                    if selected: break
                    features=r.frame.get('world_features',{})
                    known=any(self.target('daily_notice_'+n,r) for n in NOTICES)
                    if known:unhandled_rows=True
                    panel=features.get('notification_panel')
                    rows=features.get('notification_rows')
                    if panel and type(rows) is int and rows>0:unhandled_rows=True
                    # Unknown rows are scrollable only on a confirmed notification panel.
                    if not known and not (panel and type(rows) is int and rows>0):break
                    if page+1<self.config['notification_scroll_pages']:
                        b=r.frame['bounds'];self.send('move_to',x=b['x']+b['width']//5,y=b['y']+b['height']//2,modifiers=['alt'])
                        self.send('scroll',ticks=-3,modifiers=['alt']);self.wait(.4)
                if selected is None:
                    if unhandled_rows and self.unknown_notification_policy=='stop':
                        raise RuntimeError('剩余通知没有本次可执行处理器，按stop策略暂停')
                    self.blank();self.wait(.4);self.until_free(allow_interaction=True)
                    for n in self.selected_tasks:
                        self.items.setdefault(n,{'outcome':'skipped','verified':False,'reason':'本轮扫描未发现可处理通知，未证明已完成'})
                    result={'outcome':'success','verified':False,'items':self.items,
                            'stage_complete':True,'completion_basis':'bounded_scan_policy',
                            'badge_ignored':unhandled_rows,'ignore_scope':'run' if unhandled_rows else None,
                            'rewards_verified':False,
                            'message':'通知阶段完成；剩余未处理通知及其感叹号本次忽略，下次重新检查。' if unhandled_rows else '本轮通知扫描结束，未证明奖励已全部领取。'}
                    self.emit('notification_stage_finished',result=result)
                    self.progress(result['message'])
                    self.notification_run_result=result
                    return result
                name,t=selected;self.current_task=name
                self.emit('task_started',task=name)
                self.click(t);self.progress('每日分支：'+name)
                if name=='holowork': self.holowork()
                else: self.gift(name)
                self.items[name]={'outcome':'success','verification':'interaction_then_free_ui',
                                  'rewards_verified':False}
                self.emit('task_finished',task=name,result=self.items[name])
                self.current_task=None
                # Reopen a fresh list. Same item is never dispatched twice in this run.
        except (RuntimeError,ValueError) as error:
            if self.current_task:self.items[self.current_task]={'outcome':'unknown','verified':False,'message':str(error)}
            return {'outcome':'unknown','verified':False,'items':self.items,'message':str(error)}
        finally: self.computer.release_all()
