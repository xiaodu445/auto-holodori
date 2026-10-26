"""Exclusive W/Space + mouse adapter for camera-controlled routes."""
import math
import time
import threading
from dataclasses import replace
from pathlib import Path
from modular_agent.core import Action,Outcome
from .patrol import ROOT,read_json,GuardedPulseExecutor


def camera_calibration(path=None):
    if path is None:
        candidates=sorted((ROOT/'runtime/patrol/motion-probes').glob('*/camera-calibration.json'),key=lambda p:p.stat().st_mtime,reverse=True)
    else:candidates=[Path(path)]
    for candidate in candidates:
        try:
            value=read_json(candidate)
            slope=value.get('degrees_per_count',0);protocol=value.get('protocol',{})
            if value.get('full_turn_observed') and math.isfinite(slope) and .005<=abs(slope)<=2 and protocol.get('mouse_mode')=='continuous' and protocol.get('requested_counts_per_second')==240:
                return candidate,value
        except (OSError,ValueError,TypeError):
            if path is not None:raise ValueError('所选镜头标定文件无效')
    raise ValueError('缺少完整连续转镜头标定，请先用镜头标定工具测一圈')


class RouteFrameGuard:
    """Keep the original semantic age limit; throttle only duplicate HUD grabs."""
    def __init__(self,capture,bounds,gate,cancelled,*,clock=time.perf_counter):
        self.capture=capture;self.bounds=bounds;self.gate=gate;self.cancelled=cancelled;self.clock=clock
        self.stamp=-math.inf;self.ok=False;self.last_hud=-math.inf

    def update(self,stamp,ok):self.stamp=stamp;self.ok=ok;self.last_hud=stamp

    def __call__(self):
        self.check_fresh()
        if self.clock()-self.last_hud>=.08:
            image,bounds=self.capture.grab((0,0,1,1))
            if bounds!=self.bounds:raise RuntimeError('window_moved_or_resized')
            if hasattr(self.gate,'movement_hud'):ok,_=self.gate.movement_hud(image)
            else:
                ok,_=self.gate.hud.read(image)
                ok=ok and self.gate.enabled(image)
            if not ok:raise RuntimeError('movement_hud_lost_or_disabled')
            self.last_hud=self.clock()
        self.check_fresh()

    def check_fresh(self):
        """Thread-safe OS checks; image capture stays on the main thread."""
        if self.cancelled():raise RuntimeError('stop_file_or_cancelled')
        if self.capture.bounds()!=self.bounds:raise RuntimeError('window_moved_or_resized')
        if not self.ok or not 0<=self.clock()-self.stamp<=.5:raise RuntimeError('stale_or_blocked_scene')


class GuardedCameraExecutor:
    def __init__(self,computer,check,*,clock=time.perf_counter,sleep=time.sleep):
        self.computer=computer;self.check=check;self.clock=clock;self.sleep=sleep
        self.dispatched_actions=0
        owner=self
        class CountedComputer:
            def __getattr__(self,name):return getattr(computer,name)
            def perform(self,action):
                result=computer.perform(action)
                if result.outcome==Outcome.SUCCESS:owner.dispatched_actions+=1
                return result
        self.pulse=GuardedPulseExecutor(CountedComputer(),check,live=True,clock=clock,sleep=sleep)

    def prepare(self,decision,*,observed_at):
        """Reserve time for guards and release without relaxing the 0.5s age."""
        age=self.clock()-observed_at
        remaining=.5-age-.14
        if age<0 or remaining<.05:return None
        if decision.kind=='turn':
            rate=decision.counts_per_second
            if rate not in (240,7200):raise ValueError('invalid camera rate')
            count=min(abs(decision.mouse_dx),int(remaining*rate))
            if count<1:return None
            count=count if decision.mouse_dx>0 else -count
            return replace(decision,mouse_dx=count,duration=abs(count)/rate)
        if decision.kind=='jump':return decision if decision.duration<=remaining else None
        if decision.kind=='move':return replace(decision,duration=min(decision.duration,remaining))
        return decision

    def execute(self,decision,*,observed_at):
        self.last_decision=decision
        if decision.kind in ('move','jump'):
            expected=('w',) if decision.kind=='move' else ('w','space')
            if decision.keys!=expected:raise ValueError('镜头路线只允许W，跳跃只允许W+Space')
            return self.pulse.execute(decision,observed_at=observed_at)
        if decision.kind!='turn':return False
        count=decision.mouse_dx
        rate=decision.counts_per_second
        maximum=3600 if rate==7200 else 72
        if rate not in (240,7200) or type(count) is not int or not 1<=abs(count)<=maximum or decision.keys:raise ValueError('invalid camera turn')
        if self.computer.keys or self.computer.buttons:raise RuntimeError('turn requires released keys/buttons')
        self.check()
        if not 0<=self.clock()-observed_at<=.5:raise RuntimeError('stale camera observation')
        start=self.clock();sent=0
        try:
            while sent<abs(count):
                # Wall-clock guard/capture cost is not mouse motion time.
                # Finish this batch early and report actual counts rather than
                # spending the entire frame budget trying to catch up.
                if sent and self.clock()-observed_at>=.36:break
                self.check()
                if self.clock()-observed_at>=.40:break
                if self.computer.stopped:raise RuntimeError('cancelled')
                if self.clock()-start>.6:raise RuntimeError('camera_input_deadline')
                due=min(abs(count),int((self.clock()-start)*rate))
                step=min(128 if rate==7200 else 4,max(0,due-sent))
                if step:
                    result=self.computer.perform(Action('move_relative',arguments=dict(dx=step if count>0 else -step,dy=0)))
                    if result.outcome!=Outcome.SUCCESS:raise RuntimeError(result.message)
                    self.dispatched_actions+=1
                    sent+=step
                self.sleep(.01)
        finally:self.computer.release_all()
        self.last_decision=replace(decision,mouse_dx=sent if count>0 else -sent,duration=self.clock()-start)
        self.check();return sent>0


class ContinuousRouteExecutor:
    """Renewable visual lease: keep W down while the main loop observes.

    A separate 100Hz worker owns cruise input. No image capture runs here.
    Lease expiry releases W even if recognition/the preview blocks forever.
    """
    def __init__(self,computer,guard,*,clock=time.perf_counter):
        self.computer=computer;self.guard=guard;self.clock=clock
        self.legacy=GuardedCameraExecutor(computer,guard,clock=clock)
        self._lock=threading.RLock();self._closed=threading.Event()
        self.command=None;self.error=None;self.cruise_actions=0;self.expirations=0
        self.worker=threading.Thread(target=self._run,daemon=True)
        try:self.worker.start()
        except BaseException:
            self._closed.set();computer.release_all();raise

    @property
    def dispatched_actions(self):return self.cruise_actions+self.legacy.dispatched_actions

    def _send(self,action):
        result=self.computer.perform(action)
        if result.outcome!=Outcome.SUCCESS:raise RuntimeError(result.message)
        self.cruise_actions+=1

    def prepare(self,decision,*,observed_at):
        if self.error:raise RuntimeError(self.error)
        if decision.kind!='cruise':return self.legacy.prepare(decision,observed_at=observed_at)
        remaining=min(decision.duration,.5-(self.clock()-observed_at))
        if remaining<.06:return None
        return replace(decision,duration=remaining)

    def execute(self,decision,*,observed_at):
        if decision.kind!='cruise':
            self.pause()
            result=self.legacy.execute(decision,observed_at=observed_at)
            self.last_decision=self.legacy.last_decision
            return result
        self.last_decision=decision
        rate=decision.counts_per_second
        maximum=360 if rate==2400 else 72
        if rate not in (240,2400) or decision.keys!=('w',) or type(decision.mouse_dx) is not int or abs(decision.mouse_dx)>maximum:
            self.pause();raise ValueError('invalid continuous W steering')
        if not math.isfinite(decision.duration) or not 0<decision.duration<=.5:
            self.pause();raise ValueError('invalid cruise lease')
        with self._lock:
            if self.error:raise RuntimeError(self.error)
            self.guard.check_fresh()
            now=self.clock()
            deadline=min(observed_at+.5,now+decision.duration)
            if deadline-now<.05:return False
            if self.computer.buttons or self.computer.keys-{'w'}:raise RuntimeError('unexpected_held_input')
            try:
                if 'w' not in self.computer.keys:self._send(Action('key_down',arguments=dict(key='w')))
            except Exception as error:
                self.error=str(error);self.pause();raise
            self.command=dict(deadline=deadline,remaining=decision.mouse_dx,last=now,credit=0.,rate=rate)
        return True

    def pause(self):
        with self._lock:
            self.command=None
            self.computer.release_all()

    def _tick(self):
        with self._lock:
            if self.command is None:return
            now=self.clock();command=self.command
            if now>=command['deadline']:
                self.expirations+=1;self.pause();return
            try:
                self.guard.check_fresh()
                if self.computer.stopped:raise RuntimeError('cancelled')
                rate=command['rate'];maximum=24 if rate==2400 else 4
                command['credit']=min(float(maximum),command['credit']+max(0,now-command['last'])*rate)
                command['last']=now
                step=min(abs(command['remaining']),int(command['credit']))
                if step:
                    dx=step if command['remaining']>0 else -step
                    self._send(Action('move_relative',arguments=dict(dx=dx,dy=0)))
                    command['remaining']-=dx;command['credit']-=step
            except Exception as error:
                self.error=str(error);self.pause()

    def _run(self):
        try:
            while not self._closed.wait(.01):self._tick()
        except Exception as error:self.error=str(error)
        finally:self.pause()

    def close(self):
        self._closed.set();self.pause();self.worker.join(timeout=1)
        if self.worker.is_alive():raise RuntimeError('cruise_worker_did_not_stop')
