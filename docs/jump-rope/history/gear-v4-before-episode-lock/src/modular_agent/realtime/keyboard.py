"""Shared exclusive keyboard real-time loop; synchronous capture has no frame queue."""
from collections import deque
import time
import numpy as np
from modular_agent.core import Action, Outcome
from modular_agent.realtime.runtime import WindowCapture


class KeyLatch:
    def __init__(self, computer, live, key):
        self.computer, self.live, self.key = computer, live, key
        self.down = False
        self.events = []

    def set(self, down):
        if down == self.down: return
        before = time.perf_counter()
        if self.live:
            result = self.computer.perform(Action('key_down' if down else 'key_up', arguments={'key': self.key}))
            if result.outcome != Outcome.SUCCESS: raise RuntimeError(result.message)
        after = time.perf_counter()
        self.events.append(dict(down=down, started=before, dispatched=after, simulated=not self.live))
        self.down = down


class GuardedCapture(WindowCapture):
    """Cheap root-window hit tests at the domain's essential tracking points."""
    def __init__(self, handle, points):
        super().__init__(handle)
        from ctypes import wintypes as W
        self.api.WindowFromPoint.argtypes = [W.POINT]
        self.api.WindowFromPoint.restype = W.HWND
        self.api.GetAncestor.argtypes = [W.HWND, W.UINT]
        self.api.GetAncestor.restype = W.HWND
        self.points = points

    def bounds(self):
        from ctypes import wintypes as W
        bounds = super().bounds()
        x, y, w, h = bounds
        for fx, fy in self.points:
            handle = self.api.WindowFromPoint(W.POINT(x+round(fx*w), y+round(fy*h)))
            root = self.api.GetAncestor(handle, 2) or handle
            if root != self.handle: raise RuntimeError('tracking_region_occluded')
        return bounds


def run_key_loop(capture, vision, controller, computer, config, *, live=False,
                 should_yield=lambda: False, progress=lambda text: None, on_tracking_loss=None, on_frame=None):
    if live and not computer.live: raise ValueError('live requires live ActionComputer')
    if computer.keys or computer.buttons: raise ValueError('exclusive component requires released inputs')
    latch = KeyLatch(computer, live, 'space')
    samples = deque(maxlen=600)
    diagnostic_frames = deque(maxlen=8)
    totals = {k: 0.0 for k in ('capture_ms', 'recognition_ms', 'control_ms', 'input_ms', 'frame_age_ms','preview_submit_ms')}
    start = time.perf_counter(); previous = None; count = 0; reason = 'timeout'
    next_status = start+3; last_tick = None
    try:
        while time.perf_counter()-start < config['timeout']:
            tick = time.perf_counter()
            if computer.stopped or should_yield(): reason = 'cancelled'; break
            image, bounds = capture.grab(config['roi'])
            captured = time.perf_counter()
            if previous is not None and bounds != previous:
                latch.set(False); controller.reset_motion(); vision.reset()
            previous = bounds
            if image.shape[1] > config['analysis_width']:
                import cv2
                image = cv2.resize(image, (config['analysis_width'], round(image.shape[0]*config['analysis_width']/image.shape[1])))
            # A bounded in-memory sample, no disk work in the real-time path.
            if on_tracking_loss is not None and count % 6 == 0:
                diagnostic_frames.append((image.copy(),captured,list(bounds)))
            observation = vision.detect(image,timestamp=captured)
            detected = time.perf_counter()
            decision = controller.step(observation, captured, latch.down, frame_age=detected-tick)
            if hasattr(controller,'debug_snapshot'):decision['controller_debug']=controller.debug_snapshot()
            controlled = time.perf_counter()
            if capture.bounds() != bounds: reason = 'window_changed_before_input'; break
            if decision.get('stop') or controlled-tick > config['max_frame_age']:
                decision['down'] = False
            latch.set(decision['down'])
            dispatched = time.perf_counter()
            preview_started=time.perf_counter()
            if on_frame is not None:on_frame(image,observation,decision,bounds,(count+1)/max(dispatched-start,1e-9))
            preview_ms=(time.perf_counter()-preview_started)*1000 if on_frame is not None else 0.0
            timings = dict(preview_submit_ms=preview_ms,capture_ms=(captured-tick)*1000, recognition_ms=(detected-captured)*1000,
                           control_ms=(controlled-detected)*1000, input_ms=(dispatched-controlled)*1000,
                           frame_age_ms=(dispatched-tick)*1000)
            for key, value in timings.items(): totals[key] += value
            count += 1
            samples.append(dict(client_bounds=list(bounds),roi=list(config["roi"]),capture_started=tick, captured=captured, recognized=detected,
                                controlled=controlled, dispatched=dispatched,
                                interval_ms=None if last_tick is None else (tick-last_tick)*1000,
                                **timings, observation=observation, decision=decision))
            last_tick = tick
            if decision.get('stop'): reason = decision['stop']; break
            if dispatched >= next_status:
                if config.get('phase_gear'):
                    phase=observation.get('phase_estimate',{})
                    progress(f'跳绳模板 {observation.get("motion_state")}；{count/(dispatched-start):.1f} FPS；模型速度={phase.get("clock_rate",0):.3f}圈/秒；挡位={phase.get("speed_gear")}；视觉支持={observation.get("rope_valid")}；来源={phase.get("continuation")}；只判断')
                elif config.get('phase_state'):
                    phase=observation.get('phase_estimate',{})
                    mode=observation.get('motion_state')
                    label={'rotation_forward':'正摇','rotation_reverse':'反摇','low_swing':'低空左右摇'}.get(mode,mode)
                    unit='坐标/秒' if mode=='low_swing' else '圈/秒'
                    progress(f'跳绳 {label} / {controller.state}；{count/(dispatched-start):.1f} FPS；速度={phase.get("rate",0):.3f}{unit}；视觉支持={observation.get("rope_valid")}；来源={phase.get("continuation")}；恢复={observation.get("reacquisitions",0)}；只判断')
                elif config.get('phase_rope'):
                    phase=observation.get('phase_estimate',{})
                    progress(f'跳绳阶段 {controller.state}；{count/(dispatched-start):.1f} FPS；阶段={phase.get("phase",0):.3f} 速度={phase.get("rate",0):.3f}圈/秒；置信={phase.get("confidence",0):.3f}；视觉支持={observation.get("rope_valid")}；只判断')
                else:
                    progress(f'跳绳 {controller.state} / {decision.get('mode',controller.mode)}；{count/(dispatched-start):.1f} FPS；角色={observation.get("avatar_valid")} 绳子={observation.get("rope_valid")}；请求跳跃={controller.jumps}；输入抑制：{decision.get("input_inhibited")}')
                next_status = dispatched+3
            time.sleep(max(0, 1/config['fps']-(time.perf_counter()-tick)))
    except KeyboardInterrupt: reason = 'cancelled'
    except Exception as error: reason = 'exception: '+str(error)
    finally:
        try: computer.release_all()
        except Exception as error: reason += '; release_failed: '+str(error)
        try: capture.close()
        except Exception as error: reason += '; capture_close_failed: '+str(error)
    elapsed = time.perf_counter()-start
    diagnostic_error=None
    tracking_unavailable = bool(samples and samples[-1]['decision'].get('missing_features'))
    if on_tracking_loss is not None and diagnostic_frames and (reason in ('recognition_lost','initial_recognition_unavailable') or tracking_unavailable):
        try: on_tracking_loss(list(diagnostic_frames))
        except Exception as error: diagnostic_error=str(error)
    outcome = 'failure' if reason == 'damage_zero_miss_goal_failed' else 'unknown'
    if reason == 'failure': outcome = 'failure'
    # Goal success requires a verified 999 count and zero damage from a separate boundary observer.
    return dict(outcome=outcome, verified=False, handoff='jump_rope_boundary', reason=reason,
                state=controller.state, mode=controller.mode, live=live, frames=count,
                missing_features=samples[-1]['decision'].get('missing_features',[]) if samples else [],
                diagnostic_error=diagnostic_error,
                jumps_requested=controller.jumps, crossings_observed=controller.crossings,
                elapsed_seconds=elapsed, actual_fps=count/max(elapsed, 1e-9),
                timings_mean_ms={k: v/max(count, 1) for k,v in totals.items()},
                timings_recent_p95_ms={k:float(np.percentile([s[k] for s in samples],95)) for k in totals} if samples else {},
                recent_interval_p95_ms=float(np.percentile([s['interval_ms'] for s in samples if s['interval_ms'] is not None],95)) if len(samples)>1 else None,
                input_events=latch.events, timing_samples=list(samples))
