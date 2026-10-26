"""Learning-only game integration. F8 arm, F9 reset, F12 stop. No game input in replay."""
import argparse
from contextlib import nullcontext
import hashlib
from collections import deque
from datetime import datetime
import json
import os
from pathlib import Path
import sys
import threading
import time
import cv2
import numpy as np
from game_jump_logic import JumpClock,RopeProgress,ROOT
from inference_helpers import composite
from inference_helpers import roi_bounds
from failure_capture import FailureRecorder
from counter_reader import counter_glyphs
from round_loop import RoundLoop

HERE=Path(__file__).resolve().parent
os.environ.setdefault('YOLO_CONFIG_DIR',str(HERE/'.ultralytics'))
sys.path.insert(0,str(ROOT/'src'))

class StageHint:
    """Existing local digit references, extended to three digits; no OCR service."""
    def __init__(self):
        self.shapes=counter_glyphs
        asset=json.loads((HERE/'count_digits_complete_v2.json').read_text(encoding='utf-8'))
        self.refs={k:[np.array(v,bool) for v in variants] for k,variants in asset['variants'].items()}
        self.pending=None;self.since=0.;self.stage=1;self.count=None
        self.pending_samples=0;self.last_pending=None
        self.count_reading=None;self.glyphs=[];self.digit_scores=[]
    def clear_pending(self):
        self.pending=None;self.pending_samples=0;self.last_pending=None
    def update(self,image,now):
        shapes=self.shapes(image);self.glyphs=shapes;self.count_reading=None;self.digit_scores=[]
        if not 1<=len(shapes)<=3:
            self.clear_pending();return self.stage
        digits=[]
        for shape in shapes:
            ranks=sorted([(max(np.count_nonzero(shape&r)/max(1,np.count_nonzero(shape|r)) for r in variants),k) for k,variants in self.refs.items()],reverse=True)
            self.digit_scores.append(dict(digit=ranks[0][1],score=float(ranks[0][0]),margin=float(ranks[0][0]-ranks[1][0])))
            if ranks[0][0]<.65 or ranks[0][0]-ranks[1][0]<.08:
                self.clear_pending();return self.stage
            digits.append(ranks[0][1])
        self.count=int(''.join(digits));self.count_reading=self.count;stage=sum(self.count>=n for n in [0,10,30,50,70])
        if stage<=self.stage:
            self.clear_pending();return self.stage
        if stage!=self.pending or self.last_pending is None or now-self.last_pending>.15:
            self.pending=stage;self.since=now;self.pending_samples=0
        self.pending_samples+=1;self.last_pending=now
        skipping=stage>self.stage+1
        if now-self.since>=(.6 if skipping else .2) and self.pending_samples>=(6 if skipping else 3):
            self.stage=stage;self.clear_pending()
        return self.stage

class Pulse:
    def __init__(self,backend):self.backend=backend;self.lock=threading.Lock();self.down=False;self.timer=None;self.event_callback=None
    def record_edge(self,down):
        if self.event_callback:self.event_callback(dict(time=time.perf_counter(),type='key_down' if down else 'key_up',key='space',down=down))
    def release(self):
        with self.lock:
            if self.down:self.backend.key('space',False);self.down=False;self.record_edge(False)
    def send(self,seconds):
        with self.lock:
            if self.down:return False
            self.backend.key('space',True);self.down=True;self.record_edge(True)
            self.timer=threading.Timer(seconds,self.release);self.timer.daemon=True;self.timer.start()
            return True
    def close(self):
        if self.timer:self.timer.cancel()
        self.release()

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',action='store_true',help='F8 enables actual Space pulses; otherwise judgment only')
    p.add_argument('--replay',type=Path)
    p.add_argument('--start',type=int,default=600)
    p.add_argument('--frames',type=int,default=180)
    p.add_argument('--window-handle',type=int)
    p.add_argument('--config',type=Path,default=HERE/'game_jump_config.json')
    p.add_argument('--preview',action='store_true')
    p.add_argument('--stop-file',type=Path)
    p.add_argument('--timeout-seconds',type=float,default=0)
    a=p.parse_args(argv)
    import math
    if not math.isfinite(a.timeout_seconds) or a.timeout_seconds<0:p.error('invalid timeout')
    deadline=time.monotonic()+a.timeout_seconds if a.timeout_seconds else math.inf
    if a.live and a.replay:p.error('Replay cannot send game input')
    if a.start<2 or a.frames<1:p.error('start must be >=2 and frames positive')
    config=json.loads(a.config.read_text(encoding='utf-8'));clock=JumpClock(config);stage_hint=StageHint();rope_progress=RopeProgress()
    from ultralytics import YOLO
    import torch
    if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable')
    weights=HERE/'engines/history-07-late-960-fp16-nms/history-07-late.engine'
    model=YOLO(weights,task='segment');seed=None
    def predict(im,net=model):
        r=net.predict(im,imgsz=960,rect=False,device=0,quantize=16,conf=config['confidence'],retina_masks=True,verbose=False)[0]
        return np.zeros(im.shape[:2],bool) if r.masks is None else r.masks.data.any(0).cpu().numpy().astype(bool)
    # Compile/warm before arming. No stale warmup image enters history.
    for _ in range(3):predict(np.zeros((540,880,3),np.uint8))
    history=deque(maxlen=2);capture=None;cap=None;pulse=None;backend=None
    out=ROOT/'runtime/jump-rope/sessions'/('game-jump-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));out.mkdir(parents=True,exist_ok=False)
    (out/'config.json').write_text(json.dumps(config,indent=2),encoding='utf-8')
    armed=False;previous_bounds=None;previous_time=None;last_status=0;frame=0;reason='finished';pressed={}
    if a.replay:
        seed_path=HERE/'runs/temporal-control-05/weights/last.pt'
        if not seed_path.is_file():seed_path=HERE/'runs/temporal-history-07-late/weights/last.pt'
        seed=YOLO(seed_path)
        from live_video_preview import Engine
        from types import SimpleNamespace
        replay=Engine(SimpleNamespace(video=a.replay,weights=weights,history=False))
        for f in [a.start-2,a.start-1]:
            im=replay.read(f);x0,y0,x1,y1=roi_bounds(im.shape);history.append(predict(im[y0:y1,x0:x1],seed))
        armed=True
    else:
        from modular_agent.computer.windows import WindowsBackend
        from modular_agent.realtime.keyboard import GuardedCapture
        backend=WindowsBackend()
        matches=[w for w in backend.windows() if w['title'].lower()=='hololive-dreams']
        handle=a.window_handle
        if handle is None:
            if len(matches)!=1:raise RuntimeError('未找到唯一hololive-dreams窗口，请启动游戏或指定--window-handle')
            handle=matches[0]['handle']
        capture=GuardedCapture(handle,[(.3,.5),(.55,.5),(.8,.5)])
        pulse=Pulse(backend)
        print('模型就绪。切回游戏：F8启停，F9重置，F10保存片段，F12退出。'+('实际按键模式' if a.live else '仅判断模式'),flush=True)
    round_loop=None;loop_action={'block_jump':False};last_loop_check=-100.
    if a.live and not a.replay and config.get('round_loop',{}).get('enabled',False):
        loop_settings=config['round_loop']
        round_loop=RoundLoop(ROOT/loop_settings.get('output_dir','runtime/jump-rope/round-scores'),loop_settings)
        print('自动循环已启用：结算→奖励→活动结果→游玩；每局分数保存在 '+str(round_loop.output),flush=True)
    failure=None
    failure_settings=config.get('failure_capture',{})
    if failure_settings.get('enabled',False):
        metadata=dict(run=str(out),config=config,weights=str(weights),engine_sha256=hashlib.sha256(weights.read_bytes()).hexdigest(),gpu=torch.cuda.get_device_name(0),torch=torch.__version__,opencv=cv2.__version__,python=sys.version,source_time_basis='recorded_video_timestamps' if a.replay else 'monotonic_clock',code_sha256={name:hashlib.sha256((HERE/name).read_bytes()).hexdigest() for name in ('game_jump_live.py','game_jump_logic.py','failure_capture.py','counter_reader.py','count_digits_complete_v2.json','round_loop.py')})
        failure=FailureRecorder(ROOT/failure_settings.get('output_dir','runtime/jump-rope/failure-clips'),failure_settings,metadata)
        if pulse:pulse.event_callback=failure.record_input
        print(f'自动片段记录：停滞{failure.detector.stall:g}秒触发；F10手动保存。' if failure.auto_detect else f'手动片段记录：仅F10保存最近{failure.manual_seconds:g}秒，自动判定和F9补存已关闭。',flush=True)
    try:
        with ((out/'events.jsonl').open('w',encoding='utf-8') if config.get('save_full_events',False) else nullcontext(None)) as log:
            while True:
                if (a.stop_file and a.stop_file.exists()) or time.monotonic()>=deadline:
                    reason='cancelled_or_timeout';break
                if a.replay:
                    if frame>=a.frames:break
                    index=a.start+frame
                    if index>=replay.count:break
                    image=replay.read(index);now=replay.seconds(index);bounds=None;capture_started=None;capture_completed=None
                else:
                    if backend.emergency_pressed():reason='F12_stop';break
                    for vk in [119,120,121]:
                        down=bool(backend.api.GetAsyncKeyState(vk)&0x8000)
                        if down and not pressed.get(vk):
                            if vk==121:
                                if failure:failure.manual_save()
                                pressed[vk]=down
                                continue
                            if vk==120 and failure and failure.auto_detect and failure.settings.get('save_on_reset',True) and failure.detector.changes>=failure.detector.needed and not failure.detector.latched:
                                failure.manual_save('manual_reset_F9')
                            armed=not armed if vk==119 else False
                            pulse.release();clock.reset();stage_hint=StageHint()
                            if round_loop:round_loop.reset_detection();last_loop_check=-100.
                            if vk==120:rope_progress=RopeProgress()
                            else:rope_progress.previous=None
                            clock.set_stage(config['stage'] or rope_progress.stage);history.clear();previous_time=None
                            if failure and (armed or vk==120):failure.reset()
                            print('运行中' if armed else '已暂停（F8继续）',flush=True)
                        pressed[vk]=down
                    if not armed:time.sleep(.01);continue
                    capture_started=time.perf_counter();image,bounds=capture.grab((0,0,1,1));capture_completed=time.perf_counter();now=(capture_started+capture_completed)/2
                    if previous_bounds is not None and bounds!=previous_bounds:
                        pulse.release();clock.reset();history.clear();armed=False
                        if failure:failure.reset()
                        print('窗口变化，已暂停；F8重新开始',flush=True);continue
                    previous_bounds=bounds
                if round_loop:
                    if now-last_loop_check>=.12:
                        loop_action=round_loop.update(image,now);last_loop_check=now
                        if loop_action['new_round']:
                            pulse.release();clock.reset();stage_hint=StageHint();rope_progress=RopeProgress();clock.set_stage(config['stage'] or 1);history.clear();previous_time=None
                            if failure:failure.reset()
                            print('new_round | rope_count=0 | stage=1',flush=True)
                        if loop_action['click']:
                            pulse.release()
                            if capture.bounds()!=bounds:raise RuntimeError('window_changed_before_menu_input')
                            x,y=loop_action['click'];left,top,width,height=bounds
                            backend.move_to(left+round(x*width),top+round(y*height))
                            if capture.bounds()!=bounds:raise RuntimeError('window_changed_before_menu_click')
                            backend.button('left',True)
                            try:time.sleep(.04)
                            finally:backend.button('left',False)
                            print('round_loop | click='+str(loop_action['screen']),flush=True)
                    if loop_action['block_jump']:
                        pulse.release();history.clear();previous_time=None;rope_progress.previous=None
                        time.sleep(.01);continue
                started=time.perf_counter();roi=roi_bounds(image.shape);x0,y0,x1,y1=roi;crop=image[y0:y1,x0:x1]
                if previous_time is not None and now-previous_time>config['history_reset_seconds']:history.clear()
                while len(history)<2:history.append(np.zeros(crop.shape[:2],bool))
                mask=predict(composite(crop,*history));history.append(mask.copy());previous_time=now
                decision_at=time.perf_counter();dispatch=now if a.replay else decision_at
                stage_hint.update(image,now)
                # Apply progress from the previous frame; the current decision keeps its stage.
                if not config['stage']:
                    observed_stage=rope_progress.stage
                    if observed_stage!=clock.active_stage:print(f'stage_switch | {clock.active_stage}->{observed_stage} | rope_count={rope_progress.count}',flush=True)
                    clock.set_stage(observed_stage)
                decision=clock.update(now,mask,image.shape,roi,dispatch)
                template=clock.templates[clock.selected] if clock.selected is not None else None
                rope_progress.update(now,decision,template)
                fresh=a.replay or decision_at-now<=config['max_frame_age_seconds']
                request=decision['trigger'] and bool(fresh)
                sent=False
                if request:
                    if a.live:
                        if capture.bounds()!=bounds:raise RuntimeError('window_changed_before_input')
                        sent=pulse.send(config['pulse_seconds'])
                    if not a.live or sent:clock.on_trigger(now)
                row=dict(rope_count=rope_progress.count,stage_source="rope_crossings",frame=(a.start+frame if a.replay else frame),time=now,pixels=int(mask.sum()),live=a.live,stage=clock.active_stage,count=stage_hint.count,
                         inference_and_logic_ms=(time.perf_counter()-started)*1000,fresh=bool(fresh),requested=bool(request),sent=sent,decision=decision,roi=list(roi),client_bounds=list(bounds) if bounds is not None else None,frame_age_ms=0. if a.replay else (decision_at-now)*1000,capture_started=capture_started,capture_completed=capture_completed,dispatch_time=dispatch,key_pulse_active=bool(pulse and pulse.down),count_reading=stage_hint.count_reading,count_digit_scores=stage_hint.digit_scores,count_glyphs=len(stage_hint.glyphs))
                if failure:failure.observe(image,mask,row,stage_hint.glyphs,stage_hint.count_reading)
                if log:
                    log.write(json.dumps(row,ensure_ascii=False)+'\n')
                    if frame%60==0:log.flush()
                if a.preview:
                    view=image.copy();view[y0:y1,x0:x1][mask]=(255,230,0)
                    cv2.putText(view,f'{decision["status"]}  eta={decision["eta"]}  jumps={clock.jumps}',(15,25),cv2.FONT_HERSHEY_SIMPLEX,.55,(0,255,255),1)
                    cv2.imshow('YOLO07 jump trial',cv2.resize(view,(960,540)))
                    if cv2.waitKey(1)&255==27:reason='preview_escape';break
                if time.perf_counter()-last_status>=1:
                    print(f'{decision["status"]} | {decision["template"]} | eta={decision["eta"]} | jumps={clock.jumps}',flush=True);last_status=time.perf_counter()
                frame+=1
    except KeyboardInterrupt:reason='keyboard_interrupt'
    except Exception as error:reason=str(error);raise
    finally:
        if pulse:pulse.close()
        if capture:capture.close()
        if failure:failure.close()
        if a.replay:replay.close()
        if a.preview:cv2.destroyAllWindows()
        (out/'summary.json').write_text(json.dumps(dict(reason=reason,frames=frame,jumps=clock.jumps,live=a.live,weights=str(weights),replay=str(a.replay) if a.replay else None,verified=False,failure_capture=failure.stats() if failure else None),indent=2),encoding='utf-8')
        print('日志：'+str(out),flush=True)
    return dict(outcome='unknown',verified=False,reason=reason,frames=frame,jumps=clock.jumps,trace_directory=str(out))

if __name__=='__main__':main()
