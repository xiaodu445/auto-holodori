"""Version 1.0.1: deterministic, local-only navigation into High&Low.
Source: successful log agent-20261002-113650-459247.log and user route.
No cloud model, historical coordinates or card/betting automation.
"""
import time
from modular_agent.core import Action, Outcome
from modular_agent.domains.hololive_dreams.states import classify, UIState
from .entry_contract import EXPECTED

VERSION='1.2.0'


def normalize(text):
    return ''.join(text.split()).lower().replace('＆','&')


class GreedCardsEntry:
    def __init__(self):
        self.moved=False
        self.dialogue_started=False
        self.walks=0
        self.dialogue_advances=0
        self.switching=False
        self.switch_arrived=False
        self.last_state='initial'
        self.saw_dialogue=False
        self.area_selected=False
        self.zoom_attempts=0
        self.pan_attempts=0

    def decide(self, report):
        ui=classify(report)
        if ui.state==UIState.ERROR:
            return {'state':'blocked','outcome':'unknown','message':'错误或确认弹窗需要处理，入口模块不继续发送导航输入。'}
        if ui.state in (UIState.REWARD,UIState.RANK_UP):
            return {'state':'overlay','outcome':'unknown','message':'奖励展示覆盖当前场景，需展示层模块处理。'}
        texts=report.texts
        values=[normalize(t.get('text','')) for t in texts]
        def has(value): return any(normalize(value) in t for t in values)
        def text(value):
            needle=normalize(value)
            # Exact or punctuation-prefixed labels, never long descriptive paragraphs.
            return next((t for t in texts if normalize(t.get('text','')).strip('/／vy✓×。.!！')==needle),None)
        def match(label):
            return sorted((m for m in report.knowledge_matches if m.get('label')==label),key=lambda m:m.get('similarity',0),reverse=True)
        def click(state,target): return {'state':state,'action':'click','target':target}
        def missing(state,message): return {'state':state,'outcome':'unknown','message':message}
        hud=ui.state in (UIState.WORLD,UIState.INTERACTION)
        is_map=ui.state in (UIState.MAP,UIState.LOCATION_DETAIL) or (has('MAP') and (has('协律花园') or has('电玩巨蛋城') or bool(match('map1') or match('map2'))))
        actual_game=not is_map and has('High&Low') and (
            (has('押注额') and has('押注并开始游戏') and has('两对以上'))
            or (has('请选择要留下的卡片') and has('替换')))
        ready_templates=bool(match('entry_ready_logo') and match('entry_ready_start'))
        if actual_game or (not is_map and ready_templates):
            return {'state':'high_low_game','outcome':'success','message':'已确认实际 High&Low 小游戏界面；入口导航完成，未下注。'}
        if has('Cruising') or has('移动中'):
            return {'state':'transit','action':'wait','duration':1}
        # Overlay evidence precedes the HUD still visible behind it.
        if not is_map and has('切换为赌场区'):
            target=text('切换为赌场区')
            return click('switch_casino',target) if target else missing('switch_options','未定位到切换为赌场区选项。')
        if not is_map and has('切换为游戏区'):
            target=text('不进行更改')
            return click('keep_casino',target) if target else missing('switch_options','当前已是赌场，但未定位到不进行更改。')
        if not is_map and text('切换操纵杆'):
            return {'state':'lever_interact','action':'press','key':'e','duration':.08}
        if not is_map and ui.state==UIState.DIALOGUE:
            limit=8 if report.frame.get('world_features',{}).get('dialogue') else 2
            if self.dialogue_advances>=limit: return missing('dialogue','对话推进仍无反馈，等待界面变化。')
            return {'state':'dialogue','action':'press','key':'e','duration':.08}
        if is_map:
            if has('协律花园') or has('汽水泡泡海湾'):
                candidates=match('map2')
                return click('select_arcade',candidates[0]) if candidates else missing('map_other','未识别到电玩巨蛋城切换入口 map2。')
            if not has('电玩巨蛋城') and not has('强欲之牌') and not has('切换操纵杆'):
                return missing('map_other','当前地图名称不明确；不猜测地图。')
            right_details=has('强欲之牌') and (has('猜高低') or has('Shiori'))
            if right_details:
                target=text('移动')
                return click('teleport',target) if target else missing('target_detail','强欲之牌详情已出现，但未定位到“移动”文字。')
            if has('切换操纵杆') and has('更改游玩区域'):
                target=text('移动')
                return click('lever_teleport',target) if target else missing('lever_detail','操纵杆详情缺少移动按钮。')
            if has('满腹之旅') or has('WCollect'):
                return {'state':'wrong_detail','action':'press','key':'esc','duration':.08}
            if has('游戏场') and not has('赌场'):
                return missing('wrong_time','当前是游戏场；需经大厅切换操纵杆切换赌场区。')
            if has('游戏区') and not has('赌场区'):
                target=text('大厅')
                return click('select_lobby',target) if target else missing('wrong_time','需回大厅切换操纵杆，未定位到大厅。')
            if self.switching:
                candidates=match('time')
                if candidates: return click('select_lever',candidates[0])
            candidates=match('smallgame')
            if candidates:
                rightmost=max(candidates,key=lambda m:m['bounds']['x']+m['bounds']['width']/2)
                # Right-side target only; details on next frame verify the game name.
                # Map panning invalidates a window-half test. Selection is
                # provisional: only the target detail allows teleportation.
                return click('select_smallgame',rightmost)
            target=text('游玩区域')
            if target and not self.area_selected: return click('select_area',target)
            zoom=report.frame.get('world_features',{}).get('map_zoom')
            if zoom and self.zoom_attempts<2 and zoom['knob']['x']-zoom['minimum']['x']>8:
                return {'state':'map_zoom_out','action':'drag','start':zoom['knob'],'end':zoom['minimum']}
            if self.area_selected and zoom and self.pan_attempts<2:
                b=report.frame['bounds']
                dx=(-.18,.30)[self.pan_attempts]
                return {'state':'map_pan','action':'drag',
                        'start':{'x':b['x']+round(b['width']*.50),'y':b['y']+round(b['height']*.48)},
                        'end':{'x':b['x']+round(b['width']*(.50+dx)),'y':b['y']+round(b['height']*.65)}}
            if self.area_selected:
                return missing('map_target_missing','地图视野整理后仍未找到小游戏图标，需检查区域或模板。')
            return click('select_area',target) if target else missing('map_arcade','未定位到游玩区域或目标小游戏图标。')
        if hud:
            if self.switch_arrived:
                return {'state':'open_map_after_switch','action':'press','key':'m','duration':.08}
            target=text('猜高低')
            if target:
                if self.dialogue_started:
                    if self.saw_dialogue:
                        return {'state':'reinteract','action':'press','key':'e','duration':.08}
                    return {'state':'await_game','action':'wait','duration':1}
                return {'state':'interact','action':'press','key':'e','duration':.08}
            # Resume directly from the known Shiori entry-dialogue as well.
            if self.dialogue_started:
                return {'state':'await_game','action':'wait','duration':1}
            if self.switching:
                return {'state':'await_lever','action':'wait','duration':1}
            if self.moved:
                if self.walks>=2: return missing('arrived','两次短按 W 后仍无猜高低入口，需确认位置。')
                return {'state':'arrived','action':'press','key':'w','duration':.3}
            return {'state':'free_main','action':'press','key':'m','duration':.08}
        return missing('unrecognized','当前画面不属于已知入口流程，需要人工或顶层 Agent 处理。')

    def committed(self, decision):
        self.last_state=decision['state']
        if decision['state']=='select_area': self.area_selected=True
        if decision['state']=='map_zoom_out': self.zoom_attempts+=1
        if decision['state']=='map_pan': self.pan_attempts+=1
        if decision['state'] in ('select_lobby','select_lever','lever_teleport','lever_interact'): self.switching=True
        if decision['state'] in ('switch_casino','keep_casino'):
            self.switching=False
            self.switch_arrived=True
        if decision['state']=='open_map_after_switch': self.switch_arrived=False
        if decision['state']=='teleport': self.moved=True
        if decision['state']=='interact': self.dialogue_started=True
        if decision['state']=='reinteract': self.saw_dialogue=False
        if decision['state']=='arrived': self.walks+=1
        if decision['state']=='dialogue':
            self.dialogue_advances+=1
            self.saw_dialogue=True

    def run(self, observe, computer, progress=lambda message:None, **options):
        try:
            result=self._run(observe,computer,progress,**options)
        except Exception as error:
            trace=getattr(self,'trace',None)
            if trace: trace.write('exception',type=type(error).__name__,message=str(error))
            raise
        trace=getattr(self,'trace',None)
        if trace:
            result={**result,'trace_directory':str(trace.directory)}
            trace.result(result)
        return result

    def _run(self, observe, computer, progress=lambda message:None, *, timeout=300, transition_timeout=30, clock=time.monotonic, should_yield=lambda:False):
        if not computer.live:
            return {'outcome':'unknown','verified':False,'message':'模拟模式不操作；使用 --live 或直接 decide(report) 检查决策。'}
        started=clock(); attempts={}; pending_since=None; pending_state=None
        try:
            while clock()-started<timeout:
                if getattr(computer,'stopped',False): return {'outcome':'failure','verified':False,'message':'用户停止本地组件。'}
                if should_yield(): return {'outcome':'unknown','verified':False,'message':'收到人工引导，本地组件释放控制权，由顶层重新规划。','handoff':'human_guidance'}
                report=observe()
                if getattr(computer,'stopped',False): return {'outcome':'failure','verified':False,'message':'用户停止本地组件。'}
                if should_yield(): return {'outcome':'unknown','verified':False,'message':'收到人工引导，丢弃未执行的本地决策。','handoff':'human_guidance'}
                decision=self.decide(report)
                ui=classify(report)
                decision={**decision,'ui_state':ui.state.value,'flow_step':decision['state'],
                          'expected_ui_states':[s.value for s in EXPECTED.get(decision['state'],())]}
                trace=getattr(self,'trace',None)
                if trace: trace.decision(decision,ui)
                progress('界面状态：'+ui.state.value+'；入口步骤：'+decision['state'])
                if decision.get('outcome')=='success':
                    return {**decision,'verified':True,'verification':'local_ui_rule','model_version':VERSION,
                            'module':'greed_cards_entry','next_module':'greed_cards_play'}
                state=decision['state']
                if state!=pending_state and not decision.get('outcome') and decision.get('action')!='wait':
                    pending_since=clock();pending_state=state
                if pending_since is None: pending_since=clock()
                if clock()-pending_since>=transition_timeout:
                    return {'outcome':'unknown','verified':False,'state':state,'module':'greed_cards_entry',
                            'message':'等待页面推进超时；最后动作：'+str(pending_state)+'；当前：'+state}
                if decision.get('outcome')=='unknown':
                    actions=[Action('wait',arguments={'duration':1})]
                else:
                    state=decision['state']
                    # Semantic state, not animated pixel signatures, controls retries.
                    attempts[state]=attempts.get(state,0)+1
                    from .interaction import policy_for
                    if decision['action']!='wait' and attempts[state]>policy_for('world_navigation').max_attempts:
                        return {'outcome':'unknown','verified':False,'message':'状态 '+state+' 重试三次仍未推进，交回人工或顶层 Agent。'}
                    game=next((w for w in report.windows if w.get('handle')==report.frame.get('target_window_handle')),None)
                    if game is None: return {'outcome':'unknown','verified':False,'message':'缺少目标游戏窗口，拒绝发送输入。'}
                    if game.get('minimized') or not game.get('foreground') or report.frame.get('masked_agent_regions'):
                        return {'outcome':'unknown','verified':False,'message':'游戏不在前台或被遮挡，暂停入口模块。'}
                    actions=[Action('focus',arguments={'handle':game['handle']})]
                    if decision['action']=='click':
                        b=decision['target']['bounds']
                        frame=report.frame['bounds']
                        x=b['x']+b['width']//2;y=b['y']+b['height']//2
                        if not frame['x']<=x<frame['x']+frame['width'] or not frame['y']<=y<frame['y']+frame['height']:
                            return {'outcome':'unknown','verified':False,'message':'点击目标超出当前游戏窗口。'}
                        actions.append(Action('click',arguments={'x':b['x']+b['width']//2,'y':b['y']+b['height']//2,'modifiers':['alt']}))
                    elif decision['action']=='drag':
                        frame=report.frame['bounds']
                        for point in (decision['start'],decision['end']):
                            if not (frame['x']<=point['x']<frame['x']+frame['width'] and frame['y']<=point['y']<frame['y']+frame['height']):
                                return {'outcome':'unknown','verified':False,'message':'地图拖动超出当前窗口边界。'}
                        actions.append(Action('move_to',arguments={**decision['start'],'modifiers':['alt']}))
                        actions.append(Action('drag',arguments={**decision['end'],'duration':.5,'steps':25,'modifiers':['alt']}))
                    elif decision['action']=='press':
                        actions.append(Action('press',arguments={'key':decision['key'],'duration':decision['duration']}))
                    else: actions.append(Action('wait',arguments={'duration':decision['duration']}))
                    actions.append(Action('wait',arguments={'duration':1}))
                results=computer.run_actions(actions)
                if trace:
                    trace.write('input',actions=[{'name':a.name,'arguments':a.arguments} for a in actions],
                                results=[{'outcome':r.outcome.value,'message':r.message} for r in results])
                if not all(r.outcome==Outcome.SUCCESS for r in results):
                    return {'outcome':'failure','verified':False,'message':'本地输入失败。'}
                if not decision.get('outcome'): self.committed(decision)
            return {'outcome':'unknown','verified':False,'message':'本地入口导航超时。'}
        finally: computer.release_all()
