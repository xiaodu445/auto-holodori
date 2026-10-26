"""Ordered, bounded capability plans with explicit conditions and durable facts.

No automatic replay: a new run is always a new execution. Unknown results block
dependent steps. Logs record facts, never upgrade process exit to game success.
"""
from __future__ import annotations

from copy import deepcopy
import json
import math
from pathlib import Path
import re
import time
from uuid import uuid4
from contextlib import contextmanager
from datetime import datetime,timezone


@contextmanager
def execution_lock(root):
    """OS lock is released on process exit, so a crash cannot leave a stale lease."""
    path=Path(root)/'runtime/task-plans/session.lock'
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0);stream.write(b'0');stream.flush();stream.seek(0)
        import os
        if os.name=='nt':
            import msvcrt
            try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
            except OSError as error:raise RuntimeError('Another capability plan is running') from error
            try:yield
            finally:stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
        else:
            import fcntl
            try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as error:raise RuntimeError('Another capability plan is running') from error
            try:yield
            finally:fcntl.flock(stream,fcntl.LOCK_UN)


def result_value(reference, results):
    parts = reference.split('.')
    if len(parts) < 2 or parts[0] not in results:
        raise ValueError('Unavailable result reference: ' + reference)
    value = results[parts[0]]
    for part in parts[1:]:
        if not isinstance(value, dict) or part not in value:
            raise ValueError('Missing result field: ' + reference)
        value = value[part]
    return deepcopy(value)


def resolve(value, results):
    if isinstance(value, dict):
        if set(value) == {'$ref'}:
            return result_value(value['$ref'], results)
        return {k: resolve(v, results) for k, v in value.items()}
    if isinstance(value, list):
        return [resolve(v, results) for v in value]
    return value


def json_equal(left,right):
    if isinstance(left,bool) != isinstance(right,bool):return False
    if isinstance(left,dict) and isinstance(right,dict):
        return left.keys()==right.keys() and all(json_equal(left[k],right[k]) for k in left)
    if isinstance(left,list) and isinstance(right,list):
        return len(left)==len(right) and all(json_equal(a,b) for a,b in zip(left,right))
    return left==right


def validate_plan(catalog, plan):
    if not isinstance(plan, dict) or plan.keys() - {'schema_version', 'steps', 'timeout_seconds'}:
        raise ValueError('Plan must contain schema_version, steps and optional timeout_seconds')
    if type(plan.get('schema_version')) is not int or plan['schema_version'] != 1:
        raise ValueError('Unsupported plan schema_version')
    steps = plan.get('steps')
    if not isinstance(steps, list) or not 1 <= len(steps) <= 100:
        raise ValueError('Plan requires 1..100 steps')
    def budget(v):
        if type(v) not in (int, float) or not math.isfinite(v) or not .1 <= v <= 86400:
            raise ValueError('timeout_seconds must be .1..86400')
        return v
    result = {'schema_version': 1, 'timeout_seconds': budget(plan.get('timeout_seconds', 3600)), 'steps': []}
    seen = set()
    for raw in steps:
        if not isinstance(raw, dict) or raw.keys() - {'id', 'capability', 'params', 'depends_on', 'when', 'on_failure', 'timeout_seconds','recovery'}:
            raise ValueError('Unknown step fields')
        name = raw.get('id')
        if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', name) or name in seen:
            raise ValueError('Step IDs must be unique identifiers')
        capability = raw.get('capability')
        catalog.read(capability)
        dependencies = raw.get('depends_on', [])
        if not isinstance(dependencies, list) or any(not isinstance(d, str) or d not in seen for d in dependencies):
            raise ValueError('Dependencies must refer to earlier steps; cycles/forward references forbidden')
        params = catalog.parameters(capability, raw.get('params', {}), references=True)
        def check_refs(value):
            if isinstance(value, dict):
                if '$ref' in value:
                    if set(value) != {'$ref'} or not isinstance(value['$ref'], str):
                        raise ValueError('A result reference must contain only $ref')
                    parts = value['$ref'].split('.')
                    if len(parts) < 2 or parts[0] not in seen or any(not p for p in parts):
                        raise ValueError('Result references must target earlier step fields')
                else:
                    for item in value.values(): check_refs(item)
            elif isinstance(value, list):
                for item in value: check_refs(item)
        check_refs(params)
        catalog.preflight(capability,params)
        step = {'id': name, 'capability': capability, 'params': params,
                'depends_on': dependencies, 'on_failure': raw.get('on_failure', 'stop'),
                'recovery':raw.get('recovery','auto'),
                'timeout_seconds': budget(raw.get('timeout_seconds', result['timeout_seconds']))}
        if step['recovery'] not in ('auto','none'):raise ValueError('recovery must be auto or none')
        if step['on_failure'] not in ('stop', 'continue'):
            raise ValueError('on_failure must be stop or continue; no implicit retries')
        if 'when' in raw:
            condition = raw['when']
            if not isinstance(condition, dict) or set(condition) != {'ref', 'equals'} or not isinstance(condition['ref'], str):
                raise ValueError('when requires ref and equals')
            check_refs({'$ref': condition['ref']})
            # Conditions are JSON values, never expressions or executable code.
            json.dumps(condition, allow_nan=False)
            step['when'] = deepcopy(condition)
        result['steps'].append(step)
        seen.add(name)
    return result


class PlanRunner:
    def __init__(self, catalog, executor, *, clock=time.monotonic):
        self.catalog, self.executor, self.clock = catalog, executor, clock

    def _invoke(self,step,params,*,progress,cancelled,deadline,directory,event):
        from .recovery import recovery_target
        def call(capability,arguments,path):
            if cancelled():return {'outcome':'cancelled','verified':False}
            return self.executor(capability,arguments,progress=progress,cancelled=cancelled,
                timeout=max(.001,deadline-self.clock()),directory=path)
        initial=call(step['capability'],params,directory)
        target=recovery_target(self.catalog,step,initial)
        if not target or cancelled() or deadline-self.clock()<.1:return initial
        # Exactly one recovery plus one retry. The original step's clock keeps running.
        event('recovery_started',id=step['id'],capability=target,initial_result=initial)
        progress('前置状态不满足，尝试恢复界面后重试当前步骤一次：'+step['id'])
        arguments=self.catalog.parameters(target,{'timeout_seconds':min(30,deadline-self.clock())})
        try:
            recovered=call(target,arguments,directory/'recovery')
        except Exception as error:
            recovered={'outcome':'failure','verified':False,'message':str(error)}
        event('recovery_finished',id=step['id'],result=recovered)
        history={'initial_result':initial,'capability':target,'result':recovered,'retries':0}
        if isinstance(recovered,dict) and recovered.get('outcome')=='cancelled':
            return {'outcome':'cancelled','verified':False,'reason':'recovery_cancelled','recovery_attempt':history}
        if (not isinstance(recovered,dict) or recovered.get('outcome')!='success'
                or recovered.get('verified') is not True
                or recovered.get('state')!=initial['error']['expected_state'] or cancelled()):
            return {**initial,'recovery_attempt':history}
        history['retries']=1
        event('step_retry_started',id=step['id'])
        try:
            retried=call(step['capability'],params,directory/'retry')
        except Exception as error:
            retried={'outcome':'failure','verified':False,'message':str(error)}
        if not isinstance(retried,dict):retried={'outcome':'failure','verified':False,'message':'Invalid retry result'}
        # No recursion: another precondition failure returns to the model as-is.
        return {**retried,'recovery_attempt':history}

    def run(self, plan, *, live=False, progress=print, cancelled=lambda: False, run_id=None):
        plan=validate_plan(self.catalog,plan)
        if not live:return self._run(plan,live=False,progress=progress,cancelled=cancelled,run_id=run_id)
        with execution_lock(self.catalog.root):
            return self._run(plan,live=True,progress=progress,cancelled=cancelled,run_id=run_id)

    def _run(self, plan, *, live, progress, cancelled, run_id):
        plan = validate_plan(self.catalog, plan)  # Whole-plan preflight before any input.
        if not live:
            return {'outcome': 'planned', 'verified': False, 'executed': False, 'plan': plan}
        run_id = run_id or uuid4().hex
        directory = run_directory(self.catalog.root, run_id)
        directory.mkdir(parents=True, exist_ok=False)
        state = {'run_id': run_id, 'outcome': 'running', 'verified': False, 'executed': True,
                 'plan': plan, 'steps': {}, 'trace_directory': str(directory)}
        progress('任务计划运行 ID：' + run_id)
        def save():
            temporary = directory / 'state.tmp'
            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
            temporary.replace(directory / 'state.json')
        def event(kind, **data):
            state['updated_at']=datetime.now(timezone.utc).isoformat()
            with (directory / 'events.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'event': kind, 'time':state['updated_at'], **data}, ensure_ascii=False, allow_nan=False) + '\n')
            save()
        deadline = self.clock() + plan['timeout_seconds']
        cancellation_latched = False
        def stopped():
            nonlocal cancellation_latched
            cancellation_latched = cancellation_latched or cancelled() or (directory / 'cancel').exists() or self.clock() >= deadline
            return cancellation_latched
        event('plan_started')
        stop_reason = None
        try:
            for step in plan['steps']:
                name = step['id']
                if stopped():
                    stop_reason = 'cancelled_or_timeout'
                    break
                if any(state['steps'][d]['outcome'] != 'success' for d in step['depends_on']):
                    state['steps'][name] = {'outcome': 'skipped', 'verified': False, 'reason': 'dependency_not_successful'}
                    event('step_skipped', id=name)
                    continue
                step_deadline = min(deadline, self.clock() + step['timeout_seconds'])
                try:
                    condition = step.get('when')
                    if condition and not json_equal(result_value(condition['ref'], state['steps']),condition['equals']):
                        state['steps'][name] = {'outcome': 'skipped', 'verified': False, 'reason': 'condition_false'}
                        event('step_skipped', id=name)
                        continue
                    params = self.catalog.parameters(step['capability'], resolve(step['params'], state['steps']))
                    def step_cancelled():
                        return stopped() or self.clock() >= step_deadline
                    state['active_step'] = name
                    event('step_started', id=name, params=params)
                    progress('执行计划步骤：' + name + ' / ' + step['capability'])
                    value = self._invoke(step,params,progress=progress,cancelled=step_cancelled,
                        deadline=step_deadline,directory=directory/name,event=event)
                    if not isinstance(value, dict) or value.get('outcome') not in ('success', 'unknown', 'failure', 'cancelled'):
                        raise ValueError('Capability returned no valid outcome')
                    value = deepcopy(value)
                    value['verified'] = value.get('verified') is True and value['outcome'] == 'success'
                    if step_cancelled():
                        value.update(outcome='cancelled', verified=False, reason='cancelled_or_timeout')
                except Exception as error:
                    value = {'outcome': 'failure', 'verified': False, 'message': str(error)}
                    if stopped() or self.clock()>=step_deadline:
                        value.update(outcome='cancelled',reason='cancelled_or_timeout')
                state['steps'][name] = value
                event('step_finished', id=name, result=value)
                if value['outcome'] == 'cancelled' or (value['outcome'] != 'success' and step['on_failure'] == 'stop'):
                    stop_reason = name
                    break
        finally:
            state.pop('active_step', None)
            for step in plan['steps']:
                state['steps'].setdefault(step['id'], {'outcome': 'skipped', 'verified': False, 'reason': 'not_executed'})
            values = list(state['steps'].values())
            bad = [v for v in values if v['outcome'] not in ('success', 'skipped')]
            blocked = any(v.get('reason') in ('dependency_not_successful', 'not_executed') for v in values)
            state['outcome'] = ('cancelled' if stop_reason == 'cancelled_or_timeout' or any(v['outcome']=='cancelled' for v in values)
                                else 'failure' if any(v['outcome']=='failure' for v in bad)
                                else 'unknown' if bad or blocked else 'success')
            state['verified'] = state['outcome']=='success' and all(v.get('verified') is True for v in values if v['outcome']!='skipped')
            state['stop_reason'] = stop_reason
            event('plan_finished', outcome=state['outcome'])
        return state


def run_directory(root, run_id):
    if not isinstance(run_id, str) or not re.fullmatch(r'[a-f0-9]{32}', run_id):
        raise ValueError('run_id must be 32 lowercase hex characters')
    return Path(root) / 'runtime' / 'task-plans' / run_id


def plan_status(root, run_id, *, cancel=False):
    directory = run_directory(root, run_id)
    state = json.loads((directory / 'state.json').read_text(encoding='utf-8'))
    if cancel and state['outcome'] == 'running':
        (directory / 'cancel').touch()
        state['cancel_requested'] = True
    return state
