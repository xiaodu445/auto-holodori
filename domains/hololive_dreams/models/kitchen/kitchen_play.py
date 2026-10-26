"""One manually-started kitchen round; asynchronous vision and opt-in input.
Offline replay and default preview NEVER create an input backend click action.
"""
import argparse,json,time,threading,os,math
from dataclasses import asdict,replace
from datetime import datetime
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[4]/'src'))
import cv2
from modular_agent.realtime.kitchen_match import Item,OrderContinueController,Latest,Settings,BatchController,TrayLedger,RecipeTracker,RoundVisionGate,ScenePauseGate,plan,policy_state
from modular_agent.realtime.kitchen_policy import POLICY_FIELDS
from modular_agent.realtime.kitchen_session import SessionRecorder,LoopSessionRecorder
from modular_agent.realtime.kitchen_loop import LoopPageDetector,LoopMenuController
from modular_agent.realtime.kitchen_vision import intro_cards_visible,ResultTransitionGate,KitchenDetector,BoardRimGate,OrderTransitionGate,choose_weights

ROOT=Path(__file__).resolve().parents[4]

class ScenePaused(RuntimeError):pass

def target_ids(text,catalog):
    names={c['name']:c['id'] for c in catalog['classes']};ids={c['id'] for c in catalog['classes']};out=set()
    for token in text.replace('，',',').split(','):
        token=token.strip()
        if not token:continue
        key=names.get(token,token)
        if key not in ids:raise ValueError('未知指定食材：'+token)
        out.add(key)
    return out

def offline(args,detector,recorder,settings,targets):
    cap=cv2.VideoCapture(str(args.recording/'screen.avi'))
    stamps=json.loads((args.recording/'timestamps.json').read_text(encoding='utf-8'));count=0
    try:
        for index in range(args.start_index,len(stamps),args.stride):
            if count>=args.limit:break
            cap.set(cv2.CAP_PROP_POS_FRAMES,index);ok,image=cap.read()
            if not ok:raise RuntimeError('cannot read replay source frame')
            stamp=stamps[index]['t'];recorder.frame(image,index,stamp,stamps[index].get('client_bounds',()))
            start=time.perf_counter();observation=detector.predict(image,index,stamp,lambda:stamp)
            recorder.event('detection',t=stamp,observation=asdict(observation),inference_wall_ms=(time.perf_counter()-start)*1000)
            batch=plan(observation,targets,settings,stamp)
            recorder.event('preview_plan',t=stamp,frame_id=index,items=[asdict(p) for p in batch],simulated=True)
            count+=1
            print(f'离线帧 {index}：{len(observation.items)} 候选，计划 {len(batch)//3} 组；不发送输入',flush=True)
    finally:cap.release()
    return dict(reason='offline_limit_or_end',mode='offline',sends_input=False,source=str(args.recording),processed=count)

def live_round(args,detector,recorder,settings,targets):
    from modular_agent.computer.windows import WindowsBackend
    from modular_agent.realtime.runtime import WindowCapture
    backend=WindowsBackend()
    handle=args.window_handle
    if handle is None:
        windows=[w for w in backend.windows() if w['title'].casefold()==args.window_title.casefold()]
        if len(windows)!=1:raise ValueError('请指定 --window-handle')
        handle=windows[0]['handle']
    print(f'{args.start_delay:g} 秒后开始本局，请手动进入厨房并切回游戏；F12/失焦/窗口移动停止。'+(' 实际发送点击。' if args.live else ' 仅预览，不点击。'),flush=True)
    time.sleep(args.start_delay)
    origin=time.perf_counter();clock=lambda:time.perf_counter()-origin
    vision_gate=RoundVisionGate();last_scheduled_frame=-1;entry_after=0.;slot_updates=Latest()
    stop=threading.Event();frames=Latest();observations=Latest();health=Latest();health.put(dict(scene='starting',bounds=None,t=clock()))
    failures=[];ledger=TrayLedger(use_vision=not getattr(args,'no_tray_vision',False));controller=BatchController(settings,ledger=ledger);rim=BoardRimGate();order_gate=OrderTransitionGate(ROOT/'data/kitchen/order-transition-title.png');result_gate=ResultTransitionGate(ROOT/'data/kitchen/result-transition-title.png');sent=0;batches=0;guard_capture=None
    loop_detector=LoopPageDetector(ROOT/'data/kitchen/loop-ui')
    loop_controller=LoopMenuController();awaiting_round=False;restart_sent=-math.inf;restart_frames=0;restart_last=-1;loop_exhausted=None
    def fail(error):failures.append(str(error));stop.set()
    def capture_loop():
        nonlocal entry_after
        capture=None
        try:
            capture=WindowCapture(handle);initial=capture.bounds();index=0;order_targets=();last_order_read=-10.;previous_scene='starting'
            while not stop.is_set():
                if getattr(args,'stop_file',None) and args.stop_file.exists():raise RuntimeError('user_stop')
                tick=time.perf_counter();image,bounds=capture.grab((0,0,1,1));stamp=clock()
                if bounds!=initial:raise RuntimeError('window_moved_or_resized')
                menu=loop_detector.read(image) if loop_detector else None
                if menu:
                    scene=menu['scene']
                elif result_gate.check(image):
                    scene='result_transition';rim.begin_recovery()
                elif order_gate.check(image):
                    scene='order_transition';rim.begin_recovery()
                    if stamp-last_order_read>=.5:
                        order_targets,_=detector.hud.read_order(image);last_order_read=stamp
                else:
                    if previous_scene=='order_transition' and entry_after<=stamp:entry_after=stamp+.33
                    scene='entering' if stamp<entry_after else 'playing'
                previous_scene=scene
                health.put(dict(scene=scene,bounds=bounds,t=stamp,frame_id=index,order_targets=order_targets,loop_page=menu))
                recorder.frame(image,index,stamp,bounds);frames.put((index,stamp,image,bounds,scene));index+=1
                stop.wait(max(0,1/args.fps-(time.perf_counter()-tick)))
        except Exception as error:fail(error)
        finally:
            if capture:capture.close()
    def detect_loop():
        last=-1
        try:
            while not stop.is_set():
                frame=frames.get()
                if frame is None or frame[0]==last:stop.wait(.002);continue
                index,stamp,image,bounds,scene=frame
                if scene!='playing' or not vision_gate.claim(stamp):stop.wait(.002);continue
                last=index
                observation=detector.predict(image,index,stamp,clock,bounds)
                observation=replace(observation,scene=scene)
                if stop.is_set():break
                recorder.event('detection',t=clock(),observation=asdict(observation));observations.put(observation)
        except Exception as error:fail(error)
    def slot_loop():
        from modular_agent.realtime.kitchen_slot_watch import SlotWatcher
        watcher=SlotWatcher(ROOT/'data/kitchen/ui-icons');last=-1;signature=None
        try:
            while not stop.is_set():
                frame=frames.get()
                if frame is None or frame[0]==last:stop.wait(.02);continue
                index,stamp,image,bounds,scene=frame;last=index
                if scene!='playing':watcher.reset();slot_updates.put(None);stop.wait(.08);continue
                packet=watcher.observe(image,index,stamp,full_slots=controller.tray_feedback_mode()=='full_slots');slot_updates.put(packet)
                key=(packet['classification_scope'],tuple(row['value'] for row in packet['slots']),packet['occupied_count'])
                if key!=signature:
                    recorder.event('tray_visual_evidence',t=clock(),evidence=packet);signature=key
                stop.wait(.08)
        except Exception as error:fail(error)
    workers=[threading.Thread(target=capture_loop,daemon=True),threading.Thread(target=detect_loop,daemon=True)]
    if ledger.use_vision:workers.append(threading.Thread(target=slot_loop,daemon=True))
    recipe_tracker=RecipeTracker();pause_gate=ScenePauseGate(getattr(args,'scene_timeout',0) or math.inf);was_paused=False;minimum_capture=-1
    last_tray_state=None;last_confidence=settings.confidence
    result_continue=OrderContinueController('result_transition',delay=1.5);order_continue=OrderContinueController(delay=4);order_streak=0;order_last=-1;order_reset=False;cached_order_targets=()
    reason='duration' if args.duration else 'user_stop';last_observation=-1;last_status=0;last_plan=None;no_plan_since=clock()
    try:
        guard_capture=WindowCapture(handle)
        for worker in workers:worker.start()
        def reconcile_tray():
            packet=slot_updates.get();before=list(ledger.slots())
            if controller.apply_tray_feedback(packet,clock()):
                recorder.event('tray_correction',t=clock(),before=before,logical_tray=list(ledger.slots()),evidence=packet,phase='after_queue_wait',rule=controller.tray_feedback_mode(),recent_batch_counts=list(controller.recent_batch_counts),verified=False)
                print(('近两轮不足3次，主动刷新全部槽位：' if controller.tray_feedback_mode()=='full_slots' else '按占用槽数减3反馈台账：')+','.join(ledger.items),flush=True)
        def guard(expected_scene='playing'):
            if stop.is_set():raise RuntimeError('cancelled')
            health_now=health.get()
            if health_now['scene']!=expected_scene or clock()-health_now['t']>.3:raise ScenePaused('scene_not_current')
            if expected_scene.startswith('loop_') and not (health_now.get('loop_page') or {}).get('enabled',False):raise ScenePaused('loop_button_not_enabled')
            if guard_capture.bounds()!=health_now['bounds']:raise RuntimeError('window_changed_before_input')
        def click(item,expected_scene='playing'):
            nonlocal sent
            guard(expected_scene);bounds=health.get()['bounds'];sx,sy=round(bounds[0]+item.x),round(bounds[1]+item.y)
            # Reject an occluding top-level window at this exact click point.
            import ctypes as C
            from ctypes import wintypes as W
            backend.api.WindowFromPoint.argtypes=[W.POINT];backend.api.WindowFromPoint.restype=W.HWND
            backend.api.GetAncestor.argtypes=[W.HWND,W.UINT];backend.api.GetAncestor.restype=W.HWND
            foreground=backend.api.WindowFromPoint(W.POINT(sx,sy))
            if backend.api.GetAncestor(foreground,2)!=handle:raise RuntimeError('click_point_occluded')
            backend.move_to(sx,sy);guard(expected_scene)
            try:backend.button('left',True)
            finally:backend.button('left',False)
            sent+=1
        while (not args.duration or clock()<args.duration) and not stop.is_set():
            current_health=health.get()
            scene=current_health['scene'] if clock()-current_health['t']<=.3 else 'unknown'
            menu=current_health.get('loop_page') if scene.startswith('loop_') else None
            if loop_controller.observe(menu,current_health.get('frame_id',-1),clock(),stopped=stop.is_set()) and not getattr(args,'no_loop',False):
                stage=menu['stage'];width,height=current_health['bounds'][2:]
                x,y=menu['point'];point=Item('loop-'+stage,'loop_'+stage,width*x,height*y,1,(0,0,width,height))
                if args.live:
                    try:
                        click(point,expected_scene=menu['scene']);loop_controller.sent(clock())
                        recorder.event('loop_menu_sent',t=clock(),stage=stage,attempt=loop_controller.budget.attempts,verified=False)
                        print('循环菜单：'+{'score_next':'成绩页下一步','reward_ok':'奖励页OK','event_next':'活动结算下一步','play':'游玩，等待新局'}[stage],flush=True)
                        if stage=='play':awaiting_round=True;restart_sent=clock();restart_frames=0
                    except ScenePaused:pass
                else:
                    loop_controller.sent(clock());recorder.event('loop_menu_preview',t=clock(),stage=stage,simulated=True)
            if menu and loop_controller.exhausted and loop_exhausted!=menu['stage']:
                loop_exhausted=menu['stage'];print('该页面已尝试3次，继续观察；可手动推进，程序不会退出。',flush=True)
                recorder.event('loop_menu_retry_exhausted',t=clock(),stage=menu['stage'],verified=False)
            if not menu:loop_exhausted=None
            if awaiting_round and scene in ('playing','order_transition') and current_health.get('t',0)>restart_sent+.33:
                if current_health.get('frame_id',-1)!=restart_last:restart_frames+=1;restart_last=current_health.get('frame_id',-1)
                if restart_frames>=2:
                    awaiting_round=False
                    if hasattr(recorder,'rotate'):recorder.rotate(clock())
                    ledger.reset(clock());controller.pending=();controller.recent_batch_counts=[];last_confidence=settings.confidence
                    controller.last_frame=current_health.get('frame_id',-1);cached_order_targets=();recipe_tracker=RecipeTracker()
                    minimum_capture=clock();vision_gate.schedule(minimum_capture);last_plan=None;last_observation=-1
                    recorder.event('tray_ledger_reset',t=clock(),reason='new_loop_round',logical_tray=list(ledger.slots()),verified=False)
                    print('已观察到新局，清空旧台账并开始独立回放。',flush=True)
            elif awaiting_round:restart_frames=0
            if current_health.get('frame_id',-1)!=order_last:
                order_last=current_health.get('frame_id',-1)
                order_streak=order_streak+1 if scene=='order_transition' else 0
                if scene=='playing':order_reset=False
            if order_streak>=2 and not order_reset:
                ledger.reset(clock());controller.recent_batch_counts=[];last_confidence=settings.confidence
                controller.pending=();controller.last_frame=order_last
                recipe_tracker=RecipeTracker();cached_order_targets=();minimum_capture=current_health['t']
                vision_gate.schedule(minimum_capture);last_plan=None;order_reset=True
                recorder.event('tray_ledger_reset',t=clock(),reason='order_transition_page',logical_tray=list(ledger.slots()),verified=False)
                print('识别到Order过渡页：清空暂存台账和旧计划。',flush=True)
            if scene=='order_transition' and current_health.get('order_targets'):
                found=tuple(current_health['order_targets'])
                if found!=cached_order_targets:
                    cached_order_targets=found
                    recorder.event('order_targets',t=clock(),targets=list(found),source='order_page_icons')
                    print('Order页指定食材：'+','.join(found),flush=True)
            if order_continue.ready(scene,current_health.get('frame_id',-1),clock(),stopped=stop.is_set()):
                if args.live:
                    _,_,width,height=current_health['bounds']
                    point=Item('order-continue','order_continue',width*.5,height*.88,1,(0,0,width,height))
                    try:
                        click(point,expected_scene='order_transition')
                        order_continue.sent(clock());entry_after=clock()+.33
                        minimum_capture=entry_after;vision_gate.schedule(entry_after)
                        recorder.event('order_continue_sent',t=clock(),attempt=order_continue.budget.attempts,verified=False)
                        print('Order页已等待4秒，点击下方继续；等待棋盘出现。',flush=True)
                    except ScenePaused:pass
                else:
                    order_continue.sent(clock())
                    recorder.event('order_continue_preview',t=clock(),simulated=True)
            if result_continue.ready(scene,current_health.get('frame_id',-1),clock(),stopped=stop.is_set()):
                if args.live:
                    _,_,width,height=current_health['bounds']
                    point=Item('result-continue','result_continue',width*.5,height*.81,1,(0,0,width,height))
                    try:
                        click(point,expected_scene='result_transition');result_continue.sent(clock())
                        recorder.event('result_continue_sent',t=clock(),attempt=result_continue.budget.attempts,verified=False)
                        print('识别到做好啦页面，点击下方继续。',flush=True)
                    except ScenePaused:pass
                else:
                    result_continue.sent(clock());recorder.event('result_continue_preview',t=clock(),simulated=True)
            pause_state=pause_gate.update(scene,current_health.get('frame_id',-1),clock())
            if pause_state=='timeout':reason='scene_wait_timeout';break
            if pause_state=='paused':
                no_plan_since=clock()
                if not was_paused:
                    recipe_tracker.transition()
                    recorder.event('scene_paused',t=clock(),reason='animation_or_popup');print('画面变化，暂停点击并继续观察；棋盘恢复后自动继续。',flush=True)
                was_paused=True;stop.wait(.01);continue
            if pause_state=='resumed':
                minimum_capture=current_health['t'];vision_gate.schedule(minimum_capture);controller.pending=();controller.last_frame=current_health.get('frame_id',-1)
                last_observation=-1;last_plan=None;no_plan_since=clock();was_paused=False
                recorder.event('scene_resumed',t=clock(),verified=False);print('棋盘恢复，等待新检测后继续。',flush=True)
            reconcile_tray()  # Main loop is idle/cooling; never mutate ledger during a click queue.
            observation=observations.get()
            if observation is None or observation.captured<minimum_capture:stop.wait(.002);continue
            try:guard()
            except ScenePaused:stop.wait(.002);continue
            if controller.pending:
                state=controller.reconcile(observation,clock())
                if state=='blocked':
                    pause_gate.update('unknown',observation.frame_id,clock());stop.wait(.01);continue
                if state=='unconfirmed_batch':reason=state;break
                if state in ('targets_no_longer_detected','batch_interval_elapsed'):
                    recorder.event(state,t=clock(),verified=False);no_plan_since=clock()
                else:
                    if settings.verify_removal and observation.frame_id!=last_scheduled_frame and observation.frame_id>controller.last_frame:
                        vision_gate.schedule(clock()+.15);last_scheduled_frame=observation.frame_id
                    stop.wait(.002);continue
            if observation.frame_id==last_observation:stop.wait(.002);continue
            last_observation=observation.frame_id
            observed_tray=observation.tray
            if recipe_tracker.update(observation.targets,observed_tray,ledger):
                recorder.event('tray_ledger_reset',t=clock(),reason='stable_new_recipe_after_scene_transition',targets=list(observation.targets),verified=False)
                ledger.reset(clock());controller.recent_batch_counts=[];last_confidence=settings.confidence
                print('检测到新菜谱，重置暂存台账。',flush=True)
            if not ledger.observe(observed_tray):
                vision_gate.schedule(clock()+settings.batch_interval);last_scheduled_frame=observation.frame_id
                stop.wait(.01);continue
            logical_tray=ledger.slots()
            signature=(logical_tray,observed_tray)
            if signature!=last_tray_state:
                recorder.event('tray_ledger',t=clock(),logical_tray=list(logical_tray),observed_tray=list(observed_tray),verified=False);last_tray_state=signature
            capacity_details=dict(observation.ui_details or {});slot_packet=slot_updates.get()
            if slot_packet and 0<=clock()-slot_packet['captured']<=.35:
                capacity_details['occupied_slots']=slot_packet.get('occupied_count',sum(bool(c) for c in logical_tray))
                capacity_details['tray_capacity_reliable']=bool(slot_packet.get('slots')) and '?' not in slot_packet.get('prefix',[])

            capacity_details['last_round_clicks']=controller.recent_batch_counts[-1] if controller.recent_batch_counts else None
            capacity_details['previous_confidence']=last_confidence
            observation=replace(observation,ui_details=capacity_details,tray=logical_tray,targets=tuple(dict.fromkeys((*cached_order_targets,*observation.targets))))
            decision_time=clock();decision_trace=[]
            decision_policy=policy_state(observation,settings);last_confidence=decision_policy['threshold']
            batch=plan(observation,targets,settings,decision_time,trace=decision_trace)
            recorder.event('decision',t=decision_time,frame_id=observation.frame_id,logical_tray=list(logical_tray),observed_tray=list(observed_tray),targets=list(observation.targets),items=decision_trace,planned_ids=[p.instance_id for p in batch],settings=asdict(settings),confidence_policy=decision_policy)
            if not batch:
                controller.record_round(0)
                vision_gate.schedule(clock()+settings.batch_interval);last_scheduled_frame=observation.frame_id
                if clock()-last_status>=2:
                    print(f'{clock():.1f}s | 门槛{last_confidence:.3f} | 无可靠补齐/三消组合 | 槽位={observation.tray} | 指定={observation.targets}',flush=True);last_status=clock()
                if args.idle_timeout and clock()-no_plan_since>args.idle_timeout:reason='no_reliable_triple';break
                continue
            no_plan_since=clock()
            if args.live:
                try:
                    dispatched=controller.execute(observation,targets,clock=clock,wait=stop.wait,stopped=stop.is_set,guard=guard,click=click,latest=observations.get,emit=lambda kind,**data:recorder.event(kind,t=clock(),**data));batches+=1
                except ScenePaused:
                    vision_gate.schedule(clock()+settings.batch_interval);last_scheduled_frame=observation.frame_id
                    recorder.event('batch_interrupted_by_scene',t=clock(),verified=False);continue
                vision_gate.schedule(controller.last_sent+settings.batch_interval);last_scheduled_frame=observation.frame_id
                if len(dispatched)<len(batch):recorder.event('partial_batch_unconfirmed',t=clock(),sent=len(dispatched),verified=False)
                if controller.pending:recorder.event('pending_verification' if settings.verify_removal else 'batch_cooldown',t=clock(),count=len(controller.pending),batch_interval=settings.batch_interval,verified=False)
                if args.max_batches and batches>=args.max_batches:reason='batch_budget';break
            else:
                vision_gate.schedule(clock()+settings.batch_interval);last_scheduled_frame=observation.frame_id
                signature=tuple((p.class_id,round(p.x/8),round(p.y/8)) for p in batch)
                if signature!=last_plan:
                    recorder.event('preview_plan',t=clock(),frame_id=observation.frame_id,items=[asdict(p) for p in batch],simulated=True);last_plan=signature
            if clock()-last_status>=2:
                print(f'{clock():.1f}s | {len(observation.items)}候选 | 门槛{last_confidence:.3f} | {len(batch)}次计划点击 | 已发送{sent}次 | '+('LIVE' if args.live else '仅预览'),flush=True);last_status=clock()
    except KeyboardInterrupt:reason='cancelled'
    except Exception as error:reason=str(error)
    finally:
        stop.set()
        for worker in workers:
            if worker.ident:worker.join(timeout=10)
        if guard_capture:guard_capture.close()
        if failures:reason=failures[0]
    return dict(reason=reason,mode='live' if args.live else 'preview',sends_input=args.live,clicks_sent=sent,batches_dispatched=batches,remaining_pending=len(controller.pending),elapsed_seconds=clock(),outcome='unknown',note='fixed batch delay and fresh-frame replanning do not confirm pickup, triple removal, tray state or round completion')

def main(argv=None):
    p=argparse.ArgumentParser(description='厨房局内框架：默认仅预览，每次运行保存一局回放')
    p.add_argument('--no-loop',action='store_true',help='关闭结算后自动开始下一局')
    p.add_argument('--live',action='store_true');p.add_argument('--recording',type=Path)
    p.add_argument('--stop-file',type=Path,help='控制窗口请求正常停止并保存回放')
    p.add_argument('--targets',default='',help='可选优先类别；默认不看指定食材，所有类别凑三就消')
    p.add_argument('--weights',type=Path);p.add_argument('--device',default='0')
    p.add_argument('--window-handle',type=int);p.add_argument('--window-title',default='hololive-dreams')
    p.add_argument('--start-delay',type=float,default=5);p.add_argument('--duration',type=float,default=0,help='总时长秒；0不限')
    p.add_argument('--fps',type=float,default=30);p.add_argument('--interval-ms',type=float,default=5)
    p.add_argument('--batch-interval',type=float,default=.5,help='最后一次点击后等待秒数，之后用新截图重新规划')
    p.add_argument('--no-tray-vision',action='store_true',help='关闭槽位视觉，按新局空槽启动独立点击台账；顶部识别保留')
    p.add_argument('--reserve-slots',type=int,choices=range(1,7),default=3,help='常规预留空槽数量')
    p.add_argument('--only-targets',action='store_true',help='仅点击已识别指定食材，目标未知时不点')
    p.add_argument('--no-exploration',action='store_true',help='关闭有空位时的单件取物')
    p.add_argument('--verify-removal',action='store_true',help='可选旧版目标消失确认；默认关闭')
    p.add_argument('--confidence',type=float,default=.25);p.add_argument('--max-age-ms',type=float,default=600)
    p.add_argument('--tail-confidence',type=float,default=.12,help='稀疏残局补检门槛；0关闭')
    p.add_argument('--max-batch-clicks',type=int,default=60);p.add_argument('--max-batches',type=int,default=0,help='批次数；0不限')
    p.add_argument('--scene-timeout',type=float,default=0,help='暂停等待时限；0不限');p.add_argument('--idle-timeout',type=float,default=0,help='无计划等待时限；0不限');p.add_argument('--output',type=Path)
    p.add_argument('--start-index',type=int,default=0);p.add_argument('--stride',type=int,default=10);p.add_argument('--limit',type=int,default=60)
    p.add_argument('--no-adaptive-confidence',action='store_true')
    p.add_argument('--no-enhanced-tail',action='store_true')
    for name,_,default,kind,_,_ in POLICY_FIELDS:
        if name!='confidence':p.add_argument('--'+name.replace('_','-'),type=kind,default=default)
    a=p.parse_args(argv)
    if a.live and a.recording:p.error('回放禁止发送输入')
    if not (math.isfinite(a.duration) and a.duration>=0) or not 1<=a.fps<=60 or not 0<=a.start_delay<=30 or a.stride<1 or a.limit<1 or a.start_index<0 or a.max_batches<0 or not (math.isfinite(a.idle_timeout) and a.idle_timeout>=0) or not (math.isfinite(a.scene_timeout) and a.scene_timeout>=0):p.error('无效预算')
    catalog=json.loads((ROOT/'data/kitchen/manual-classes.json').read_text(encoding='utf-8'));targets=target_ids(a.targets,catalog)
    weights=a.weights or choose_weights(ROOT);settings=Settings(click_interval=a.interval_ms/1000,batch_interval=a.batch_interval,verify_removal=a.verify_removal,exploratory=not a.no_exploration,only_targets=a.only_targets,reserve_slots=a.reserve_slots,confidence=a.confidence,max_age=a.max_age_ms/1000,max_clicks=a.max_batch_clicks,adaptive_confidence=not a.no_adaptive_confidence,enhanced_tail=not a.no_enhanced_tail,**{name:getattr(a,name) for name,*_ in POLICY_FIELDS if name!='confidence'})
    detector=KitchenDetector(weights,a.device,a.confidence,tail_confidence=a.tail_confidence)
    detector.hud.use_tray_vision=not a.no_tray_vision
    if not a.recording:
        print('正在预热模型，完成后开始切回游戏倒计时…',flush=True)
        detector.warmup()
    output=a.output or ROOT/'runtime/kitchen/sessions'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    recorder=(SessionRecorder if a.recording or a.no_loop else LoopSessionRecorder)(output,a.fps);summary=dict(reason='initializing',sends_input=False)
    try:
        recorder.event('session_start',t=0,settings=asdict(settings),targets=sorted(targets),weights=str(weights),live=a.live,orders_source='hud_icons_with_optional_manual_override',scene_gate='prototype plate-rim change guard; not a trained popup classifier')
        summary=offline(a,detector,recorder,settings,targets) if a.recording else live_round(a,detector,recorder,settings,targets)
    except Exception as error:summary=dict(reason=str(error),mode='failed',sends_input=a.live);raise
    finally:
        recorder.close(**summary)
        print('本局回放：'+str(output.resolve()),flush=True)
    print(json.dumps(summary,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
