"""Serialized action executor with cancellation, bounded holds, and audit records."""
from __future__ import annotations
import json
import math
from pathlib import Path
import threading
import time
from datetime import datetime, UTC
from modular_agent.core import Action, Outcome, SkillResult
from .windows import KEYS, BUTTONS, WindowsBackend

SCHEMA = {
 'key_down':({'key'},set()), 'key_up':({'key'},set()),
 'press':({'key'},{'duration'}), 'hotkey':({'keys'},{'duration'}),
 'hold':({'keys','duration'},{'dx','dy','steps'}),
 'text':({'text'},set()), 'move_to':({'x','y'},{'modifiers'}),
 'move_relative':({'dx','dy'},{'duration','steps'}),
 'mouse_down':(set(),{'button'}), 'mouse_up':(set(),{'button'}),
 'click':(set(),{'button','count','interval','x','y','modifiers','duration'}),
 'scroll':({'ticks'},{'modifiers'}), 'drag':({'x','y'},{'button','duration','steps','modifiers'}),
 'wait':({'duration'},set()), 'release_all':(set(),set()),
 'windows':(set(),set()), 'cursor':(set(),set()),
 'window_resize_info':({'handle'},set()), 'resize_window':({'handle','width','height'},set()), 'focus':({'handle'},set()), 'launch':({'executable'},{'arguments'}),
 'stop':(set(),set()), 'show_desktop':(set(),set()),
}

def validate(action):
    if action.name not in SCHEMA: raise ValueError(f'Unknown action: {action.name}')
    a = action.arguments
    if not isinstance(a,dict): raise ValueError('arguments must be an object')
    required,optional = SCHEMA[action.name]
    if not required <= a.keys() or a.keys()-required-optional:
        raise ValueError(f'{action.name}: required={sorted(required)}, optional={sorted(optional)}')
    if action.target is not None: raise ValueError('Use focus with a window handle before input')
    for name in ('duration','interval'):
        if name in a and (isinstance(a[name],bool) or not isinstance(a[name],(float,int)) or not math.isfinite(a[name]) or not 0 <= a[name] <= 30):
            raise ValueError(f'{name} must be between 0 and 30 seconds')
    for name in ('x','y','dx','dy','ticks','steps','count','handle'):
        if name in a and (type(a[name]) is not int or not -2147483648 <= a[name] <= 2147483647):
            raise ValueError(f'{name} must be a 32-bit integer')
    for name in ('width','height'):
        if name in a and (type(a[name]) is not int or not 100 <= a[name] <= 10000): raise ValueError(f'{name} must be an integer between 100 and 10000')
    for name,maximum in (('steps',1000),('count',10)):
        if name in a and not 1 <= a[name] <= maximum: raise ValueError(f'{name} out of range')
    if 'ticks' in a and not -10000 <= a['ticks'] <= 10000: raise ValueError('ticks out of range')
    if 'key' in a and (not isinstance(a['key'],str) or a['key'] not in KEYS): raise ValueError('Unsupported key')
    if 'keys' in a and (not isinstance(a['keys'],list) or not a['keys'] or any(not isinstance(k,str) or k not in KEYS for k in a['keys']) or len(set(a['keys'])) != len(a['keys'])):
        raise ValueError('keys must be a nonempty list of distinct supported keys')
    if 'modifiers' in a and (not isinstance(a['modifiers'],list) or any(k not in ('alt','ctrl','shift','ralt','rctrl') for k in a['modifiers']) or len(set(a['modifiers']))!=len(a['modifiers'])):
        raise ValueError('modifiers must be a list of distinct modifier keys')
    if 'button' in a and (not isinstance(a['button'],str) or a['button'] not in BUTTONS): raise ValueError('Unsupported button')
    if action.name == 'click' and (('x' in a) != ('y' in a)): raise ValueError('Supply both x and y')
    if 'text' in a and (not isinstance(a['text'],str) or len(a['text']) > 4096): raise ValueError('text must be at most 4096 characters')
    if 'executable' in a and (not isinstance(a['executable'],str) or not a['executable']): raise ValueError('executable must be nonempty')
    if 'arguments' in a and (not isinstance(a['arguments'],list) or any(not isinstance(v,str) for v in a['arguments'])): raise ValueError('arguments must be a list of strings')

class ActionComputer:
    """Use as a context manager. Live access is explicitly enabled by the caller.

    Manual holds expire after 30 seconds by default. Explicit bounded sessions
    may opt into hold_timeout (1..1800s), or explicitly None for no expiry;
    F12 always stops this session, including non-expiring sessions.
    Success means input dispatched, not that a game completed the intended task.
    """
    def __init__(self, *, live=False, backend=None, audit_path=None, hold_timeout=30):
        if hold_timeout is not None and (isinstance(hold_timeout,bool) or not isinstance(hold_timeout,(int,float)) or not math.isfinite(hold_timeout) or not 1<=hold_timeout<=1800):
            raise ValueError('hold_timeout must be None or 1..1800 seconds')
        self.hold_timeout=None if hold_timeout is None else float(hold_timeout)
        self.live = live
        self.backend = backend if backend is not None else (WindowsBackend() if live else None)
        self.audit_path = Path(audit_path) if audit_path else None
        self.keys = set()
        self.buttons = set()
        self._held_since = None
        self._stop = threading.Event()
        self._closed = threading.Event()
        self._lock = threading.RLock()
        self._watcher = None
        if live:
            self._watcher = threading.Thread(target=self._watch,daemon=True)
            self._watcher.start()
    @property
    def stopped(self): return self._stop.is_set() or self._closed.is_set()

    def _watch(self):
        while not self._closed.wait(.01):
            try:
                expired = self.hold_timeout is not None and self._held_since is not None and time.monotonic()-self._held_since >= self.hold_timeout
                if self.backend.emergency_pressed() or expired:
                    self.stop()
                    return
            except Exception:
                self._stop.set()
                try: self.release_all()
                except Exception: pass
                return
    def _check(self):
        if self._closed.is_set() or self._stop.is_set(): raise RuntimeError('Operation session stopped')
        if self.live and self.backend.emergency_pressed():
            self._stop.set()
            raise RuntimeError('F12 emergency stop')
    def _wait(self,seconds):
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            self._check()
            self._stop.wait(min(.01,max(0,deadline-time.monotonic())))
        self._check()
    def _key(self,key,down):
        if down:
            self._check()
            if key in self.keys: return
            self.keys.add(key)
            if self._held_since is None: self._held_since = time.monotonic()
        self.backend.key(key,down)
        if not down:
            self.keys.discard(key)
            if not self.keys and not self.buttons: self._held_since = None
    def _button(self,button,down):
        if down:
            self._check()
            if button in self.buttons: return
            self.buttons.add(button)
            if self._held_since is None: self._held_since = time.monotonic()
        self.backend.button(button,down)
        if not down:
            self.buttons.discard(button)
            if not self.keys and not self.buttons: self._held_since = None
    def release_all(self):
        with self._lock:
            errors = []
            if self.live:
                for key in list(self.keys):
                    try: self._key(key,False)
                    except Exception as e: errors.append(str(e))
                for button in list(self.buttons):
                    try: self._button(button,False)
                    except Exception as e: errors.append(str(e))
            if errors: raise RuntimeError('Release failed: '+ '; '.join(errors))
    def stop(self):
        self._stop.set()
        self.release_all()
    def close(self):
        self._stop.set()
        try: self.release_all()
        finally:
            self._closed.set()
            if self._watcher and threading.current_thread() is not self._watcher:
                self._watcher.join(timeout=1)
    def __enter__(self): return self
    def __exit__(self,*unused): self.close()
    def _motion(self,dx,dy,duration,steps):
        previous_x = previous_y = 0
        for i in range(1,steps+1):
            self._check()
            x,y = round(dx*i/steps),round(dy*i/steps)
            self.backend.mouse(x-previous_x,y-previous_y)
            previous_x,previous_y = x,y
            self._wait(duration/steps)
    def _execute(self,name,a):
        pressed=[]
        try:
            for key in a.get('modifiers',[]):
                if key not in self.keys:
                    pressed.append(key)
                    self._key(key,True)
            if pressed: self._wait(.05)
            return self._execute_plain(name,a)
        finally:
            for key in reversed(pressed):
                if key in self.keys: self._key(key,False)

    def _execute_plain(self,name,a):
        if name == 'release_all': self.release_all()
        elif name == 'stop': self.stop()
        elif name == 'show_desktop': self.backend.show_desktop()
        elif name == 'windows': return {'windows':self.backend.windows()}
        elif name == 'cursor': return self.backend.cursor()
        elif name == 'window_resize_info': return self.backend.window_resize_info(a['handle'])
        elif name == 'resize_window': return self.backend.resize_window(a['handle'],a['width'],a['height'])
        elif name == 'focus': self.backend.focus(a['handle'])
        elif name == 'launch': return {'pid':self.backend.launch(a['executable'],a.get('arguments',[]))}
        elif name == 'wait': self._wait(a['duration'])
        elif name in ('key_down','key_up'): self._key(a['key'],name=='key_down')
        elif name in ('mouse_down','mouse_up'): self._button(a.get('button','left'),name=='mouse_down')
        elif name in ('press','hotkey','hold'):
            keys = [a['key']] if name == 'press' else a['keys']
            if set(keys) & self.keys: raise ValueError('Temporary hold overlaps an already held key')
            try:
                for key in keys: self._key(key,True)
                if name == 'hold': self._motion(a.get('dx',0),a.get('dy',0),a['duration'],a.get('steps',max(1,round(a['duration']*60))))
                else: self._wait(a.get('duration',.05))
            finally:
                for key in reversed(keys):
                    if key in self.keys: self._key(key,False)
        elif name == 'text':
            for char in a['text']:
                self._check()
                self.backend.text(char)
        elif name == 'move_to': self.backend.move_to(a['x'],a['y'])
        elif name == 'move_relative': self._motion(a['dx'],a['dy'],a.get('duration',0),a.get('steps',1))
        elif name == 'scroll': self.backend.mouse(flags=0x800,data=a['ticks']*120)
        elif name in ('click','drag'):
            button = a.get('button','left')
            if button in self.buttons: raise ValueError('Button already held')
            if name == 'click' and 'x' in a: self.backend.move_to(a['x'],a['y'])
            for i in range(a.get('count',1)):
                try:
                    self._button(button,True)
                    if name == 'drag':
                        start = self.backend.cursor()
                        steps = a.get('steps',30)
                        for j in range(1,steps+1):
                            self._check()
                            self.backend.move_to(round(start['x']+(a['x']-start['x'])*j/steps),round(start['y']+(a['y']-start['y'])*j/steps))
                            self._wait(a.get('duration',.5)/steps)
                    else: self._wait(a.get('duration',.03))
                finally:
                    if button in self.buttons: self._button(button,False)
                if i+1 < a.get('count',1): self._wait(a.get('interval',.1))
        return {}
    def perform(self,action):
        with self._lock:
            try:
                validate(action)
                if action.name not in ('stop','release_all'): self._check()
                data = self._execute(action.name,action.arguments) if self.live else {}
                if not self.live and action.name == 'stop': self._stop.set()
                result = SkillResult(Outcome.SUCCESS, {'action':action.name,'dry_run':not self.live, **data},'Input dispatched' if self.live else 'Action validated; simulation only')
            except Exception as error:
                try: self.release_all()
                except Exception as cleanup: error = RuntimeError(f'{error}; {cleanup}')
                result = SkillResult(Outcome.FAILURE,{'action':action.name,'dry_run':not self.live},str(error))
            if self.audit_path:
                try:
                    self.audit_path.parent.mkdir(parents=True,exist_ok=True)
                    with self.audit_path.open('a',encoding='utf-8') as stream:
                        stream.write(json.dumps({'time':datetime.now(UTC).isoformat(),'action':action.name,'outcome':result.outcome,'live':self.live},ensure_ascii=False)+'\n')
                except OSError as error:
                    self.stop()
                    return SkillResult(Outcome.FAILURE, result.data, f'Action may have executed; audit failed: {error}')
            return result
    def run_actions(self,actions):
        with self._lock:
            results = []
            try:
                actions = list(actions)
                if len(actions)>1000: raise ValueError('At most 1000 actions per batch')
                for action in actions: validate(action)
                for action in actions:
                    result = self.perform(action)
                    results.append(result)
                    if result.outcome != Outcome.SUCCESS: break
            finally: self.release_all()
            return results
