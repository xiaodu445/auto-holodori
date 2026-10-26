"""Bounded MULTI session orchestration, independent of rhythm note algorithms."""
import math
import time
from .interaction import RetryBudget, policy_for


class MultiLiveSession:
    def __init__(self,*,rounds,observe,click,play,wait,check=lambda:None,emit=lambda *a,**k:None,
                 clock=time.monotonic,timeout=0,step_timeout=45,matching_timeout=600):
        if type(rounds) is not int or not 1<=rounds<=1000:raise ValueError('rounds must be 1..1000')
        if not isinstance(timeout,(int,float)) or not math.isfinite(timeout) or timeout<0:raise ValueError('invalid timeout')
        for value in (step_timeout,matching_timeout):
            if not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:raise ValueError('invalid timeout')
        self.rounds=rounds;self.observe=observe;self.click=click;self.play=play;self.wait=wait
        self.check=check;self.emit=emit;self.clock=clock;self.timeout=timeout;self.step_timeout=step_timeout
        self.matching_timeout=matching_timeout;self.completed=0;self.armed=False;self.budgets={}

    def run(self):
        started=self.clock();changed=started;previous=None;stable=0;ocr_last=-math.inf
        recovering=False;accepted=None;episode=0;input_count=0;last_state=None
        try:
            while self.timeout==0 or self.clock()-started<self.timeout:
                self.check();frame=self.observe();self.check()
                if frame.state=='unknown' and (recovering or self.clock()-ocr_last>=2):
                    frame=self.observe(ocr=True);self.check();ocr_last=self.clock()
                    recovering=frame.state in ('popup','world','reward','achievement','result','again')
                elif frame.state!='unknown':recovering=False
                state=frame.state
                state_key=(state,frame.key,tuple(sorted(frame.targets)))
                signature=(state,frame.key,tuple(sorted((k,tuple(v.get('bounds',{}).get(axis,0) for axis in ('x','y','width','height'))) for k,v in frame.targets.items())))
                same_settings=(state=='settings' and state_key==last_state and previous is not None
                    and len(signature[2])==len(previous[2])
                    and all(a[0]==b[0] and all(abs(x-y)<=2 for x,y in zip(a[1],b[1])) for a,b in zip(signature[2],previous[2])))
                stable=stable+1 if signature==previous or same_settings else 1
                if state_key!=last_state:
                    # Unknown flashes do not reset the step budget.
                    if state!='unknown':changed=self.clock()
                    self.emit('state',state=state,key=frame.key,completed=self.completed,
                              evidence=frame.evidence,scores=frame.scores)
                previous=signature
                last_state=state_key
                if stable>=2 and state!='unknown' and state_key!=accepted:
                    episode+=1;accepted=state_key
                limit=self.matching_timeout if state=='matching' else (120 if state=='loading' else self.step_timeout)
                if self.clock()-changed>limit:raise RuntimeError('state_timeout:'+state)
                if state=='blocked':raise RuntimeError('game_error_or_insufficient_stamina')
                if state=='again' and stable>=2 and self.completed>=self.rounds:
                    return self.result('success','target_rounds_settled',verified=True)
                if state=='playing' and stable>=2:
                    if not self.armed:raise RuntimeError('unexpected_gameplay_without_confirmed_settings')
                    self.play_round()
                    changed=self.clock();previous=None;stable=0
                    continue
                if state in ('matching','loading','unknown','playing') or stable<2:
                    self.wait(.2);continue
                choices={'world':'stage','portal':'multi','grade':'grade','settings':'decide',
                         'reward':'close','achievement':'close','popup':'close','result':'next','again':'again'}
                action='pickup' if state=='song' else choices.get(state)
                if state in ('world','portal','grade','song','settings') and self.completed>=self.rounds:
                    raise RuntimeError('unexpected_menu_before_final_settlement')
                target=frame.targets.get(action)
                if target and target.get('enabled') is True:
                    # Pickup is a submission action, not a toggle. Keep its
                    # three-attempt budget across animation/enable-state flicker.
                    key=(self.completed,'pickup_action') if state=='song' else ((self.completed,'settings_decide') if state=='settings' else (self.completed,episode,state,frame.key,action))
                    budget=self.budgets.setdefault(key,RetryBudget(policy_for('live_menu')))
                    if budget.ready(self.clock(),enabled=True):
                        if input_count>=self.rounds*100+30:raise RuntimeError('session_input_budget_exhausted')
                        self.check();self.click(target);budget.sent(self.clock());input_count+=1
                        self.emit('menu_input',state=state,label=target['label'],attempt=budget.attempts)
                        if state=='song':
                            self.emit('pickup_requested',meaning='auto_select_high_score_and_submit',
                                      requires_song_decide=False,attempt=budget.attempts)
                        if state=='settings':
                            self.armed=True
                            # Initialize immediately after confirmation. Capture gating
                            # keeps loading/menu frames away from the note scheduler.
                            self.play_round(wait_for_start=True)
                            changed=self.clock();previous=None;stable=0
                self.wait(.2)
            raise RuntimeError('session_timeout')
        except (RuntimeError,KeyboardInterrupt) as error:
            return self.result('unknown',str(error) or 'cancelled')

    def play_round(self,wait_for_start=False):
        if self.completed>=self.rounds:raise RuntimeError('round_budget_exhausted')
        self.emit('input_owner',owner='rhythm')
        result=self.play(wait_for_start=wait_for_start)
        if result.get('cleanup_error') or not result.get('scheduler_stopped'):
            raise RuntimeError('rhythm_cleanup_unconfirmed')
        self.armed=False
        if result.get('reason')=='settings_not_accepted':
            self.emit('input_owner',owner='menu',reason='settings_not_accepted')
            return
        if result.get('reason')!='settlement_observed':
            raise RuntimeError('rhythm_stopped_without_settlement:'+str(result.get('reason')))
        self.completed+=1
        self.emit('round_completed',completed=self.completed,evidence='settlement_structure')
        self.emit('input_owner',owner='menu')

    def result(self,outcome,reason,verified=False):
        return {'outcome':outcome,'verified':verified,'reason':reason,'completed_rounds':self.completed,
                'target_rounds':self.rounds,'rewards_verified':False,
                'verification':'observed_song_settlement_and_continue_prompt' if verified else None}


class SettlementMonitor:
    """Low-frequency template-only detection on existing diagnostic frames."""
    def __init__(self,vision,*,clock=time.monotonic,cancelled=lambda:False,timeout=1800,diagnostic=None):
        import threading
        self.vision=vision;self.clock=clock;self.cancelled=cancelled;self.timeout=timeout
        self.started=clock();self.last=-math.inf;self.consecutive=0;self.settled=threading.Event()
        self.reason=None;self.diagnostic=diagnostic

    def input_edge(self,event):
        if self.diagnostic:self.diagnostic.input_edge(event)

    def check(self):
        if self.diagnostic:self.diagnostic.check()

    def frame(self,image,stamp,bounds,*args):
        if self.diagnostic:self.diagnostic.frame(image,stamp,bounds,*args)
        if stamp-self.last<.2:return
        self.last=stamp
        # Two independent current result anchors required by the recognizer.
        terminal=self.vision.settlement(image)
        self.consecutive=self.consecutive+1 if terminal else 0
        if self.consecutive>=2:self.reason='settlement_observed';self.settled.set()

    def should_yield(self):
        if self.cancelled():self.reason='cancelled';return True
        if self.clock()-self.started>=self.timeout:self.reason='song_timeout';return True
        return self.settled.is_set()


class StartGateCapture:
    """Let run() initialize now, deliver its first image only at gameplay HUD."""
    def __init__(self,capture,vision,*,clock=time.monotonic,diagnostic=None):
        self.capture=capture;self.vision=vision;self.clock=clock;self.started=clock()
        self.ready=False;self.reason=None;self.stable=0;self.settings_since=None
        self.last_poll=-math.inf;self.last_bounds=None
        self.diagnostic=diagnostic;self.diag_frames=0;self.diag_empty=0;self.diag_state='waiting_frame';self.diag_hud=None
        if diagnostic:diagnostic.gate=self
    @property
    def stats(self):return self.capture.stats
    @property
    def last_timestamp(self):return getattr(self.capture,'last_timestamp',None)
    def bounds(self):return self.capture.bounds()
    def close(self):return self.capture.close()
    def grab(self,roi):
        if self.ready:
            image,bounds=self.capture.grab(roi)
            if image is None:self.diag_empty+=1
            else:self.diag_frames+=1
            return image,bounds
        now=self.clock()
        if now-self.started>120:self.reason='gameplay_start_timeout';return None,self.bounds()
        if self.last_bounds is not None and now-self.last_poll<.03:return None,self.bounds()
        image,bounds=self.capture.grab(roi);self.last_bounds=bounds;self.last_poll=now
        if image is None:
            self.diag_empty+=1
            return None,bounds
        self.diag_frames+=1
        state=self.vision.detect(image,bounds)
        self.diag_state=state.state;self.diag_hud=None
        if state.state=='settings' and 'decide' in state.targets:
            if self.settings_since is None:self.settings_since=now
            elif now-self.settings_since>=2:self.reason='settings_not_accepted'
        else:self.settings_since=None
        if state.state=='blocked':self.reason='game_error_before_song'
        # Loading, blank fades and settings never reach the scheduler, even if
        # no notes are currently visible. HUD permits the all-held baseline.
        hud=state.state=='unknown' and self.vision.gameplay_hud(image)
        self.diag_hud=bool(hud) if state.state=='unknown' else None
        self.stable=self.stable+1 if hud else 0
        if self.diagnostic and self.diagnostic.preview:
            self.diagnostic.safe(self.diagnostic.preview.publish,image,bounds,self.diagnostic.snapshot())
        if self.diagnostic and self.stable<2:self.diagnostic.image(image)
        if self.stable>=2:self.ready=True;return image,bounds
        return None,bounds


def first_note_rearm_bindings(engine,*,progress=lambda _:None,emit=lambda *a,**k:None,clock=time.perf_counter):
    """Per-song input-edge adapter. Runs only inside the engine's input lock.

    Note detection and timing algorithms stay inherited. Release/repress once
    on the first detected note; every rising edge still uses the original
    250ms restore guard. Subsequent notes never repeat this startup action.
    """
    state={'keys':None,'phase':'armed','until':0.}
    class StartupKeys(engine.KeyState):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs);state['keys']=self
    class StartupController(engine.RhythmController):
        def decide(self,notes,*args,**kwargs):
            decision=super().decide(notes,*args,**kwargs)
            if notes and state['phase']=='armed':state['phase']='requested'
            return decision
        def guard_baseline_restore(self,decision,actual_down,now):
            keys=state['keys']
            if state['phase']=='requested' and keys is not None:
                if decision.get('inhibited'):
                    state['phase']='armed'
                    return super().guard_baseline_restore(decision,actual_down,now)
                keys.release()
                state['until']=max(now,clock())+self.c.get('release_gap_ms',8)/1000
                state['phase']='gap'
                emit('first_note_baseline_release',keys=list(self.keys),gap_ms=self.c.get('release_gap_ms',8))
                progress('首音符：释放六键，等待抬键间隔后重新按下（每曲一次）')
            rearming=False
            if state['phase']=='gap':
                if now<state['until'] or decision.get('inhibited'):
                    decision['keys']=set()
                else:
                    decision['keys']=set(self.keys);rearming=True
            guarded=super().guard_baseline_restore(decision,keys.down if keys is not None else actual_down,now)
            if rearming:
                state['phase']='done'
                emit('first_note_baseline_rearm_requested',keys=sorted(guarded['keys']),
                     blocked=guarded.get('restore_blocked',{}))
                progress('首音符重新按下请求：'+','.join(sorted(guarded['keys'])))
            return guarded
    return {'KeyState':StartupKeys,'RhythmController':StartupController}


def run_song(root,handle,vision,*,cancelled=lambda:False,progress=print,timeout=1800,config_path=None,engine=None,
             overrides=None,wait_for_start=False,emit=lambda *a,**k:None,diagnostic_dir=None,recognition_preview=None):
    """Reuse run(), and refuse menu handoff unless its timer really stopped."""
    import importlib.util
    import sys
    import threading
    from pathlib import Path
    if any(t.name=='rhythm-input-deadlines' and t.is_alive() for t in threading.enumerate()):
        raise RuntimeError('another_rhythm_scheduler_is_running')
    if engine is None:
        path=Path(root)/'domains/hololive_dreams/models/rhythm_game.py'
        spec=importlib.util.spec_from_file_location('multi_live_existing_rhythm',path)
        engine=importlib.util.module_from_spec(spec);sys.modules[spec.name]=engine;spec.loader.exec_module(engine)
    from .song_diagnostics import SongDiagnostics
    diagnostic=SongDiagnostics(emit=emit,progress=progress,directory=diagnostic_dir,preview=recognition_preview)
    monitor=SettlementMonitor(vision,cancelled=cancelled,timeout=timeout,diagnostic=diagnostic)
    run=engine.run;gates=[]
    if wait_for_start:
        # A function-local globals copy avoids mutating the engine module or
        # changing recognition/scheduling code used by other entry points.
        from types import FunctionType
        original=engine.create_capture
        def create_capture(*args,**kwargs):
            gate=StartGateCapture(original(*args,**kwargs),vision,diagnostic=diagnostic);gates.append(gate);return gate
        bindings={'create_capture':create_capture}
        if diagnostic_dir is not None:
            original_computer=engine.ActionComputer
            def compact_computer(*args,**kwargs):
                kwargs['audit_path']=None
                return original_computer(*args,**kwargs)
            bindings['ActionComputer']=compact_computer
        effective=engine.load_config(root,config_path);effective.update(overrides or {})
        if effective.get('input_mode')=='all-held':
            bindings.update(first_note_rearm_bindings(engine,progress=progress,emit=emit))
        run=FunctionType(engine.run.__code__,{**engine.run.__globals__,**bindings},
                         engine.run.__name__,engine.run.__defaults__,engine.run.__closure__)
        run.__kwdefaults__=engine.run.__kwdefaults__
    def should_yield():return any(g.reason for g in gates) or monitor.should_yield()
    options={} if overrides is None else {'overrides':dict(overrides)}
    result={}
    try:
        result=run(root,handle,live=True,config_path=config_path,should_yield=should_yield,
                   diagnostics=monitor,progress=progress,**options)
    except Exception as error:
        result={'exception':type(error).__name__+': '+str(error)}
        raise
    finally:diagnostic.finish({**result,'stop_reason':monitor.reason or next((g.reason for g in gates if g.reason),None) or result.get('reason')})
    stopped=not any(t.name=='rhythm-input-deadlines' and t.is_alive() for t in threading.enumerate())
    if not stopped or result.get('cleanup_error'):
        return {'reason':'cleanup_failed','cleanup_error':result.get('cleanup_error') or 'scheduler_alive','scheduler_stopped':stopped}
    return {'reason':next((g.reason for g in gates if g.reason),None) or monitor.reason or result.get('reason'),
            'scheduler_stopped':True,'cleanup_error':None}
