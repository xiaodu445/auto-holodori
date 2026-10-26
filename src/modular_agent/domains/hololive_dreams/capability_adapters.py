"""Trusted Hololive adapters. Manifest data never chooses code or shell commands."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

DOMAIN = 'hololive_dreams'


def domain_file(root, value, *, suffixes=('.json',), weights=False):
    """Model-supplied files are existing domain data, never provider credentials."""
    base = (Path(root) / 'domains' / DOMAIN).resolve()
    if weights:
        base = base / 'models'
    path = Path(value)
    if not path.is_absolute():
        path = Path(root) / path
    path = path.resolve()
    if not path.is_relative_to(base) or not path.is_file() or path.suffix.lower() not in suffixes:
        raise ValueError('File must be existing domain data with suffix ' + ','.join(suffixes))
    return str(path)


def prepare_params(root, name, params, *, references=False):
    params = dict(params)
    def literal(value):
        if isinstance(value,dict):return '$ref' not in value and all(literal(v) for v in value.values())
        if isinstance(value,list):return all(literal(v) for v in value)
        return True
    if 'config_path' in params and (not references or literal(params['config_path'])):
        params['config_path'] = domain_file(root, params['config_path'])
    if 'weights' in params and (not references or literal(params['weights'])):
        params['weights'] = domain_file(root, params['weights'], suffixes=('.pt', '.engine', '.onnx'), weights=True)
    if name == 'multi_live':
        if ('window_width' in params) != ('window_height' in params):
            raise ValueError('window_width and window_height must be specified together')
        if params.get('rhythm_profile') == 'config' and 'config_path' not in params:
            raise ValueError('rhythm_profile=config requires config_path')
    if name == 'daily_tasks':
        from modular_agent.domains.hololive_dreams.daily_plan import build_plan, effective_config
        defaults = json.loads((Path(root) / 'domains' / DOMAIN / 'daily_tasks_config.json').read_text(encoding='utf-8-sig'))
        request = params.get('request', {})
        if references:
            request={k:v for k,v in request.items() if literal(v)} if literal(request) or '$ref' not in request else {}
        build_plan(effective_config(defaults, request, root=root), request)
    if name == 'kitchen':
        if literal(params['confidence_ceiling']) and literal(params['confidence']) and params['confidence_ceiling'] < params['confidence']:
            raise ValueError('confidence_ceiling must be >= confidence')
        if all(literal(params[k]) for k in ('confidence_slot_weight','confidence_visible_weight','confidence_click_weight')) and params['confidence_slot_weight'] < params['confidence_visible_weight'] + params['confidence_click_weight']:
            raise ValueError('confidence_slot_weight must be >= sum of other weights')
    return params


def execute(adapter, goal, name, params, *, progress, cancelled, timeout, directory):
    params = prepare_params(adapter.root, name, params)
    if name=='return_to_free':
        from .free_state_recovery import FreeStateRecovery
        return FreeStateRecovery(lambda:adapter._observe(DOMAIN,progress,'full'),adapter.computer,
            cancelled=cancelled,progress=progress,timeout=min(timeout,params['timeout_seconds']),
            current_windows=(lambda:adapter._vision_for(DOMAIN).desktop.windows()) if hasattr(adapter,'_vision_for') else None).run()
    if name == 'daily_tasks':
        from modular_agent.local_models import execute_daily
        failure=daily_precondition(adapter,params,progress=progress,cancelled=cancelled)
        if failure is not None:return failure
        return execute_daily(adapter, progress, cancelled, request=params.get('request'), startup=params['startup'])
    if name == 'greed_cards_entry':
        return adapter._run_local_entry(goal, progress, cancelled)
    if name == 'greed_cards_play':
        return adapter._run_local_play(goal, progress, cancelled, params=params, timeout=timeout)
    if name in ('launch_game', 'fishing_loop', 'fishing_assist'):
        if name.startswith('fishing'):
            # Each explicit plan step gets a fresh eligibility check; no blind UI replay.
            adapter._fishing_used = False
            params = {**params, 'timeout_seconds': min(params.get('timeout_seconds', timeout), timeout)}
        return adapter._skill({'skill': name, 'domain': DOMAIN, 'params': params}, goal, progress, cancelled)
    if name not in ('jump_rope', 'kitchen', 'rhythm', 'multi_live'):
        raise ValueError('No trusted adapter: ' + name)
    # Real-time engines own their input; never leave menu keys held during handoff.
    adapter.computer.release_all()
    return run_worker(adapter.root, name, params, timeout=timeout, cancelled=cancelled,
                      progress=progress, directory=directory)


def daily_precondition(adapter,params,*,progress,cancelled):
    from modular_agent.agent.recovery import precondition_failure
    from .free_state_recovery import recovery_state,check_window,observed_state
    if params.get('request',{}).get('selected_tasks')==[]:return None
    if cancelled():return {'outcome':'cancelled','verified':False}
    report=adapter._observe(DOMAIN,progress,'full')
    if cancelled():return {'outcome':'cancelled','verified':False}
    game=next((w for w in report.windows if w.get('handle')==report.frame.get('target_window_handle')),None)
    if params.get('startup',True) and (not game or not game.get('foreground') or game.get('minimized')):
        return None  # Preserve the existing explicitly enabled launch/focus path.
    try:check_window(report)
    except RuntimeError as error:
        return precondition_failure('world.free','window_unavailable',str(error))
    state=recovery_state(report)
    if state=='free':return None
    return precondition_failure('world.free',observed_state(report),
        '日常尚未开始：当前不是自由界面；未发送业务操作。',
        recoverable=state not in ('blocked','unsupported'))


def run_worker(root, name, params, *, timeout, cancelled, progress, directory):
    root, directory = Path(root).resolve(), Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    request = directory / 'request.json'
    stop = directory / 'stop'
    output = directory / 'result.json'
    request.write_text(json.dumps({'capability': name, 'params': params, 'timeout': timeout}), encoding='utf-8')
    python = root / ('.vision/Scripts/python.exe' if name in ('jump_rope', 'kitchen') else '.conda/python.exe')
    if not python.is_file():
        raise ValueError('Runtime interpreter missing: ' + str(python))
    env = {**os.environ, 'PYTHONPATH': str(root / 'src'), 'PYTHONIOENCODING': 'utf-8'}
    args = [str(python), '-m', 'modular_agent.agent.capability_worker',
            '--root', str(root), '--request', str(request), '--stop', str(stop), '--output', str(output)]
    deadline = time.monotonic() + timeout
    interrupted = False
    with (directory / 'worker.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen(args, cwd=root, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            progress('实时组件日志：' + str(directory/'worker.log'))
            next_update=time.monotonic()+30
            while process.poll() is None:
                if cancelled() or time.monotonic() >= deadline:
                    interrupted = True
                    stop.touch()  # Engines release held inputs through their own finally blocks.
                    progress('请求实时组件停止并保存结果。')
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill(); process.wait()
                        release_worker_inputs(root, name, params)
                    break
                if time.monotonic()>=next_update:
                    progress('实时组件运行中：'+name+'；剩余预算约 '+str(max(0,round(deadline-time.monotonic())))+' 秒')
                    next_update=time.monotonic()+30
                time.sleep(.05)
        finally:
            if process.poll() is None:
                stop.touch()
                try: process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
                    release_worker_inputs(root, name, params)
    result = json.loads(output.read_text(encoding='utf-8')) if output.is_file() else {
        'outcome': 'failure' if process.returncode else 'unknown', 'verified': False,
        'message': 'Worker returned no structured result'}
    if not isinstance(result,dict) or result.get('outcome') not in ('success','unknown','failure','cancelled'):
        result={'outcome':'failure','verified':False,'message':'Invalid worker result'}
    result['verified']=result.get('verified') is True and result['outcome']=='success'
    if interrupted:
        result.update(outcome='cancelled', verified=False, reason='cancelled_or_timeout')
    elif process.returncode:
        result.update(outcome='failure', verified=False)
    result['trace_directory'] = str(directory)
    result['worker_exit_code'] = process.returncode
    return result


def release_worker_inputs(root, name, params):
    """After forced termination, release only this engine's possible input keys."""
    from modular_agent.computer.windows import WindowsBackend, KEYS
    backend = WindowsBackend()
    keys = {'space'} if name == 'jump_rope' else {'alt'} if name == 'kitchen' else {'s','d','f','j','k','l','alt'}
    if name in ('rhythm','multi_live'):
        config = Path(params.get('config_path', Path(root)/'domains/hololive_dreams/models/rhythm/rhythm_game_config.json'))
        if config.is_file():
            keys.update(k for k in json.loads(config.read_text(encoding='utf-8-sig')).get('keys',[]) if k in KEYS)
    errors = []
    for key in keys:
        try: backend.key(key, False)
        except Exception as error: errors.append(str(error))
    try: backend.button('left', False)
    except Exception as error: errors.append(str(error))
    if errors: raise RuntimeError('Worker input release failed: ' + '; '.join(errors))
