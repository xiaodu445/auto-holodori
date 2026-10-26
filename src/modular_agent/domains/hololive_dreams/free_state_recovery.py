"""Bounded return from recognized menus to free world, without claiming/starting.

This adapter uses the common transition runner with explicit acknowledgement
states. Reward acknowledgement is navigation here, not a repeated claim action.
Unknown pages, active minigames and spending/matching confirmation are blocked.
"""
from __future__ import annotations

import time
from types import SimpleNamespace
from modular_agent.agent.interaction import TransitionState, assert_window, transition
from modular_agent.agent.ui_actions import send_action, target_center
from .interaction import policy_for, text_button
from .states import classify, UIState

PAGE_LABELS = {'claim_pass_page','claim_achievement_page','claim_event_carousel',
               'claim_event_page','claim_event_home',
               'daily_work_claim_all','daily_work_claim_summary','daily_work_setup_all',
               'daily_work_recommend','daily_work_decide'}
FORBIDDEN = ('确认购买','购买确认','确认兑换','确认删除','确认成员','决定成员','匹配中','等待成员',
             '押注并开始游戏','High&Low','猜高','猜低')


def current_labels(report):
    return {m.get('label') for m in report.knowledge_matches
            if m.get('similarity',0) >= max(.92 if m.get('label','').startswith('claim_') else .85,m.get('threshold',.85))}


def recovery_state(report):
    """More specific page/overlay evidence must win over HUD behind that page."""
    ui = classify(report).state
    words = [''.join(t.get('text','').split()) for t in report.texts]
    if ui == UIState.ERROR or any(token in word for token in FORBIDDEN for word in words):
        return 'blocked'
    if ui in (UIState.GREED_READY,UIState.GREED_PLAY,UIState.OPTIONS,UIState.DIALOGUE,UIState.SCRATCH_TICKET):
        return 'unsupported'
    if ui == UIState.LOADING: return 'loading'
    if ui in (UIState.REWARD,UIState.RANK_UP): return 'acknowledgement'
    if report.frame.get('confirmed_popup'): return 'registered_popup'
    labels = current_labels(report)
    if any(label.startswith(('kitchen_','rhythm_','jump_rope_','fishing_','entry_ready_')) for label in labels):
        return 'unsupported'
    if ui in (UIState.MAP,UIState.LOCATION_DETAIL): return 'map'
    if ui == UIState.NOTIFICATION or any(n.startswith('daily_notice_') for n in labels): return 'notifications'
    if labels & PAGE_LABELS or ui in (UIState.ACHIEVEMENT_LIST,UIState.ACHIEVEMENT_DETAIL): return 'menu'
    if ui in (UIState.WORLD,UIState.INTERACTION) and not any(n.startswith('daily_') and n not in
            ('daily_back','daily_gift_interact','daily_wheel_interact') for n in labels):
        return 'free'
    return 'unknown'


def check_window(report):
    assert_window(report)
    game=next(w for w in report.windows if w.get('handle')==report.frame.get('target_window_handle'))
    bounds=game.get('bounds',report.frame['bounds'])
    for window in report.windows:
        if window.get('handle')==game['handle'] or window.get('minimized'):continue
        if window.get('z_order',float('inf'))>=game.get('z_order',0):continue
        other=window.get('bounds',{})
        if all(k in other and k in bounds for k in ('x','y','width','height')) and (
                max(other['x'],bounds['x']) < min(other['x']+other['width'],bounds['x']+bounds['width']) and
                max(other['y'],bounds['y']) < min(other['y']+other['height'],bounds['y']+bounds['height'])):
            raise RuntimeError('恢复停止：游戏被其他窗口遮挡')


def observed_state(report):
    ui=classify(report).state
    state=recovery_state(report)
    if state=='free':return 'world.free'
    if ui not in (UIState.WORLD,UIState.UNKNOWN):return ui.value
    return {'menu':'menu.recognized','registered_popup':'overlay.registered',
            'notifications':'overlay.notifications','acknowledgement':'overlay.acknowledgement'}.get(state,state)


class FreeStateRecovery:
    def __init__(self, observe, computer, *, cancelled=lambda:False, progress=print,
                 clock=time.monotonic, timeout=30,current_windows=None):
        self.observe,self.computer=observe,computer
        self.cancelled,self.progress,self.clock=cancelled,progress,clock
        self.timeout=timeout;self.report=None;self.inputs=0;self.events=[]
        self.current_windows=current_windows
        self.last_frame_time=None;self.samples=[]
        self.input_delivery_unknown=False

    def check(self):
        if self.cancelled() or getattr(self.computer,'stopped',False):raise RuntimeError('恢复已取消')

    def capture(self):
        self.check();report=self.observe();self.check();check_window(report)
        self.report=report
        stamp=report.frame.get('captured_at') or getattr(report,'observed_at',None)
        if not stamp or stamp==self.last_frame_time:raise RuntimeError('恢复观察缺少新鲜帧时间，拒绝用重复旧帧确认状态')
        self.last_frame_time=stamp
        self.samples=(self.samples+[{'state':observed_state(report),'captured_at':stamp,
            'evidence':list(classify(report).evidence)}])[-3:]
        return report

    def emit(self,event,**data):
        self.events.append({'event':event,**data})

    def input_event(self,event,**data):
        self.emit(event,**data)
        if event=='input':
            if data.get('outcome')=='success':self.inputs+=1
            else:self.input_delivery_unknown=True

    def send(self,target):
        self.check();check_window(self.report)
        if self.current_windows:
            latest=list(self.current_windows())
            check_window(SimpleNamespace(frame=self.report.frame,windows=latest))
            handle=self.report.frame['target_window_handle']
            old=next(w for w in self.report.windows if w.get('handle')==handle)
            fresh=next(w for w in latest if w.get('handle')==handle)
            if old.get('bounds')!=fresh.get('bounds'):raise RuntimeError('恢复输入前窗口位置或尺寸改变')
        kind=target.get('recovery_action','click')
        if kind=='escape':
            send_action(self.computer,'press',{'key':'escape','duration':.08},check=self.check,emit=self.input_event)
        else:
            x,y=target_center(target,self.report.frame['bounds'])
            send_action(self.computer,'click',{'x':x,'y':y,'modifiers':['alt']},check=self.check,emit=self.input_event)

    def wait(self,seconds):
        send_action(self.computer,'wait',{'duration':seconds},check=self.check)

    def target(self,report):
        state=recovery_state(report)
        if state not in ('map','notifications','menu','acknowledgement','registered_popup'):return None
        if state=='registered_popup':
            return text_button(report,('确定','关闭'),known_page=True,zone=(.15,.15,.98,.98))
        if state=='acknowledgement':
            # Never click a menu close control visible behind this overlay.
            frame=report.frame['bounds']
            return {'label':'acknowledge_existing_overlay','bounds':{
                'x':frame['x']+round(frame['width']*.90),'y':frame['y']+round(frame['height']*.88),'width':1,'height':1}}
        # An explicit but disabled close control does not authorize another input.
        candidates=[]
        for match in report.knowledge_matches:
            if match.get('label') not in ('claim_close','daily_back') or match.get('similarity',0)<.92:continue
            frame=report.frame['bounds'];box=match['bounds']
            x=(box['x']+box['width']/2-frame['x'])/frame['width']
            y=(box['y']+box['height']/2-frame['y'])/frame['height']
            if .75<=x<=.995 and .02<=y<=.25:candidates.append(match)
        if candidates:
            target=max(candidates,key=lambda m:m['similarity'])
            return None if target.get('enabled') is False or target.get('claim_enabled') is False else target
        return {'label':'close_recognized_menu','recovery_action':'escape'}

    def run(self):
        def state_of(report):
            state=recovery_state(report)
            if state in ('blocked','unsupported'):return TransitionState.BLOCKED
            if state=='loading':return TransitionState.LOADING
            if state=='unknown':return TransitionState.UNKNOWN
            return TransitionState.READY
        try:
            self.progress('恢复界面：只退出已识别菜单，等待自由界面稳定。')
            transition(observe=self.capture,send=self.send,resolve=self.target,
                source=lambda r:recovery_state(r) not in ('free','unknown','blocked','unsupported','loading'),
                completed=lambda r:recovery_state(r)=='free',wait=self.wait,check=self.check,
                state_of=state_of,discover=self.capture,clock=self.clock,emit=self.emit,
                policy=policy_for('return_to_free',timeout=self.timeout,max_attempts=6,retry_interval=1,stable_frames=3))
            return {'outcome':'success','verified':True,'state':'world.free',
                    'verification':'three_fresh_free_world_observations','recovery_inputs':self.inputs,
                    'rewards_verified':False,'verification_samples':self.samples,
                    'input_delivery_unknown':self.input_delivery_unknown,'events':self.events}
        except (RuntimeError,ValueError) as error:
            return {'outcome':'cancelled' if self.cancelled() or getattr(self.computer,'stopped',False) else 'unknown',
                    'verified':False,'message':str(error),'observed_state':observed_state(self.report) if self.report else 'unobserved',
                    'recovery_inputs':self.inputs,'verification_samples':self.samples,
                    'input_delivery_unknown':self.input_delivery_unknown,'events':self.events}
        finally:self.computer.release_all()
