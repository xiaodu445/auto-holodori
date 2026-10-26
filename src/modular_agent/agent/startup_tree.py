"""Local hololive Dreams startup/login/reward dismissal, version 1.2.0."""
import time
from modular_agent.core import Action, Outcome
from modular_agent.domains.hololive_dreams.states import classify, UIState
from modular_agent.domains.hololive_dreams.interaction import text_button,policy_for

HUD=('活动','游戏','演出','任务','成就','扭蛋')

def normalized(value): return ''.join(value.split()).lower()

class StartupTree:
    def __init__(self, startup_grace=0, loading_timeout=120, post_input_grace=.3, max_center_attempts=800):
        self.ready_frames=0
        self.center_attempts=0
        self.max_center_attempts=max_center_attempts
        self.startup_grace=startup_grace
        self.loading_timeout=loading_timeout
        self.post_input_grace=post_input_grace

    def decide(self,report):
        ui=classify(report)
        if ui.state==UIState.SCRATCH_TICKET:
            from modular_agent.domains.hololive_dreams.scratch_ticket import target
            t=target(report)
            if t:return {'state':'scratch_ticket','action':'click','target':t,'post_input_grace':policy_for('scratch_ticket').retry_interval}
            return {'state':'needs_help','outcome':'unknown','message':'刮奖券已打开但缺少当前点击目标，不盲点。'}
        if report.frame.get('confirmed_popup'):
            target=text_button(report,('确定','继续','下一步','关闭'),known_page=True)
            if target:return {'state':'registered_popup','action':'click','target':target}
            return {'state':'needs_help','outcome':'unknown','message':'已知弹窗没有启用的安全文字按钮，不盲点空白。'}
        if ui.state in (UIState.ACHIEVEMENT_DETAIL,UIState.ACHIEVEMENT_LIST):
            return {'state':'close_achievement_detail','action':'back'}
        if ui.state in (UIState.DIALOGUE,UIState.MAP,UIState.LOCATION_DETAIL,UIState.INTERACTION,UIState.OPTIONS):
            return {'state':'needs_help','outcome':'unknown','message':'当前为地图导航或小游戏交互/对话，交给对应组件。'}
        if report.frame.get('startup_template_only'):
            # Only the current captured templates can end the no-OCR startup loop.
            threshold=.80 if self.ready_frames else .85
            found={m.get('label') for m in report.knowledge_matches if m.get('similarity',0)>=threshold}
            ready=(ui.state==UIState.WORLD if 'world_features' in report.frame else len({'menu','stage','task'} & found)>=2)
            self.ready_frames=self.ready_frames+1 if ready else 0
            if self.ready_frames>=2:
                return {'state':'free_main','outcome':'success','verified':True,
                    'verification':'startup_hud_template_rule','message':'连续两次命中至少两个主界面图标，启动点击已结束。'}
            if ready: return {'state':'confirm_hud','action':'wait','duration':.1}
            return {'state':'startup_probe','action':'center'}
        texts=report.texts
        values=[normalized(t.get('text','')) for t in texts]
        def has(word): return any(normalized(word) in v for v in values)
        def label(word): return next((t for t in texts if normalized(t.get('text','')).strip('。.!！/／')==normalized(word)),None)
        def unknown(message): return {'state':'needs_help','outcome':'unknown','message':message}
        if any(has(w) for w in ('连接失败','登录失败','维护中','验证码','购买确认','确认购买','删除账号')):
            return unknown('出现错误或需要人工处理的页面，不自动点击。')
        if has('High&Low') or has('押注并开始游戏'):
            return unknown('已经处于小游戏，启动树不操作或退出小游戏。')
        if has('MAP') and (has('协律花园') or has('电玩巨蛋城')):
            return unknown('当前已在地图导航界面，应交给对应导航组件。')
        reward=any(has(w) for w in ('每日奖励','每日登录','登录奖励','签到奖励','每日登入','获得奖励'))
        continuing=next((label(w) for w in ('继续','点击继续','点击屏幕继续','点击任意位置继续') if label(w)),None)
        ready=sum(has(w) for w in HUD)>=4
        if ready and not reward and continuing is None:
            return {'state':'free_main','outcome':'success','verified':True,'verification':'local_startup_ui_rule','message':'已确认自由主界面；启动登录流程结束，可进入小游戏导航。'}
        for w in ('加载中','下载中','更新中','连接中','正在加载','loading','connecting','downloading'):
            if has(w): return {'state':'loading','action':'wait','duration':1}
        title_start=next((t for t in texts if any(k in normalized(t.get('text','')) for k in ('taptostart','aptostart','touchtostart','点击开始'))),None)
        if title_start: return {'state':'title_start','action':'center'}
        if continuing: return {'state':'continue','action':'center'}
        for w in ('领取','领取奖励','进入游戏','开始游戏','登录'):
            target=label(w)
            if target: return {'state':'startup_button','action':'click','target':target}
        if reward or has('点击屏幕') or has('点击任意') or has('touch') or has('tap'):
            return {'state':'tap_screen','action':'center'}
        chrome={'最小化','最大化','关闭','系统','hololive-dreams','hololivedreams','×','x','口'}
        if not any(v not in chrome for v in values):
            return {'state':'startup_blank','action':'center'}
        if self.center_attempts>=self.max_center_attempts: return unknown('点击右下空白区后仍未识别自由主界面，需要顶层判断。')
        return {'state':'startup_probe','action':'center'}

    def run(self,observe,computer,progress=print,*,should_yield=lambda:False,timeout=240,clock=time.monotonic):
        if not computer.live: return {'outcome':'unknown','verified':False,'message':'模拟模式不执行登录操作。'}
        started=clock();attempts={}; waiting_since={}; unknown_since=None; cooldown_until=0; last_clicked_state=None
        try:
            # Do not inspect or click the first splash frame: let the game window settle first.
            if self.startup_grace>0:
                progress(f'启动窗口稳定等待：{self.startup_grace:.0f} 秒；随后固定点击右下角。')
                result=computer.perform(Action('wait',arguments={'duration':self.startup_grace}))
                if result.outcome!=Outcome.SUCCESS:
                    return {'outcome':'failure','verified':False,'message':'启动稳定等待失败。'}
            while clock()-started<timeout:
                if getattr(computer,'stopped',False): return {'outcome':'failure','verified':False,'message':'用户停止启动树。'}
                if should_yield(): return {'outcome':'unknown','verified':False,'message':'人工指示更新，启动树交回控制权。'}
                report=observe()
                if getattr(computer,'stopped',False): return {'outcome':'failure','verified':False,'message':'用户停止启动树。'}
                if should_yield(): return {'outcome':'unknown','verified':False,'message':'人工指示更新，取消未执行输入。'}
                game=next((w for w in report.windows if w.get('handle')==report.frame.get('target_window_handle')),None)
                if not game or game.get('minimized'): return {'outcome':'unknown','verified':False,'message':'游戏窗口不可见，停止登录操作。'}
                if report.frame.get('masked_agent_regions'): return {'outcome':'unknown','verified':False,'message':'游戏被 Agent 窗口遮挡，需先移开。'}
                decision=self.decide(report)
                now=clock()
                state=decision['state']
                if state in ('startup_probe','startup_blank'):
                    if unknown_since is None: unknown_since=now
                    if now-unknown_since<self.startup_grace:
                        decision={'state':'startup_settle','action':'wait','duration':2}
                        progress(f'启动过渡缓冲：{now-unknown_since:.0f}/{self.startup_grace:.0f} 秒；暂不点击或求助。')
                else: unknown_since=None
                if decision.get('action') in ('center','click') and now<cooldown_until:
                    decision={'state':'post_input_wait','action':'wait','duration':max(0,cooldown_until-now)}
                    progress('输入后等待界面切换，暂不重复点击。')
                progress('启动树状态：'+decision['state'])
                if not game.get('foreground'):
                    state='focus';decision={'action':'focus','state':state}
                else:
                    if decision.get('outcome'): return decision
                    if decision.get('action')=='center' and self.center_attempts>=self.max_center_attempts:
                        return {'outcome':'unknown','verified':False,'message':'右下空白区点击达到 '+str(self.max_center_attempts)+' 次仍未到主界面，交回顶层。'}
                    state=decision['state']
                attempts[state]=attempts.get(state,0)+1
                waiting=state in ('loading','startup_blank','startup_settle','post_input_wait','confirm_hud')
                if waiting:
                    waiting_since.setdefault(state,now)
                    # Loading is limited by elapsed time, not screenshot frequency.
                    if state in ('loading','startup_blank') and now-waiting_since[state]>=self.loading_timeout:
                        return {'outcome':'unknown','verified':False,'message':'加载/空白等待超过 '+str(self.loading_timeout)+' 秒，交回顶层。'}
                else:
                    waiting_since.clear()
                if not waiting and attempts[state]>(self.max_center_attempts if decision.get('action')=='center' else (12 if state=='focus' else policy_for('startup').max_attempts)):
                    return {'outcome':'unknown','verified':False,'message':'启动状态 '+state+' 多次未推进，交回顶层。'}
                actions=[]
                if decision['action']=='focus':
                    actions.extend([Action('focus',arguments={'handle':game['handle']}),Action('wait',arguments={'duration':.5})])
                elif decision['action']=='wait': actions.append(Action('wait',arguments={'duration':decision['duration']}))
                elif decision['action']=='back':
                    actions.extend([Action('press',arguments={'key':'escape','duration':.08}),Action('wait',arguments={'duration':.5})])
                else:
                    b=decision.get('target',{}).get('bounds',report.frame.get('bounds',{}))
                    if not b.get('width') or not b.get('height'): return {'outcome':'unknown','verified':False,'message':'缺少本次目标位置，拒绝点击。'}
                    x=b['x']+round(b['width']*.90) if decision['action']=='center' else b['x']+b['width']//2
                    y=b['y']+round(b['height']*.90) if decision['action']=='center' else b['y']+b['height']//2
                    actions.append(Action('click',arguments={'x':x,'y':y,'modifiers':['alt']}))
                    last_clicked_state=state
                    cooldown_until=clock()+decision.get('post_input_grace',self.post_input_grace)
                    if decision['action']=='center': self.center_attempts+=1
                if decision.get('action') in ('center','click'):
                    actions.append(Action('wait',arguments={'duration':decision.get('post_input_grace',self.post_input_grace)}))
                if not all(r.outcome==Outcome.SUCCESS for r in computer.run_actions(actions)):
                    return {'outcome':'failure','verified':False,'message':'启动树输入失败。'}
            return {'outcome':'unknown','verified':False,'message':'启动登录流程超时。'}
        finally: computer.release_all()
