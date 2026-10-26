"""Boundary-only fishing loop; real-time decisions remain in FishingProgram."""
import time
from modular_agent.core import Action, Outcome

class FishingLoop:
    def __init__(self, *, max_rounds=999, timeout=360000, settlement_timeout=12,
                 transition_timeout=8, poll_interval=.25, unknown_recovery=True, recovery_attempts=30, center_attempts=10, recovery_wait=2, action_attempts=5):
        if type(max_rounds) is not int or not 1<=max_rounds<=10000: raise ValueError('invalid max_rounds')
        import math
        for value in (timeout,settlement_timeout,transition_timeout,poll_interval,recovery_wait):
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0: raise ValueError('invalid loop timing')
        if type(unknown_recovery) is not bool or type(recovery_attempts) is not int or not 1<=recovery_attempts<=100: raise ValueError('invalid recovery options')
        if type(center_attempts) is not int or not 0<=center_attempts<=recovery_attempts: raise ValueError('invalid center attempts')
        if type(action_attempts) is not int or not 1<=action_attempts<=5: raise ValueError('invalid action attempts')
        self.center_attempts=center_attempts; self.recovery_wait=recovery_wait; self.action_attempts=action_attempts
        self.unknown_recovery=unknown_recovery; self.recovery_attempts=recovery_attempts
        self.max_rounds=max_rounds; self.timeout=timeout
        self.settlement_timeout=settlement_timeout; self.transition_timeout=transition_timeout
        self.poll_interval=poll_interval

    def run(self, observe, realtime, click_continue, computer, *, phase='auto', live=False,
            should_yield=lambda:False, progress=lambda message:None, clock=time.monotonic, sleep=time.sleep, observe_recovery=None, click_recovery=None):
        if phase not in ('auto','waiting','control'): raise ValueError('invalid phase')
        start=clock(); rounds=[]; clicks=0; transitions=0; state='initial'; reason='timeout'
        recovery_log=[]
        stop_requested=False
        def cancelled():
            nonlocal stop_requested
            stop_requested=stop_requested or computer.stopped or should_yield()
            return stop_requested
        def pause():
            end=min(clock()+self.poll_interval,start+self.timeout)
            while clock()<end and not cancelled(): sleep(min(.02,end-clock()))
        def remaining(): return max(0,start+self.timeout-clock())
        def recover():
            if not self.unknown_recovery: return None
            reader=observe_recovery or observe
            sender=click_recovery or click_continue
            center_count=0
            action_counts={}
            for attempt in range(self.recovery_attempts):
                if cancelled() or remaining()<=0: return None
                target=reader()
                if target['state'] in ('control','bite','waiting'): return target
                if target['state'] in ('close','continue','dismiss'):
                    confirm=reader()
                    if confirm['state'] in ('control','bite','waiting'): return confirm
                    if (confirm['state']!=target['state'] or confirm['bounds']!=target['bounds']
                            or max(abs(a-b) for a,b in zip(confirm['point'],target['point']))>8):
                        pause(); continue
                    target=confirm
                else:
                    if center_count>=self.center_attempts:
                        # Keep observing during the remaining attempts instead of exiting immediately.
                        pause(); continue
                    center_count+=1
                    x,y,w,h=target['bounds']
                    target=dict(state='corner',point=(x+round(w*.88),y+round(h*.88)),bounds=target['bounds'])
                signature=(target['state'],tuple(target['point']),tuple(target['bounds']))
                if target['state'] in ('close','continue','dismiss'):
                    used=action_counts.get(signature,0)
                    if used>=self.action_attempts:
                        pause(); continue
                    action_counts[signature]=used+1
                if not live:
                    recovery_log.append(dict(action=target['state'],point=target['point'],sent=False))
                    return None
                if cancelled() or remaining()<=0: return None
                computer.release_all()
                sender(target)
                recovery_log.append(dict(action=target['state'],point=target['point'],sent=True))
                progress('钓鱼未知页恢复：'+target['state']+'，第'+str(attempt+1)+'次，等待并重新识别')
                deadline=min(clock()+self.recovery_wait,start+self.timeout)
                absent=0
                while clock()<deadline and not cancelled():
                    pause()
                    after=reader()
                    if after['state'] in ('control','bite','waiting'): return after
                    # Continue dismissal starts waiting per the user's confirmed game rule.
                    if target['state']=='continue' and after['state']=='unknown': absent+=1
                    else: absent=0
                    if absent>=2: return {**after,'state':'waiting'}
                    if after['state']=='continue' and target['state']!='continue': return after
                # The next attempt re-reads the screen before sending any more input.
            if not cancelled() and remaining()>0:
                final=reader()
                if final['state'] in ('control','bite','continue','waiting'): return final
            return None
        try:
            if cancelled(): reason='cancelled'
            else:
                if phase=='auto':
                    initial=observe()
                    if initial['state']=='control': phase='control'
                    elif initial['state']=='bite': phase='waiting'
                    elif initial['state']=='continue': state='settlement'
                    else:
                        recovered=recover()
                        if recovered and recovered['state']=='continue': state='settlement'
                        elif recovered: phase='control' if recovered['state']=='control' else 'waiting'
                        else: state='blocked'; reason='initial_state_unknown'
                while remaining()>0 and not cancelled() and state!='blocked':
                    if state!='settlement':
                        state='realtime'; progress('钓鱼决策树：'+phase+'，接管第'+str(len(rounds)+1)+'轮')
                        result=realtime(phase,remaining())
                        if result.get('reason') == 'waiting_boundary_detected':
                            boundary = result.get('boundary_observation') or {}
                            progress('等待期间检测到结算或关闭按钮，交回决策树处理。')
                            if boundary.get('state') == 'continue':
                                state = 'settlement'
                                continue
                            recovered = recover()
                            if recovered:
                                if recovered['state'] == 'continue': state = 'settlement'
                                else:
                                    phase = 'control' if recovered['state'] == 'control' else 'waiting'
                                    state = 'waiting'
                                continue
                            reason = 'settlement_unknown'
                            break
                        rounds.append(result)
                        if result.get('reason')!='track_lost_result_pending':
                            reason=result.get('reason','realtime_unknown'); break
                        if not live:
                            reason='judgment_only_realtime_returned'; break
                    state='settlement'; deadline=min(clock()+self.settlement_timeout,start+self.timeout)
                    candidate=None; stable=0; restored=None
                    while clock()<deadline and not cancelled():
                        observation=observe()
                        if observation['state'] in ('control','bite'):
                            restored=observation; break
                        if observation['state']=='continue':
                            point=observation['point']; bounds=observation['bounds']
                            if candidate and bounds==candidate['bounds'] and max(abs(a-b) for a,b in zip(point,candidate['point']))<=8: stable+=1
                            else: stable=1
                            candidate=observation
                            if stable>=2: break
                        else: candidate=None; stable=0
                        pause()
                    if cancelled(): reason='cancelled'; break
                    if restored:
                        if len(rounds)>=self.max_rounds: reason='round_limit'; break
                        phase='control' if restored['state']=='control' else 'waiting'; state='waiting'
                        continue
                    if stable<2:
                        if len(rounds)>=self.max_rounds: reason='round_limit'; break
                        recovered=recover()
                        if recovered:
                            if recovered['state']=='continue': state='settlement'
                            else:
                                phase='control' if recovered['state']=='control' else 'waiting'; state='waiting'
                            continue
                        reason='settlement_unknown'; break
                    if len(rounds)>=self.max_rounds:
                        reason='round_limit'; break
                    if not live:
                        reason='would_click_continue'; break
                    # Third fresh observation at dispatch; never use coordinates from the previous frame.
                    fresh=observe()
                    if (fresh['state']!='continue' or fresh['bounds']!=candidate['bounds']
                        or max(abs(a-b) for a,b in zip(fresh['point'],candidate['point']))>8):
                        state='settlement'
                        pause()
                        continue
                    if cancelled(): reason='cancelled'; break
                    click_continue(fresh); clicks+=1
                    progress('钓鱼决策树：已点击继续，验证离开结算页')
                    state='transition'; deadline=min(clock()+self.transition_timeout,start+self.timeout)
                    next_phase=None
                    waiting_evidence=0; absent_bounds=None
                    last_click=clock(); retry_candidate=None; retries=1
                    while clock()<deadline and not cancelled():
                        pause()
                        if cancelled() or remaining()<=0: break
                        observation=observe()
                        if observation['state'] in ('control','bite'):
                            next_phase='control' if observation['state']=='control' else 'waiting'; break
                        if observation['state']=='continue':
                            waiting_evidence=0; absent_bounds=None
                            if retries<self.action_attempts and clock()-last_click>=1.0:
                                if (retry_candidate is not None and observation['bounds']==retry_candidate['bounds']
                                    and max(abs(a-b) for a,b in zip(observation['point'],retry_candidate['point']))<=8):
                                    fresh=observe()
                                    if (fresh['state']=='continue' and fresh['bounds']==observation['bounds']
                                        and max(abs(a-b) for a,b in zip(fresh['point'],observation['point']))<=8
                                        and not cancelled() and remaining()>0):
                                        click_continue(fresh); clicks+=1; retries+=1
                                        last_click=clock(); retry_candidate=None
                                        progress('继续按钮仍在，重新点击第'+str(retries)+'次。')
                                        continue
                                retry_candidate=observation
                            continue
                        retry_candidate=None
                        if observation['state']=='unknown' and clock()-last_click>=1.0:
                            waiting_evidence=waiting_evidence+1 if observation.get('bounds')==absent_bounds else 1
                            absent_bounds=observation.get('bounds')
                            if waiting_evidence>=2:
                                next_phase='waiting'; break
                        else:
                            waiting_evidence=0; absent_bounds=None
                    if cancelled(): reason='cancelled'; break
                    if next_phase is None:
                        state='settlement'
                        progress('继续页尚未确认离开，重新识别并处理。')
                        continue
                    transitions+=1; phase=next_phase; state='waiting'
                if cancelled(): reason='cancelled'
        except Exception as error: reason='exception: '+str(error)
        finally:
            try: computer.release_all()
            except Exception as error: reason+='; release_failed: '+str(error)
        return dict(outcome='unknown',verified=False,reason=reason,state=state,
                    rounds=rounds,continue_clicks=clicks,confirmed_transitions=transitions,recovery_actions=recovery_log,
                    elapsed_seconds=clock()-start,handoff='fishing_strategy',
                    message='循环控制结束；单轮成功失败、换饵、图鉴和领奖由其他模块确认。')














