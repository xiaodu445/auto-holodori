"""Load explicitly selected domain-local programs; no model-provider configuration."""
import importlib.util
import json
from pathlib import Path
from modular_agent.agent.general import GeneralAgent
from modular_agent.agent.launcher import GameLauncher
from modular_agent.computer import ActionComputer
from modular_agent.perception import GeneralVision


def load_greed_cards(root):
    path=Path(root)/'domains'/'hololive_dreams'/'models'/'greed_cards'/'greed_cards_entry.py'
    spec=importlib.util.spec_from_file_location('hololive_greed_cards_entry',path)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.GreedCardsEntry()


def run_greed_cards(root, *, live=False, progress=print):
    root=Path(root)
    profile=json.loads((root/'domains'/'hololive_dreams'/'launch.json').read_text(encoding='utf-8-sig'))
    from modular_agent.perception.template_import import import_game_templates
    import_game_templates(root,'hololive_dreams')
    tree=load_greed_cards(root)
    with ActionComputer(live=live,audit_path=root/'runtime'/'computer-actions.jsonl') as computer:
        with GeneralAgent(root,computer,None,domain='hololive_dreams') as adapter:
            if live:
                result=GameLauncher(adapter.vision,computer,profile).run('进入强欲之牌',progress)
                if not result.get('verified'): return result
                adapter.vision.warmup(progress)
                from modular_agent.agent.startup_tree import StartupTree
                result=StartupTree().run(lambda:adapter._observe_startup('hololive_dreams',progress),computer,progress)
                if result.get('outcome')!='success' and result.get('state')!='needs_help': return result
                if result.get('state')=='needs_help' and '地图导航' not in result.get('message','') and '小游戏' not in result.get('message',''): return result
            from modular_agent.agent.entry_observer import EntryObserver
            return tree.run(EntryObserver(adapter,tree,progress),computer,progress)


def run_startup(root, *, live=False, progress=print):
    root=Path(root)
    with ActionComputer(live=live,audit_path=root/'runtime'/'computer-actions.jsonl') as computer:
        with GeneralAgent(root,computer,None,domain='hololive_dreams') as adapter:
            return adapter._skill({'skill':'launch_game','domain':'hololive_dreams'},'启动 hololive Dreams',progress)


def load_greed_cards_play_module(root):
    path = Path(root)/'domains'/'hololive_dreams'/'models'/'greed_cards'/'greed_cards_play.py'
    spec = importlib.util.spec_from_file_location('hololive_greed_cards_play', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_greed_cards_play(root, *, live=False, progress=print, image=None,
                         daily_collected=None, stage=None, max_rounds=200, max_loss=10000):
    root = Path(root)
    module = load_greed_cards_play_module(root)
    profile = json.loads((root/'domains'/'hololive_dreams'/'launch.json').read_text(encoding='utf-8-sig'))
    from contextlib import closing
    with ActionComputer(live=live,audit_path=root/'runtime'/'computer-actions.jsonl') as computer:
        with closing(GeneralVision.for_project(root,'hololive_dreams')) as vision:
            observer = module.PlayObserver(root,vision,computer,profile)
            tree = module.GreedCardsPlay(**play_starting_policy(root,daily_collected,stage,max_rounds,max_loss))
            if not image:
                progress(f'恢复今日累计：{tree.daily}；策略阶段：{tree.stage+1}')
            if image:
                from modular_agent.perception.screen import load_image
                observation = observer.analyze(load_image(Path(image)))
                return {'decision':tree.decide(observation['report'],observation['cards'],observation['errors']),
                        'cards':observation['cards'], 'errors':observation['errors'],
                        'screen':observation['report'].to_dict(), 'missing_templates':observer.cards.missing()}
            if live:
                launcher=GameLauncher(vision,computer,profile)
                game=launcher._window(vision.desktop.windows())
                if not game:
                    return {'outcome':'unknown','verified':False,'message':'未找到已运行的游戏窗口，请先进入强欲之牌'}
                progress('聚焦游戏窗口，确认前台后开始小游戏。')
                try:
                    launcher._focus_verified(game)
                except RuntimeError as error:
                    return {'outcome':'unknown','verified':False,'message':str(error)}
            result = tree.run(observer,computer,progress,timeout=profile.get("local_models",{}).get("greed_cards_play",{}).get("timeout_seconds",1800))
            save_play_result(root,result)
            return result


def play_day():
    from datetime import datetime, timezone, timedelta
    return datetime.now(timezone(timedelta(hours=8))).date().isoformat()


def play_starting_policy(root, daily_collected=None, stage=None, max_rounds=200, max_loss=10000):
    path=Path(root)/'runtime'/'high-low'/'last-result.json'
    saved={}
    def valid(data):
        ledger=data.get('ledger',{}) if isinstance(data,dict) else {}
        return (data.get('day')==play_day() and type(ledger.get('daily_collected')) is int
                and ledger['daily_collected']>=0 and ledger.get('stage') in (0,1,2))
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        if valid(data): saved=data['ledger']
    except (OSError,ValueError,TypeError): pass
    if not saved:
        history=path.parent/'runs.jsonl'
        if history.exists():
            for line in reversed(history.read_text(encoding='utf-8').splitlines()):
                try:
                    data=json.loads(line)
                    if valid(data):
                        saved=data['ledger'];break
                except (ValueError,TypeError): continue
    # Same-day confirmed cashouts survive a new task. A new day starts at zero
    # per user instruction; unrelated/manual gameplay requires an explicit override.
    collected=saved.get('daily_collected',0) if daily_collected is None else daily_collected
    if type(collected) is not int or collected < 0:
        raise ValueError('今日已收取奖励必须是非负整数')
    if stage is None:
        if daily_collected is not None:
            # Manual cumulative override starts the corresponding standard
            # 12800 / 6400 / final cashout phase, rather than stale saved phase.
            stage=2 if collected > 18000 else 1 if collected >= 10000 else 0
        else:
            stage=2 if collected > 18000 else saved.get('stage',1 if collected >= 10000 else 0)
    return {'daily_collected':collected,'stage':stage,
            'max_rounds':max_rounds,'max_loss':max_loss}


def save_play_checkpoint(root, ledger):
    """Persist confirmed cashouts immediately, before waiting for next-round UI."""
    destination=Path(root)/'runtime'/'high-low'/'last-result.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    data={'day':play_day(),'outcome':'in_progress','ledger':ledger}
    temporary=destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(destination)


def save_play_result(root,result):
    destination=Path(root)/'runtime'/'high-low'/'last-result.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    data={**result,'day':play_day()}
    temporary=destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temporary.replace(destination)
    with (destination.parent/'runs.jsonl').open('a',encoding='utf-8') as history:
        from datetime import datetime, timezone
        history.write(json.dumps({'timestamp':datetime.now(timezone.utc).isoformat(),'day':data['day'],'outcome':result.get('outcome'),'message':result.get('message'),'elapsed_seconds':result.get('elapsed_seconds'),'ledger':result.get('ledger',{})},ensure_ascii=False)+'\n')

    ledger=result.get('ledger',{})
    with (destination.parent/'runs.log').open('a',encoding='utf-8') as log:
        log.write(f"{data['day']} 本次玩{ledger.get('rounds',0)}局，收取{ledger.get('collected',0)}，赢局净赚{ledger.get('winning_net',0)}，输{ledger.get('lost_rounds',0)}局，亏损{ledger.get('loss_amount',0)}，下注成本{ledger.get('entry_fees',0)}，净收益{ledger.get('net',0)}；{result.get('message','')}\n")
        for row in ledger.get('round_history',[]):
            log.write(f"  第{row['round']}局：{'输' if row['outcome']=='loss' else '赢'}，收取{row['collected']}，下注{row['fee']}，净收益{row['net']:+d}\n")



def execute_daily(adapter,progress=print,should_yield=lambda:False,*,startup=True,
                  request=None,on_event=None,reward_reader=None,task_handlers=None):
    """Validated plan -> selected tasks. Trusted Python hooks, JSON-only requests."""
    from modular_agent.agent.daily_tasks import DailyTasks,validate_config
    from modular_agent.domains.hololive_dreams.daily_plan import build_plan,NOTIFICATION_TASKS
    from modular_agent.domains.hololive_dreams.daily_journal import DailyJournal
    from modular_agent.perception.template_import import import_game_templates
    root=adapter.root;computer=adapter.computer
    config=json.loads((root/'domains/hololive_dreams/daily_tasks_config.json').read_text(encoding='utf-8-sig'))
    validate_config(config)
    handlers={} if task_handlers is None else dict(task_handlers)
    if any(not isinstance(k,str) or not callable(v) for k,v in handlers.items()):
        raise ValueError('task_handlers需任务ID到可信Python函数的映射')
    plan=build_plan(config,request,handlers)
    if not plan['tasks']:
        return {'outcome':'success','verified':True,'plan':plan,'items':{},'message':'空任务计划，未操作游戏'}
    if not computer.live:
        return {'outcome':'unknown','verified':False,'plan':plan,'message':'模拟模式不会执行每日任务'}
    journal=DailyJournal(root,on_event)
    progress('每日运行记录：'+str(journal.directory));journal('plan',plan=plan)
    result={'outcome':'success','verified':True,'plan':plan,'items':{},
            'rewards':{'enabled':plan['record_rewards'],'records':[]},
            'message':'本轮所选任务已处理；未确认全部日常或感叹号清空'}
    tree=None;active_task=None
    def check():
        if should_yield() or getattr(computer,'stopped',False):raise RuntimeError('每日计划停止或收到人工引导')
    try:
        check()
        if startup:
            launched=adapter._skill({'skill':'launch_game','domain':'hololive_dreams'},'启动游戏完成每日任务',progress,should_yield)
            journal('startup_result',result=launched)
            if launched.get('outcome')!='success':
                result.update(outcome='unknown',verified=False,message=launched.get('message','启动未完成'))
                return result
        check()
        imported=import_game_templates(root,'hololive_dreams')
        if imported.get('errors'):raise ValueError('每日模板导入失败：'+str(imported['errors']))
        vision=adapter._vision_for('hololive_dreams')
        profile=next(p for p in adapter.profiles if p['domain']=='hololive_dreams')
        def observe(recovery=False):
            from modular_agent.agent.daily_tasks import TEMPLATES,WORK
            phase=tree.observation_phase
            names=TEMPLATES
            if phase=='holowork':names=['menu','stage','task',*WORK,'daily_work_setup_all_sample']
            elif phase=='gift':names=['menu','stage','task','attention',*('daily_notice_'+n for n in NOTIFICATION_TASKS),'daily_rewards_get','daily_gift_interact','daily_wheel_interact','entry_lever_interact','entry_to_game','entry_keep']
            elif phase=='claims':
                from modular_agent.domains.hololive_dreams.claim_tasks import templates_for
                names=templates_for(tree.current_task)
            return observe_daily(vision,computer,profile,progress,should_yield,threshold=config.get('template_threshold',.6),template_names=names,recovery=recovery)
        selected=[n for n in plan['tasks'] if n in NOTIFICATION_TASKS]
        tree=DailyTasks(config,observe,computer,progress,should_yield,
                       selected_tasks=selected,record_rewards=plan['record_rewards'],
                       redispatch_holowork=plan['redispatch_holowork'],on_event=journal,reward_reader=reward_reader,
                       unknown_notification_policy=plan['unknown_notification_policy'],discover=lambda:observe(True))
        notifications=tree.notifications()
        result['items'].update(notifications.get('items',{}))
        result['notifications']=notifications
        if notifications.get('verified') is False:result['verified']=False
        if notifications['outcome']!='success':
            result.update(outcome='unknown',verified=False,message=notifications.get('message','通知流程未完成'))
            return result
        for task in plan['tasks']:
            if task in NOTIFICATION_TASKS:continue
            check();active_task=task;journal('task_started',task=task)
            if task=='greed_cards_entry':
                from modular_agent.agent.entry_observer import EntryObserver
                entry_tree=load_greed_cards(root)
                item=entry_tree.run(EntryObserver(adapter,entry_tree,progress),computer,progress,should_yield=should_yield)
                result['greed_cards_entry']=item
            elif task=='greed_cards_play':
                module=load_greed_cards_play_module(root)
                observer=module.PlayObserver(root,vision,computer,profile)
                play=module.GreedCardsPlay(**play_starting_policy(root,max_rounds=plan['max_rounds'],max_loss=plan['max_loss']))
                item=play.run(observer,computer,progress,should_yield=should_yield,
                              timeout=profile.get('local_models',{}).get('greed_cards_play',{}).get('timeout_seconds',1800))
                save_play_result(root,item);result['greed_cards_play']=item
            elif task in ('task_pass','events','achievements'):
                from modular_agent.domains.hololive_dreams.claim_tasks import ClaimTasks
                item=ClaimTasks(tree).run(task)
            else:
                context={'adapter':adapter,'config':config,'plan':plan,'observe':observe,
                         'progress':progress,'should_yield':should_yield,'emit':journal}
                item=handlers[task](context)
                if not isinstance(item,dict) or item.get('outcome') not in ('success','unknown','failure','skipped'):
                    raise ValueError('扩展任务必须返回结构化outcome：'+task)
            result['items'][task]=item;journal('task_finished',task=task,result=item)
            if item.get('verified') is False:result['verified']=False
            if item.get('outcome') not in ('success','skipped'):
                result.update(outcome=item.get('outcome','unknown'),verified=False,message=item.get('message',task+'未完成'))
                break
    except (RuntimeError,ValueError) as error:
        if active_task:result['items'][active_task]={'outcome':'unknown','verified':False,'message':str(error)}
        journal('error',message=str(error))
        result.update(outcome='unknown',verified=False,message=str(error))
    except Exception as error:
        journal('exception',type=type(error).__name__,message=str(error))
        result.update(outcome='failure',verified=False,message='每日模块异常：'+str(error))
    finally:
        computer.release_all()
        if tree is not None:result['rewards']['records']=tree.reward_recorder.records
        for task in plan['tasks']:
            result['items'].setdefault(task,{'outcome':'skipped','verified':False,'reason':'尚未执行或前序未完成','blocked_by':active_task})
        result['day']=play_day();result['trace_directory']=str(journal.directory)
        if journal.callback_errors:result['callback_errors']=journal.callback_errors
        journal.finish(result)
        destination=root/'runtime/daily-tasks'
        (destination/'last-result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
    return result
def run_daily_tasks(root,*,live=False,progress=print,request=None,plan_only=False,on_event=None,reward_reader=None,task_handlers=None):
    root=Path(root)
    if plan_only:
        from modular_agent.domains.hololive_dreams.daily_plan import build_plan,catalog
        config=json.loads((root/'domains/hololive_dreams/daily_tasks_config.json').read_text(encoding='utf-8-sig'))
        return {'outcome':'planned','executed':False,'plan':build_plan(config,request,task_handlers or ()),'catalog':catalog()}
    from datetime import datetime
    folder=root/'runtime/daily-tasks';folder.mkdir(parents=True,exist_ok=True)
    with (folder/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.log')).open('w',encoding='utf-8') as log:
        def output(message):
            if progress is print: print(message,flush=True)
            else: progress(message)
            log.write(str(message)+'\n');log.flush()
        with ActionComputer(live=live,audit_path=root/'runtime/computer-actions.jsonl') as computer:
            with GeneralAgent(root,computer,None,domain='hololive_dreams') as adapter:
                result=execute_daily(adapter,output,request=request,on_event=on_event,reward_reader=reward_reader,task_handlers=task_handlers)
                log.write(json.dumps(result,ensure_ascii=False,indent=2)+'\n');log.flush()
                return result


def observe_daily(vision,computer,profile,progress=print,should_yield=lambda:False,*,threshold=.6,template_names=None,recovery=False):
    from modular_agent.agent.daily_tasks import TEMPLATES
    if should_yield() or getattr(computer,'stopped',False): raise RuntimeError('每日任务已停止或收到人工引导')
    launcher=GameLauncher(vision,computer,profile)
    game=launcher._window(vision.desktop.windows())
    if not game: raise RuntimeError('每日任务无法找到游戏窗口')
    if not game.get('foreground') or game.get('minimized'):
        progress('每日任务：游戏失去焦点，切回并验证游戏窗口。')
        game=launcher._focus_verified(game)
    if should_yield() or getattr(computer,'stopped',False): raise RuntimeError('每日任务已停止或收到人工引导')
    progress(f'每日识别：通知、按钮和主界面模板（'+('未知窗口按需OCR+按钮形状' if recovery else '无OCR')+f'；门槛{threshold:.2f}）。')
    report=vision.observe(environment='hololive_dreams',window_handle=game['handle'],
            enable_ocr=recovery,enable_uia=False,enable_cv_buttons=recovery,
            template_names=TEMPLATES if template_names is None else template_names,template_scales=[1.0],template_threshold=threshold)
    diagnostics=getattr(vision.knowledge,'last_diagnostics',[])
    hud=[d for d in diagnostics if d['name'] in ('menu','stage','task','attention')]
    progress('每日检测：'+('；'.join(d['name']+' '+format(d['score'],'.3f') for d in hud) or '无主界面诊断'))
    for m in report.knowledge_matches:
        if m['label'].startswith('daily_'):
            b=m['bounds'];progress(f"每日模板：{m['label']}；坐标 ({b['x']}, {b['y']})；相似度 {m['similarity']:.3f}")
    return report
