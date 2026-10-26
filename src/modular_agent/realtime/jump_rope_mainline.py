"""Opt-in mainline input trial: causal cues, template timing and short pulses."""
import json
import math
from pathlib import Path
import queue
import threading
import time
import cv2
import numpy as np
from modular_agent.realtime.audio_cues import features, dtw_distance, cue_effect, low_entry_authorized
from modular_agent.realtime.loopback_audio import LoopbackAudio, block_timing
from modular_agent.realtime.jump_rope_count_hint import CountThirtyShift
from modular_agent.realtime.jump_rope_start_gate import GoStartGate, waiting_observation


class MainlineAudio(LoopbackAudio):
    """Bounded asynchronous trailing-window matcher. Never records a microphone."""
    def start_cues(self, templates, policy):
        self.templates=templates; self.policy=policy
        self.stop_event=threading.Event(); self.pending=queue.Queue(maxsize=2)
        self.results=queue.Queue(maxsize=16); self.started_at=None
        self.buffer=np.empty(0,dtype=np.float32); self.last_end=None; self.last_probe=-math.inf
        self.last_event=-math.inf; self.dropped=0
        def process():
            while not self.stop_event.is_set():
                try: window,end=self.pending.get(timeout=.1)
                except queue.Empty:continue
                try:
                    f=features(window);scores={};prefix_scores={}
                    for template in self.templates:
                        source=np.asarray(template['features']);label=template['label'];n=len(source)
                        value=dtw_distance(f[-n::3],source[::3]);scores[label]=min(scores.get(label,math.inf),value)
                        for length in (.25,.4,.6):
                            n=round(length/.01)
                            value=dtw_distance(f[-n::2],source[:n:2]);prefix_scores[label]=min(prefix_scores.get(label,math.inf),value)
                    def ranked(values,threshold,margin):
                        order=sorted(values.items(),key=lambda p:p[1]);label,d=order[0];gap=order[1][1]-d
                        accepted=label if d<=threshold and gap>=margin else None
                        return dict(time=end,label=accepted,distance=d,margin=gap,scores=values,**cue_effect(accepted))
                    full=ranked(scores,policy['threshold'],policy['margin'])
                    prefix=ranked(prefix_scores,.22,.05)
                    event=None
                    if full['label'] and end-self.last_event>=policy['cooldown_seconds']:
                        event=full;self.last_event=end
                    item=dict(event=event,prefix=prefix,probe=full)
                    try:self.results.put_nowait(item)
                    except queue.Full:
                        self.errors.append('audio_result_overflow');self.stop_event.set()
                except Exception as error:self.errors.append(str(error));self.stop_event.set()
        self.worker=threading.Thread(target=process,daemon=True);self.worker.start()
        def callback(data,frames,info,status):
            now=time.perf_counter();meta=block_timing(info,now,frames,self.rate,0);end=meta['t']+meta['duration']
            if status:
                self.errors.append('audio_stream_status_'+str(status));self.stop_event.set();return (None,self.pa.paAbort)
            if self.last_end is not None and abs(meta['t']-self.last_end)>.08:self.buffer=np.empty(0,dtype=np.float32)
            self.last_end=end
            samples=np.frombuffer(data,dtype='<i2').reshape(-1,self.channels).mean(axis=1)/32768
            self.buffer=np.concatenate((self.buffer,samples))[-round(self.rate*2.6):]
            if self.started_at is not None and end-2.6>=self.started_at and len(self.buffer)>=round(self.rate*2.6) and end-self.last_probe>=.08:
                self.last_probe=end
                # Same 63-tap antialias filter and 16kHz features as the offline review.
                x=self.buffer.copy()
                if self.rate>16000:
                    cutoff=7000/self.rate;kernel=np.sinc((np.arange(63)-31)*2*cutoff)*np.hamming(63);kernel/=kernel.sum();x=np.convolve(x,kernel,mode='same')
                x=np.interp(np.arange(round(len(x)*16000/self.rate))*self.rate/16000,np.arange(len(x)),x).astype(np.float32)
                try:self.pending.put_nowait((x,end))
                except queue.Full:
                    try:self.pending.get_nowait()
                    except queue.Empty:pass
                    self.dropped+=1
                    try:self.pending.put_nowait((x,end))
                    except queue.Full:pass
            return (None,self.pa.paAbort if self.stop_event.is_set() else self.pa.paContinue)
        try:
            self.stream=self.host.open(format=self.pa.paInt16,channels=self.channels,rate=self.rate,input=True,input_device_index=self.device['index'],frames_per_buffer=1024,stream_callback=callback,start=False)
            self.stream.start_stream()
        except BaseException:self.close();raise
    def close(self):
        if getattr(self,'closed',False):return
        self.closed=True
        if hasattr(self,'stop_event'):self.stop_event.set()
        try:
            if self.stream:self.stream.stop_stream();self.stream.close();self.stream=None
        finally:
            if self.worker:self.worker.join(timeout=3);self.worker=None
            self.host.terminate()


class AudioPolicy:
    """Same candidate-only cue policy as the approved offline mainline."""
    def __init__(self,bank,policy):
        self.bank=bank;self.policy=policy;self.event=None;self.prefix=None;self.probe=None
        self.original=bank.choose;bank.choose=self.choose
    def choose(self,now,dt,*args,**kwargs):
        bank=self.bank;saved={p.key:p.score for p in bank.items};e=self.event;prefix=self.prefix
        bank.speed_audio_hint=e
        active=next((p for p in bank.items if p.key==bank.active),None)
        authorized=low_entry_authorized(e,now) or low_entry_authorized(prefix,now,lifetime=.40,threshold=.22,margin=.05)
        if active and active.mode!='low_swing' and not authorized:
            for p in bank.items:
                if p.mode=='low_swing':p.score=-1.
        if e and e['motion_hint'] and 0<=now-e['time']<=self.policy['hint_seconds']:
            for p in bank.items:
                match=p.mode=='low_swing' if e['motion_hint']=='low_swing' else p.mode!='low_swing' and bank.role(p)==e['motion_hint']
                if match:p.score+=self.policy['soft_score_bonus']*(1-(now-e['time'])/self.policy['hint_seconds'])
        confirmation=bank.c['confirmation_seconds'];low=[p for p in bank.items if p.mode=='low_swing' and p.visual]
        if active and active.mode!='low_swing' and low and low_entry_authorized(prefix,now,lifetime=.40,threshold=.10,margin=.08) and max(p.score for p in low)>active.score+.10:bank.c['confirmation_seconds']=min(confirmation,.035)
        try:return self.original(now,dt,*args,**kwargs)
        finally:
            bank.c['confirmation_seconds']=confirmation
            for p in bank.items:
                if p.key in saved:p.score=saved[p.key]


class MainlineVision:
    def __init__(self,vision,config,audio,policy):
        self.vision=vision;self.c=config;self.audio=audio
        self.policy=AudioPolicy(vision.bank,policy);self.reset_gate()
    def reset_gate(self):
        self.gate=GoStartGate(roi=self.c['roi'])
        self.policy.event=self.policy.prefix=self.policy.probe=None
        self.audio.started_at=None
        self.count_shift=None
        if self.c.get('phase_parameters',{}).get('force_stage_at_30',False):
            asset=json.loads((Path(__file__).resolve().parents[3]/'domains/hololive_dreams/data/jump_rope_phase/audio_count_digits_v1.json').read_text(encoding='utf-8'))
            self.count_shift=CountThirtyShift(asset,self.c['roi'])
    def reset(self):
        policy=self.policy.policy;self.vision.reset();self.policy=AudioPolicy(self.vision.bank,policy);self.reset_gate()
    def detect(self,image,timestamp=None):
        now=timestamp;playing=self.gate.update(image,now);self.audio.started_at=self.gate.started_at
        while True:
            try:item=self.audio.results.get_nowait()
            except queue.Empty:break
            # A completed matcher cannot expose a future waveform or a pre-start cue.
            if item['probe']['time']>now or self.gate.started_at is None or item['probe']['time']-2.6<self.gate.started_at:continue
            if item['event'] and item['event']['motion_hint']:self.policy.event=item['event']
            if item['prefix']['motion_hint']:self.policy.prefix=item['prefix']
            self.policy.probe=item['probe']
        if playing and self.count_shift:self.count_shift.update(image,now,self.vision.bank)
        self.vision.audio_hint_event=self.policy.event;self.vision.audio_hint_prefix=self.policy.prefix
        o=self.vision.detect(image,timestamp=now) if playing else waiting_observation()
        o['count_reading']=self.count_shift.counter.last_evidence if playing and self.count_shift else None
        o['count_30_shift']=self.count_shift.event if self.count_shift else None
        o.update(start_gate=dict(playing=playing,started_at=self.gate.started_at),
                 audio_review=dict(active_motion_hint=self.policy.event,tentative_prefix=self.policy.prefix,latest_probe=self.policy.probe,speed_window_review=getattr(self.vision.bank,'last_speed_review',None),speed_commit={k:v for k,v in (getattr(self.vision.bank,'last_speed_commit',None) or {}).items() if k!='paired_evidence'},protected_acceleration_candidates=dict(getattr(self.vision.bank,'audio_candidates',{}))),audio_error=list(self.audio.errors))
        return o


class MainlineController:
    """Measured manual onset coordinates, not verified short-jump calibration."""
    def __init__(self,config,bank,timing):
        self.c=config;self.bank=bank;self.timing=timing;self.jumps=0;self.crossings=0;self.reset_motion()
    def reset_motion(self):
        self.state='acquiring';self.mode='waiting_for_start';self.last_time=None;self.last_trigger=-math.inf
    def on_input(self,now,down):
        if down:self.jumps+=1;self.last_trigger=now;self.state='pulse_sent'
    def step(self,o,now,down=False,frame_age=0):
        self.mode=o.get('motion_state');d=dict(down=False,state=self.state,mode=self.mode,prediction=None,input_inhibited=None)
        def inhibit(reason):d.update(state=self.state,input_inhibited=reason);return d
        gap=now-self.last_time if self.last_time is not None else 0;self.last_time=now
        if not o.get('start_gate',{}).get('playing'):return inhibit('waiting_for_start')
        if gap<0:return inhibit('nonmonotonic_frame')
        # The user confirmed that correct rope timing suffices. No avatar/landing gate.
        self.state='tracking'
        phase=o.get('phase_estimate',{})
        # User-directed trial: treat the displayed curve as correct, even if uncertain.
        if not o.get('model_exists') or len(o.get('whole_curve',[]))<2:return inhibit('no_displayed_prediction')
        playback=o.get('timed_playback') or {}
        if playback.get('clock_unwrapped') is not None:
            period=playback['period_seconds'];clock=playback['clock_unwrapped'];targets=playback['jump_progress_nodes']
            late=self.timing['late_window_seconds'];rate=1/period
            arrivals=[((target-clock-rate*max(0,frame_age))%1)*period for target in targets]
            arrivals=[eta-period if eta>period-late else eta for eta in arrivals]
            if not arrivals:return inhibit('missing_template_onset')
            eta=min(arrivals)
            d['prediction']=dict(eta=eta,clock=clock,rate=rate,targets=targets,source='timed_cycle_template_onset',verified=False,assumption='displayed_prediction_is_correct',extrapolated_seconds=frame_age,template=playback['template'])
            if now-self.last_trigger<.30:return inhibit('duplicate_pass')
            if -late<=eta<=self.timing['dispatch_window_seconds']:
                d.update(down=True,state='jump_requested',input_inhibited=None,trigger='timed_template_onset_trial');return d
            return inhibit('waiting_for_onset')
        active=next((p for p in self.bank.items if p.key==self.bank.active),None)
        if active is None or active.speed<=0:return inhibit('missing_clock')
        if self.mode=='low_swing':
            targets=[]
            for coordinate,direction in [(self.timing['low_forward_coordinate'],1),(self.timing['low_return_coordinate'],-1)]:
                angle=math.acos(1-2*coordinate)/(2*math.pi)
                if direction<0:angle=1-angle
                targets.append(self.bank.warp.inverse(angle))
            signed_rate=active.speed
        else:
            coordinate=self.timing['forward_coordinate'] if active.direction>0 else self.timing['reverse_coordinate']
            # Use this candidate's own warp, including its effective stage cohort.
            if active.warp is None:target=coordinate
            else:target=active.rotation_anchor+active.direction*active.warp.inverse(active.direction*(coordinate-active.rotation_anchor))
            targets=[target];signed_rate=active.direction*active.speed
        # Advance the same displayed clock to dispatch time; never queue old actions.
        period=1/abs(signed_rate);late=self.timing.get('late_window_seconds',.035)
        arrivals=[(((target-active.phase)*(1 if signed_rate>0 else -1)-abs(signed_rate)*max(0,frame_age))%1)/abs(signed_rate) for target in targets]
        arrivals=[eta-period if eta>period-late else eta for eta in arrivals]
        eta=min(arrivals)
        d['prediction']=dict(eta=eta,clock=active.phase,rate=signed_rate,targets=targets,source=self.timing['source'],verified=False,assumption='displayed_prediction_is_correct',extrapolated_seconds=frame_age)
        if now-self.last_trigger<.30:return inhibit('duplicate_pass')
        if -late<=eta<=self.timing['dispatch_window_seconds']:
            d.update(down=True,state='jump_requested',input_inhibited=None,trigger='manual_onset_template_trial')
            return d
        return inhibit('waiting_for_onset')


def components(root,config,module,arrow_vision):
    from modular_agent.realtime.jump_rope import phase_rope_components
    settings='domains/hololive_dreams/models/jump_rope_timed_playback_config.json'
    vision,_=phase_rope_components(root,config,module,gear=True,gear_settings_path=settings)
    params=json.loads((Path(root)/settings).read_text(encoding='utf-8'))
    timing=json.loads((Path(root)/'domains/hololive_dreams/models/jump_rope_mainline_input_config.json').read_text(encoding='utf-8-sig'))
    for key in ('forward_coordinate','reverse_coordinate','low_forward_coordinate','low_return_coordinate'):
        if type(timing.get(key)) not in (int,float) or not math.isfinite(timing[key]) or not 0<timing[key]<1:raise ValueError('invalid input onset '+key)
    for key in ('dispatch_window_seconds','late_window_seconds'):
        if type(timing.get(key)) not in (int,float) or not math.isfinite(timing[key]) or not 0<timing[key]<=.05:raise ValueError('invalid input window '+key)
    config.update(mainline=True,mainline_settings=settings,mainline_trust_prediction=True,synchronous_space_pulse=True,pulse_seconds=.035)
    audio=MainlineAudio()
    try:
        templates=json.loads((Path(root)/'runtime/jump-rope/audio-calibration/reviewed-cue-templates.json').read_text(encoding='utf-8'))['templates']
        audio.start_cues(templates,params['audio_offline_review'])
        wrapped=MainlineVision(vision,config,audio,params['audio_offline_review'])
        controller=MainlineController(config,vision.bank,timing)
    except BaseException:audio.close();raise
    return wrapped,controller,audio,timing
