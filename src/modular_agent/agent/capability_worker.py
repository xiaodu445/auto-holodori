"""Isolated runtime worker for the fixed, trusted realtime adapters."""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import sys
import time


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def flags(params, *, names=None):
    args = []
    for name, value in params.items():
        key = '--' + (names or {}).get(name, name).replace('_', '-')
        if type(value) is bool:
            if value: args.append(key)
        else:
            args.extend([key, str(value)])
    return args


def run(root, request, stop):
    name, params = request['capability'], dict(request['params'])
    deadline = time.monotonic() + request['timeout']
    cancelled = lambda: stop.exists() or time.monotonic() >= deadline
    model_dir = root / 'domains/hololive_dreams/models'
    if cancelled(): return {'outcome': 'cancelled', 'verified': False}
    if name == 'rhythm':
        from modular_agent.computer.windows import WindowsBackend
        windows = [w for w in WindowsBackend().windows() if w.get('title', '').lower() == 'hololive-dreams' and w.get('foreground')]
        if len(windows) != 1: raise ValueError('Requires unique foreground hololive-dreams window')
        module = load(model_dir / 'rhythm/rhythm_game.py', 'capability_rhythm')
        deadline = min(deadline, time.monotonic() + params.pop('timeout_seconds'))
        result = module.run(root, windows[0]['handle'], live=True, should_yield=cancelled,
                            config_path=params.get('config_path'), preview=params['preview'],
                            overrides=params.get('overrides'), progress=lambda s: print(s, flush=True))
        result.pop('rows', None)
        return result
    if name == 'kitchen':
        params['duration'] = min(params['duration'], request['timeout'])
        module = load(model_dir / 'kitchen/kitchen_play.py', 'capability_kitchen')
        return module.main(['--live', '--stop-file', str(stop), *flags(params)])
    if name == 'jump_rope':
        sys.path.insert(0, str(model_dir / 'jump_rope'))
        module = load(model_dir / 'jump_rope/game_jump_live.py', 'capability_jump_rope')
        params['timeout_seconds'] = min(params['timeout_seconds'], request['timeout'])
        return module.main(['--live', '--stop-file', str(stop), *flags(params, names={'config_path': 'config'})])
    if name == 'multi_live':
        params['timeout_seconds'] = min(params['timeout_seconds'], request['timeout'])
        module = load(root / 'entrypoints/run_multi_live.py', 'capability_multi_live')
        result_path = stop.parent / 'multi-result.json'
        module.main(['--live', '--stop-file', str(stop), '--result-file', str(result_path),
                     *flags(params, names={'timeout_seconds': 'timeout', 'config_path': 'config'})])
        if result_path.is_file(): return json.loads(result_path.read_text(encoding='utf-8'))
        return {'outcome': 'unknown', 'verified': False, 'message': 'No verified multiplayer result'}
    raise ValueError('Unknown worker capability')


def main():
    parser = argparse.ArgumentParser()
    for name in ('root', 'request', 'stop', 'output'): parser.add_argument('--' + name, required=True, type=Path)
    args = parser.parse_args()
    try:
        result = run(args.root, json.loads(args.request.read_text(encoding='utf-8')), args.stop)
        if not isinstance(result, dict): result = {'outcome': 'unknown', 'verified': False}
        result.setdefault('outcome', 'unknown')
        result['verified'] = result.get('verified') is True and result['outcome'] == 'success'
    except BaseException as error:
        result = {'outcome': 'failure', 'verified': False, 'message': type(error).__name__ + ': ' + str(error)}
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__': main()
