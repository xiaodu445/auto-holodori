"""Human-facing interactive terminal for the connected top-level agent."""
import json
import queue
import threading
from pathlib import Path
from modular_agent.computer import ActionComputer
from modular_agent.model_client import ModelConfig,create_model_client
from .general import GeneralAgent
from modular_agent.model_profiles import ModelProfiles
from .console_log import ConsoleLog

def configured_model(args,root):
    path=root/args.config
    profile=getattr(args,"model_profile",None)
    config=ModelProfiles(root).resolve(profile) if profile else (ModelConfig.from_json(path) if path.exists() else ModelConfig())
    overrides={key:value for key,value in {
        'provider':args.provider,'model':args.model,'base_url':args.base_url,
        'api_key_env':args.api_key_env}.items() if value is not None}
    config=ModelConfig(**(config.public_dict()|overrides))
    return config,create_model_client(config)

def run_console(args,root):
    config,model=configured_model(args,root)
    log = ConsoleLog(root)
    try:
        _run_console(args, root, config, model, log)
    finally:
        log.close()

def _run_console(args, root, config, model, log):
    emit = log.emit
    if getattr(args, "log_window", False):
        log.show()
    with ActionComputer(live=args.live,audit_path=root/'runtime'/'computer-actions.jsonl') as computer, GeneralAgent(root,computer,model,domain=args.domain,max_steps=args.max_steps) as agent:
        def progress(message): emit(message,flush=True)
        guidance_queue=queue.Queue(maxsize=64)
        worker=None
        task_active=threading.Event()
        def drain_guidance():
            messages=[]
            while True:
                try: messages.append(guidance_queue.get_nowait())
                except queue.Empty: return messages
        def execute(goal):
            try: return agent.execute(goal,progress,guidance=drain_guidance)
            except Exception as error: return {'outcome':'failure','verified':False,'message':str(error)}
        if args.live:
            emit('初始化本地识别常驻组件；首次预热后整个会话复用。',flush=True)
            agent.vision.warmup(progress)
        if args.command=='run':
            result=execute(args.goal)
            emit(json.dumps(result,ensure_ascii=False))
            return
        emit('顶层 Agent 已启动。模式：'+('真实操作' if args.live else '模拟操作'))
        emit(f'当前模型：{config.provider} / {config.model}')
        emit('任务步骤：不限。' if args.max_steps==0 else f'任务步骤上限：{args.max_steps}。')
        emit(f'日志文件：{log.path}。/logs on 显示置顶日志，/logs off 隐藏。')
        emit('任务执行中可直接输入补充指示，或 /guide 指示；/stop 紧急停止。')
        emit('输入：启动hololivedreams。/observe 查看本地感知，/windows 查看窗口，/quit 退出。')
        emit('F12 紧急停止；停止后请退出并重新启动。所有任务由模型驱动；需要配置真实模型。')
        if config.provider=='mock':
            emit('当前 provider=mock，只验证交互，不会规划或启动游戏。请配置 config/model.json 或使用 --provider。')
        def run_task(goal):
            try:
                result=execute(goal)
                try:
                    destination=root/'runtime'/'last-agent-result.json'
                    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                except OSError as error:
                    emit(f'结果保存失败：{error}；任务已结束。',flush=True)
                emit(f"[{result['outcome']}] {result['message']}",flush=True)
                if not result.get('verified') and result['outcome']=='success':
                    emit('这是模型根据屏幕信息作出的判断，未经过专用规则验证。')
            finally:
                task_active.clear()
                emit('任务已结束，可以输入新任务。',flush=True)
                # input() is already waiting on the main thread; redraw its obscured prompt.
                # The input editor preserves and redraws the current line.

        while True:
            try: goal=(log.read_line('Agent > ') if hasattr(log,'read_line') else input('Agent > ')).strip()
            except EOFError:
                if worker is not None: worker.join()
                break
            except KeyboardInterrupt:
                computer.stop()
                if worker is not None: worker.join()
                break
            if not goal: continue
            if goal.startswith('/'):
                command,separator,arguments=goal.partition(' ')
                goal=command.lower()+separator+arguments
            if goal in ('/quit','/exit','退出'):
                if worker is not None:
                    worker.join(timeout=.05)
                    if worker.is_alive():
                        computer.stop()
                        emit('正在停止任务并等待当前调用返回……')
                        worker.join()
                break
            if goal in ('/logs', '/logs on', '/logs off'):
                if goal == '/logs off':
                    log.hide()
                    emit('日志窗口已隐藏；仍会保存日志文件。')
                else:
                    log.show()
                    emit('日志窗口已开启，不会抢走游戏键盘焦点。')
                continue
            if goal=='/stop': computer.stop(); emit('操作会话已停止。'); continue
            if goal=='/status':
                emit('会话已停止，需要重启。' if computer.stopped else ('任务执行中，可以输入人工引导。' if task_active.is_set() else '空闲，可以输入新任务。'),flush=True)
                continue
            active=task_active.is_set()
            if goal.startswith('/guide ') or (active and not goal.startswith('/')):
                message=goal[7:].strip() if goal.startswith('/guide ') else goal
                if not active:
                    emit('当前没有执行中的任务，请直接输入新任务。')
                elif not message or len(message)>2000:
                    emit('补充指示需要 1 至 2000 个字符。')
                else:
                    try:
                        guidance_queue.put_nowait(message)
                        emit('人工引导已排队，将在下一决策边界生效。')
                    except queue.Full: emit('引导队列已满，请等待当前指示被读取。')
                continue
            if active:
                emit('任务正在执行；可输入补充指示、/logs on/off、/stop 或 /quit。')
                continue
            if goal=='/models':
                profiles=ModelProfiles(root)
                emit('可切换：'+', '.join(profiles.names()))
                emit(f'当前：{config.provider} / {config.model}。使用 /model kimi 切换；仅在任务间切换。')
                continue
            if goal=='/model' or goal.startswith('/model '):
                name=goal.partition(' ')[2].strip()
                if not name:
                    emit(f'当前：{config.provider} / {config.model}。使用 /models 查看配置。')
                    continue
                try:
                    new_config=ModelProfiles(root).select(name)
                    new_model=create_model_client(new_config)
                    config=new_config
                    agent.model=new_model
                    emit(f'已切换并保存：{name}（{config.model}）')
                except Exception as error: emit(f'切换失败：{error}')
                continue
            if goal=='/help':
                emit('启动hololivedreams | /observe [full/icons] | /windows | /models | /model 名称 | /status | /guide 补充指示 | /logs on/off | /stop | /quit。其余自然语言任务交给模型。')
                continue
            if goal in ('/observe','/observe full','/observe icons','/windows'):
                try:
                    if goal=='/windows': emit(json.dumps(agent.vision.desktop.windows(),ensure_ascii=False,indent=2))
                    else:
                        report=agent._observe(args.domain,progress,goal.partition(' ')[2] or 'full')
                        destination=root/'runtime'/'screen-report.json'
                        destination.write_text(json.dumps(report.to_dict(),ensure_ascii=False,indent=2),encoding='utf-8')
                        emit(f'窗口 {len(report.windows)}，按钮/候选 {len(report.buttons)}，文字 {len(report.texts)}；结果：{destination}')
                        if report.warnings: emit('提示：'+'; '.join(report.warnings))
                except Exception as error: emit(f'读取失败：{error}')
                continue
            drain_guidance()
            emit('任务：' + goal)
            task_active.set()
            worker=threading.Thread(target=run_task,args=(goal,),name='agent-task')
            worker.start()
