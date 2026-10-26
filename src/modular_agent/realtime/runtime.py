"""ROI capture and exclusive input; no OCR, UIA or model calls."""
import ctypes as C
from ctypes import wintypes as W
from collections import deque
import time
import mss
import numpy as np
from modular_agent.core import Action, Outcome

class WindowCapture:
    def __init__(self, handle):
        from modular_agent.computer.windows import WindowsBackend
        self.backend = WindowsBackend()
        self.api = self.backend.api
        self.handle = handle
        self.api.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
        self.api.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
        self.api.IsIconic.argtypes = [W.HWND]
        self.session = mss.mss()
    def bounds(self):
        if self.backend.emergency_pressed(): raise RuntimeError('F12_stop')
        if (not self.api.IsWindow(self.handle) or self.api.IsIconic(self.handle)
                or self.api.GetForegroundWindow() != self.handle):
            raise RuntimeError('window_unavailable_or_unfocused')
        rect, point = W.RECT(), W.POINT(0, 0)
        if not self.api.GetClientRect(self.handle, C.byref(rect)) or not self.api.ClientToScreen(self.handle, C.byref(point)):
            raise RuntimeError('window_bounds_failed')
        if rect.right <= 0 or rect.bottom <= 0: raise RuntimeError('empty_window')
        return point.x, point.y, rect.right, rect.bottom
    def grab(self, roi):
        bounds = self.bounds()
        x, y, w, h = bounds
        l, t, r, b = roi
        region = dict(left=x+round(l*w), top=y+round(t*h),
                      width=round(r*w)-round(l*w), height=round(b*h)-round(t*h))
        screen = self.session.monitors[0]
        if (region['left'] < screen['left'] or region['top'] < screen['top']
            or region['left']+region['width'] > screen['left']+screen['width']
            or region['top']+region['height'] > screen['top']+screen['height']):
            raise RuntimeError('roi_outside_desktop')
        image = np.asarray(self.session.grab(region))[:, :, :3].copy()
        if self.bounds() != bounds: raise RuntimeError('window_changed_during_capture')
        return image, bounds
    def close(self): self.session.close()

class InputLatch:
    def __init__(self, computer, live):
        self.computer, self.live = computer, live
        self.down = False
        self.changed = float('-inf')
    def set(self, down, now, minimum=0, force=False):
        if down == self.down or (not force and now-self.changed < minimum): return
        if self.live:
            result = self.computer.perform(Action('mouse_down' if down else 'mouse_up', arguments={'button':'left'}))
            if result.outcome != Outcome.SUCCESS: raise RuntimeError(result.message)
        self.down, self.changed = down, now

def run_loop(capture, program, computer, config, *, live=False, should_yield=lambda:False, progress=lambda text:None, boundary_probe=None):
    samples = deque(maxlen=600)
    latch = InputLatch(computer, live)
    start = time.perf_counter()
    count, previous, reason = 0, None, 'timeout'
    boundary_observation = None
    next_probe = start
    probe_count, probe_seconds = 0, 0.0
    try:
        while time.perf_counter()-start < config['timeout']:
            tick = time.perf_counter()
            if computer.stopped or should_yield():
                reason = 'cancelled'; break
            if boundary_probe is not None and program.state == 'waiting' and tick >= next_probe:
                probe_start = time.perf_counter()
                boundary_observation = boundary_probe()
                probe_seconds += time.perf_counter() - probe_start
                probe_count += 1
                next_probe = time.perf_counter() + 1.0
                if boundary_observation and boundary_observation.get('state') in ('continue', 'close', 'dismiss'):
                    reason = 'waiting_boundary_detected'
                    break
            image, bounds = capture.grab(program.roi())
            captured = time.perf_counter()
            if previous is not None and bounds != previous:
                latch.set(False, captured, force=True)
                program.reset_motion()
                if bounds[2:] != previous[2:]:
                    reason = 'window_resized_recalibrate'; break
            previous = bounds
            observation = program.detect(image)
            detected = time.perf_counter()
            decision = program.step(observation, detected, latch.down)
            controlled = time.perf_counter()
            if capture.bounds() != bounds:
                reason = 'window_changed_before_input'; break
            latch.set(decision['down'], controlled, config['minimum_hold'], decision.get('force',False))
            dispatched = time.perf_counter()
            count += 1
            samples.append(dict(capture_ms=(captured-tick)*1000, recognition_ms=(detected-captured)*1000,
                                control_ms=(controlled-detected)*1000, input_ms=(dispatched-controlled)*1000,
                                observation=observation, decision=decision, state=program.state))
            if decision.get('stop'):
                reason = decision['stop']; break
            if count % max(1, round(config['fps']*5)) == 0:
                progress(f'钓鱼状态 {program.state}；实际 {count/(dispatched-start):.1f} FPS')
            time.sleep(max(0, 1/config['fps']-(time.perf_counter()-tick)))
    except KeyboardInterrupt: reason = 'cancelled'
    except Exception as error: reason = 'exception: '+str(error)
    finally:
        try: computer.release_all()
        except Exception as error: reason += '; release_failed: '+str(error)
        try: capture.close()
        except Exception as error: reason += "; capture_close_failed: "+str(error)
    elapsed = time.perf_counter()-start
    return dict(outcome='unknown', verified=False, handoff='fishing_settlement', reason=reason,
                state=program.state, live=live, frames=count, elapsed_seconds=elapsed,
                boundary_observation=boundary_observation, boundary_probe_count=probe_count,
                boundary_probe_mean_ms=probe_seconds*1000/max(probe_count,1),
                actual_fps=count/max(elapsed,1e-9),
                timings_mean_ms={k:sum(s[k] for s in samples)/len(samples) for k in ('capture_ms','recognition_ms','control_ms','input_ms')} if samples else {},
                timing_samples=list(samples))
