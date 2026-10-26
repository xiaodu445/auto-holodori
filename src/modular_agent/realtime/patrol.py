"""Patrol diagnostics, passive preview and explicit bounded live route execution."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import time

import cv2
import numpy as np

from modular_agent.domains.hololive_dreams.patrol import (
    Decision, MotionCalibration, Observation, PatrolController, Position, astar,
)
from modular_agent.domains.hololive_dreams.patrol_vision import (
    MinimapLocalizer, MinimapSpec, PickupPromptDetector, read_image, write_image,
)

ROOT = Path(__file__).resolve().parents[3]
DATA = ROOT/'domains/hololive_dreams/data/patrol'


@contextmanager
def route_input_lease(path):
    """Prevent two route processes from independently owning the keyboard."""
    import msvcrt
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0,2)
        if stream.tell()==0:stream.write(b'0');stream.flush()
        stream.seek(0)
        try:msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        except OSError as error:raise RuntimeError('已有路线控制或示教程序运行，请先停止它') from error
        try:yield
        finally:
            stream.seek(0);msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def save_json(path,data):
    path = Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')


class GuardedPulseExecutor:
    """Exclusive, bounded WASD/E input with before/during/after guards.

    check() must validate cancellation, focus, occlusion, client bounds and a
    fresh semantic scene observation. Calling this does not verify movement or
    collection. Stale observation time is checked again immediately before input.
    """
    def __init__(self,computer,check,*,live=False,clock=time.perf_counter,sleep=time.sleep):
        self.computer = computer;self.check = check;self.live = live
        self.clock = clock;self.sleep = sleep
        if live and not computer.live:
            raise ValueError('live ActionComputer required')

    def execute(self,decision: Decision,*,observed_at,max_age=.5):
        from modular_agent.core import Action,Outcome
        if decision.kind not in ('move','pickup','jump'):
            return False
        allowed = {'w','a','s','d'} if decision.kind == 'move' else {'e'}
        valid_keys = (len(decision.keys)==2 and decision.keys[0] in ('w','a','s','d') and decision.keys[1]=='space') if decision.kind=='jump' else (len(decision.keys)==1 and set(decision.keys)<=allowed)
        if not valid_keys or not 0 < decision.duration <= .3:
            raise ValueError('invalid patrol input')
        if self.computer.keys or self.computer.buttons:
            raise RuntimeError('exclusive patrol requires released inputs')
        self.check()
        if not 0 <= self.clock()-observed_at <= max_age:
            raise RuntimeError('stale observation before input')
        if not self.live:
            return False
        try:
            if self.computer.stopped:
                raise RuntimeError('cancelled')
            for index,key in enumerate(decision.keys):
                if index:self.check()
                result = self.computer.perform(Action('key_down',arguments={'key':key}))
                if result.outcome != Outcome.SUCCESS:
                    raise RuntimeError(result.message)
            deadline = self.clock()+decision.duration
            while self.clock() < deadline:
                self.check()
                if self.computer.stopped:
                    raise RuntimeError('cancelled')
                self.sleep(min(.01,max(0,deadline-self.clock())))
        finally:
            self.computer.release_all()
        self.check()
        return True


def make_vision(config,config_path):
    root = Path(config_path).resolve().parent
    reference = read_image(root/config['reference'])
    kw = dict(config.get('localization',{}))
    if config.get('input_mask'):
        kw['input_mask'] = cv2.imdecode(np.fromfile(str(root/config['input_mask']),dtype=np.uint8),cv2.IMREAD_GRAYSCALE)
        if kw['input_mask'] is None:raise ValueError('cannot decode custom minimap mask')
    if config.get('coverage'):
        kw['reference_mask'] = cv2.imdecode(np.fromfile(str(root/config['coverage']),dtype=np.uint8),cv2.IMREAD_GRAYSCALE)
        if kw['reference_mask'] is None:
            raise ValueError('cannot decode reference coverage')
    spec = MinimapSpec(**config.get('minimap',{}))
    localizer = MinimapLocalizer(reference,spec=spec,**kw)
    detector = PickupPromptDetector(read_image(DATA/'pickup-key.png'),read_image(DATA/'pickup-text.png'))
    return reference,localizer,detector


def latest_repaired_config(root=None):
    root = Path(root or ROOT/'runtime/patrol/maps')
    for path in sorted(root.glob('*/patrol-config.json'),key=lambda p:p.parent.name,reverse=True):
        try:
            config = read_json(path)
            if config.get('reference')=='repair-map.png' and (path.parent/config['reference']).is_file():
                return path
        except (OSError,ValueError,KeyError):
            continue
    raise ValueError('no completed repair map found; specify --config')


def overlay(reference,position,route=(),label=''):
    canvas = reference.copy()
    for i,point in enumerate(route):
        pt = tuple(round(v) for v in point)
        cv2.circle(canvas,pt,5,(255,0,255),-1)
        cv2.putText(canvas,str(i+1),pt,cv2.FONT_HERSHEY_SIMPLEX,.4,(0,0,0),1)
        if i:
            prev = tuple(round(v) for v in route[i-1])
            cv2.line(canvas,prev,pt,(255,0,255),1)
    if position:
        color = (0,210,0) if position.valid else (0,0,255)
        pt = (round(position.x),round(position.y))
        if position.valid:
            cv2.drawMarker(canvas,pt,color,cv2.MARKER_CROSS,25,3)
        if position.valid:
            label = f'position accepted s={position.score:.3f} gap={position.margin:.3f} ({position.x:.0f},{position.y:.0f}) '+label
        else:
            label = f'NOT LOCALIZED: {position.reason} s={position.score:.3f} gap={position.margin:.3f} '+label
    cv2.rectangle(canvas,(0,0),(canvas.shape[1],32),(20,20,20),-1)
    cv2.putText(canvas,label,(8,22),cv2.FONT_HERSHEY_SIMPLEX,.48,(255,255,255),1)
    return canvas


def offline(args,config):
    reference,localizer,detector = make_vision(config,args.config)
    image = read_image(args.image)
    if args.decorated:
        # Applies only to supplied screenshots. Real capture is already client-only.
        image = image[38:,:1260]
    started = time.perf_counter()
    position = localizer.locate(image,0)
    # One file is one observation: never synthesize a second confirmation frame.
    pickup = detector.read(image)
    result = dict(source=str(args.image.resolve()),position=asdict(position),pickup=pickup,
                  processing_ms=(time.perf_counter()-started)*1000,sends_input=False,
                  reference_reviewed=config.get('reference_reviewed',False))
    args.output.mkdir(parents=True,exist_ok=True)
    save_json(args.output/'observation.json',result)
    write_image(args.output/'map-overlay.png',overlay(reference,position,label='OFFLINE: one observation'))
    patch,mask = localizer.spec.crop(image)
    write_image(args.output/'minimap.png',patch)
    write_image(args.output/'minimap-mask.png',mask)
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


def edit_route(args,config):
    reference = read_image(args.config.resolve().parent/config['reference'])
    route = []
    if args.route.exists():
        route = read_json(args.route).get('points',[])
    name = 'Patrol route: left add / right undo / S save / Q quit'
    cv2.namedWindow(name,cv2.WINDOW_NORMAL)
    def click(event,x,y,flags,param):
        if event == cv2.EVENT_LBUTTONDOWN:
            route.append([x,y])
        elif event == cv2.EVENT_RBUTTONDOWN and route:
            route.pop()
    cv2.setMouseCallback(name,click)
    try:
        while cv2.getWindowProperty(name,cv2.WND_PROP_VISIBLE) >= 1:
            cv2.imshow(name,overlay(reference,None,route,'Left add | Right undo | S save | Q quit'))
            key = cv2.waitKey(30)&255
            if key in (27,ord('q')):
                break
            if key == ord('s'):
                save_json(args.route,dict(reference=config['reference'],reviewed=False,
                          coordinate_system='reference image pixels; origin top-left',points=route))
                print(f'Saved {len(route)} points: {args.route}',flush=True)
    finally:
        cv2.destroyAllWindows()
    return 0


def plan_route(args,config):
    route = read_json(args.route)['points']
    mask = cv2.imdecode(np.fromfile(str(args.walk_mask),dtype=np.uint8),cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise ValueError('cannot read walk mask')
    reference = read_image(args.config.resolve().parent/config['reference'])
    if mask.shape != reference.shape[:2]:
        raise ValueError('walk mask must match reference image dimensions')
    if not route:
        raise ValueError('empty route')
    expanded = [route[0]]
    for a,b in zip(route,route[1:]):
        expanded.extend(astar(mask,a,b,cell=args.cell,clearance=args.clearance)[1:])
    args.output.mkdir(parents=True,exist_ok=True)
    save_json(args.output/'planned-route.json',dict(points=expanded,reviewed=False,
              source=str(args.route),walk_mask=str(args.walk_mask),collection_verified=False))
    write_image(args.output/'planned-route.png',overlay(reference,None,expanded,'A* candidate; review before input'))
    print(f'Planned {len(expanded)} navigation points. No game input.')
    return 0


def calibrate(args):
    samples = read_json(args.samples)
    calibration = MotionCalibration()
    for sample in samples['samples']:
        calibration.add_sample(sample['key'],Position(**sample['before']),Position(**sample['after']),sample['held_seconds'])
    calibration.validate()
    args.output.mkdir(parents=True,exist_ok=True)
    save_json(args.output/'motion-calibration.json',dict(vectors=calibration.vectors,
              camera_fixed=True,reviewed=False,source=str(args.samples)))
    print('Saved measured WASD vectors. This does not validate camera stability in game.')
    return 0


def preview(args,config):
    from modular_agent.computer.windows import WindowsBackend
    from modular_agent.realtime.keyboard import GuardedCapture
    reference,localizer,detector = make_vision(config,args.config)
    live_route = getattr(args,'live_route',False)
    teach_route=getattr(args,'teach_route',False)
    replay_demo=getattr(args,'replay_demo',False)
    estimator_mode=getattr(args,'estimator','visual')
    computer = None
    fast_track = getattr(args,'fast_track',False)
    if fast_track:
        from modular_agent.domains.hololive_dreams.minimap_tracking import FastMinimapTracker
        from modular_agent.realtime.minimap_scan import FreeWorldGate
        localizer = FastMinimapTracker(args.config);reference = localizer.reference
        gate = FreeWorldGate()
        if live_route or teach_route:
            from modular_agent.realtime.route_scene import RouteSceneGate
            gate=RouteSceneGate(ROOT)
        print(f'Fast tracking map: {args.config.resolve()}; live={live_route}',flush=True)
    planned = read_json(args.planned_route) if getattr(args,'planned_route',None) else None
    follower = None;heading_reader=None;camera_source=None;camera_data=None;heading=None
    experience=None;demonstration=None;demo_path=None;space_monitor=None;input_meter=None;estimator=None;demo_data=None;camera_meter_counts=None
    if planned:
        from modular_agent.domains.hololive_dreams.navigation_annotations import digest
        from modular_agent.domains.hololive_dreams.navigation_planner import RouteFollower
        if planned.get('map_sha256')!=digest(args.config.resolve().parent/config['reference']):
            raise ValueError('planned route map fingerprint differs; select its exported patrol-config.json')
        mask = read_image(args.planned_route.resolve().parent/planned['planning_mask'])[:,:,0]
        if mask.shape!=reference.shape[:2]:raise ValueError('planning mask dimensions differ')
        from modular_agent.domains.hololive_dreams.route_experience import RouteExperience,Demonstration,route_key,demonstration_plan,seed_demonstration_jumps,SemiInertialEstimate
        memory_root=Path(getattr(args,'experience_root',None) or ROOT/'runtime/patrol/route-memory')
        demo_path=memory_root/(route_key(planned)+'-demonstration.json')
        if replay_demo:
            demo_data=read_json(demo_path);planned=demonstration_plan(planned,demo_data,mask)
        if live_route or teach_route:
            experience=RouteExperience(planned,memory_root/(route_key(planned)+'.json'))
        if teach_route:demonstration=Demonstration(planned)
        calibration = MotionCalibration(read_json(args.motion_calibration)['vectors']) if args.motion_calibration and not live_route else None
        if live_route:
            from modular_agent.domains.hololive_dreams.camera_navigation import CameraWRouteFollower,VisualCameraHeading
            from modular_agent.realtime.camera_navigation import camera_calibration
            camera_source,camera_data=camera_calibration(getattr(args,'camera_calibration',None))
            follower=CameraWRouteFollower(planned,mask,degrees_per_count=camera_data['degrees_per_count'],
                speed=getattr(args,'forward_speed',28.5),stop_distance=getattr(args,'stop_distance',6),continuous=True,fast_turns=True,progress_first=True)
            coverage=read_image(args.config.resolve().parent/config['coverage'])[:,:,0] if config.get('coverage') else None
            heading_reader=VisualCameraHeading(reference,coverage)
            print(f'W + camera only; calibration={camera_source}; no A/S/D probes.',flush=True)
        else:follower = RouteFollower(planned,mask,calibration)
        if teach_route:
            from modular_agent.domains.hololive_dreams.camera_navigation import VisualCameraHeading
            coverage=read_image(args.config.resolve().parent/config['coverage'])[:,:,0] if config.get('coverage') else None
            heading_reader=VisualCameraHeading(reference,coverage)
        if demo_data:seed_demonstration_jumps(experience,demo_data,follower.actions)
    backend = WindowsBackend()
    matches = [w for w in backend.windows() if w['title'].casefold()==args.window_title.casefold()]
    handle = args.window_handle
    if handle is None:
        if len(matches) != 1:
            raise ValueError('expected exactly one game window; use --window-handle')
        handle = matches[0]['handle']
    # Create/show before the countdown: creating a native preview afterwards
    # would steal foreground focus and immediately trip the game focus guard.
    from modular_agent.realtime.minimap_preview import MapPreview
    viewer = MapPreview('LIVE route - F12 stops' if live_route else ('TEACH route - manual movement; F12 stops' if teach_route else 'Patrol passive preview - no game input'),
        overlay(reference,None,label='LIVE ROUTE: focus game; F12 stops' if live_route else 'PASSIVE PREVIEW: move this window aside, then focus game'))
    print(f'{args.start_delay:g}s to switch to game. Live input={live_route}; F12/focus loss/window change stops.',flush=True)
    time.sleep(args.start_delay)
    args.output.mkdir(parents=True,exist_ok=True)
    capture = None;frames = 0;reason = 'duration';last_status = -10;input_count = 0;executor=None
    route = planned['points'] if planned else (read_json(args.route).get('points',[]) if args.route.exists() and not fast_track else [])
    motion = MotionCalibration(read_json(args.motion_calibration)['vectors']) if args.motion_calibration and not live_route else None
    controller = PatrolController(route,motion) if route and not planned else None
    origin = time.perf_counter()
    try:
        capture = GuardedCapture(handle,[(.11,.18),(.5,.5),(.79,.61),(.87,.83)])
        initial = capture.bounds()
        if camera_data:
            measured_bounds=camera_data.get('protocol',{}).get('window_bounds')
            if measured_bounds and any(abs(initial[i]-measured_bounds[i])>4 for i in (2,3)):
                raise ValueError('游戏窗口尺寸与镜头标定不同，请重新测镜头或恢复窗口大小')
        last_valid = time.perf_counter();scene_ok = False
        if experience:
            from modular_agent.realtime.route_experience import ManualSpaceMonitor
            space_monitor=ManualSpaceMonitor(handle)
        if live_route:
            from modular_agent.computer.controller import ActionComputer
            computer = ActionComputer(live=True,backend=backend,audit_path=args.output/'input-audit.jsonl',hold_timeout=65)
            from modular_agent.realtime.route_experience import InputMeter
            input_meter=InputMeter(computer)
            estimator=SemiInertialEstimate(follower.speed,follower.degrees_per_count)
            from modular_agent.realtime.camera_navigation import ContinuousRouteExecutor,RouteFrameGuard
            guard=RouteFrameGuard(capture,initial,gate,lambda:computer.stopped or bool(args.stop_file and args.stop_file.exists()))
            executor = ContinuousRouteExecutor(input_meter,guard)
        with (args.output/'observations.jsonl').open('w',encoding='utf-8') as log:
            while time.perf_counter()-origin < args.duration:
                tick = time.perf_counter()
                if args.stop_file and args.stop_file.exists():
                    reason = 'stop_file';break
                image,bounds = capture.grab((0,0,1,1));stamp = time.perf_counter()-origin
                captured_at=origin+stamp
                if bounds != initial:
                    reason = 'window_moved_or_resized';break
                if fast_track:
                    scene_valid,hud_score = gate.read(image)
                    position = localizer.locate(image,stamp,scene_valid=scene_valid)
                    pickup = dict(visible=False,enabled=False,checked=False)
                else:
                    position = localizer.locate(image,stamp);pickup = detector.read(image)
                frames += 1
                row = dict(frame_id=frames,t=stamp,position=asdict(position),pickup=pickup,sends_input=False,
                           processing_ms=(time.perf_counter()-tick)*1000)
                if fast_track:row.update(tracking=localizer.timing,hud_score=hud_score)
                scene_diagnostics=getattr(gate,'diagnostics',None) if fast_track else None
                if isinstance(scene_diagnostics,dict):row['scene_diagnostics']=scene_diagnostics.copy()
                meter_observation=input_meter.snapshot(captured_at) if input_meter else None
                if heading_reader:
                    if meter_observation is not None:
                        counts=meter_observation['mouse_counts']
                        if camera_meter_counts is not None and counts!=camera_meter_counts:
                            heading_reader.apply_mouse_delta(counts-camera_meter_counts,follower.degrees_per_count)
                        camera_meter_counts=counts
                    heading_started=time.perf_counter()
                    patch,_=localizer.spec.crop(image,mask_icons=False)
                    heading=heading_reader.read(patch,position,stamp)
                    row['camera_heading']=asdict(heading)
                    row['camera_heading_ms']=(time.perf_counter()-heading_started)*1000
                    diagnostics=getattr(heading_reader,'diagnostics',None)
                    if isinstance(diagnostics,dict):row['camera_heading_diagnostics']=diagnostics
                control_position=position;control_heading=heading
                if estimator:
                    control_position,control_heading,row['estimator']=estimator.update(position,heading,meter_observation,
                        mode=estimator_mode,cruising=follower.cruising,scene=scene_valid)
                if experience:
                    if getattr(space_monitor,'error',None):raise RuntimeError('manual_space_monitor_failed: '+space_monitor.error)
                    jump_available=getattr(gate,'jump_available',True)
                    experience.observe(position,heading,follower.index,scene_valid and jump_available)
                    learned=[]
                    for pressed_at in space_monitor.take_before(captured_at):
                        item=experience.learn(pressed_at-origin)
                        learned.append(dict(pressed_at=pressed_at-origin,recorded=item is not None,item=item,
                            reason='saved' if item else 'unconfirmed_position_or_heading'))
                        print('Manual Space: jump point saved.' if item else 'Manual Space: no confirmed pose, not saved.',flush=True)
                        if item and demonstration and not any(j['id']==item['id'] for j in demonstration.jumps):demonstration.jumps.append(item)
                    row['manual_jump_learning']=learned
                if demonstration:demonstration.observe(position,scene_valid)
                if live_route:
                    scene_ok=scene_valid;guard.update(captured_at,scene_valid)
                    if position.valid:last_valid=time.perf_counter()
                    if not scene_ok:
                        reason='free_scene_lost';row['stop_reason']=reason
                        log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush()
                        break
                    if time.perf_counter()-last_valid>2:reason='localization_timeout';break
                if follower:
                    kwargs=dict(heading=control_heading) if live_route else {}
                    advice = follower.step(control_position,frames,time.perf_counter()-origin,free_scene=scene_valid if fast_track else position.valid,**kwargs)
                    if live_route and row.get('estimator',{}).get('used_prediction') and any(
                            j['id'] not in experience.fired and j['action_index']==follower.index and
                            np.hypot(j['xy'][0]-control_position.x,j['xy'][1]-control_position.y)<=12 for j in experience.jumps):
                        advice=follower.brake(time.perf_counter()-origin,'prediction_near_jump_requires_visual')
                    if live_route and advice.kind=='jump' and not getattr(gate,'jump_available',True):
                        advice=Decision('stop','jump_unavailable_in_current_movement_state')
                    if live_route and advice.kind in ('move','cruise') and getattr(gate,'jump_available',True):
                        remembered=experience.due(position,heading,follower.index,time.perf_counter()-origin)
                        if remembered:
                            advice=Decision('jump','remembered_space',('w','space'),.12,advice.target)
                            row['remembered_jump']=remembered
                    row['route_advice'] = asdict(advice);row['route_action_index'] = follower.index
                    if live_route:row['navigation_control']=dict(progress_first=follower.progress_first,
                        camera_pending=follower.pending_turn,steering_check=follower.steering_check)
                    if live_route:
                        if advice.kind!='cruise':executor.pause()
                        if position.valid:last_valid=time.perf_counter()
                        if time.perf_counter()-last_valid>2:reason='localization_timeout';break
                        if advice.kind=='stop':
                            reason=advice.reason
                            log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush()
                            break
                        if advice.kind in ('move','jump','turn','cruise'):
                            row['frame_age_before_input_ms']=(time.perf_counter()-captured_at)*1000
                            prepared=executor.prepare(advice,observed_at=captured_at)
                            if prepared is None:
                                executor.pause();row['input_deferred']='fresh_frame_required'
                            else:
                                row['executed_decision']=asdict(prepared)
                                before=getattr(executor,'dispatched_actions',0)
                                if row.get('remembered_jump'):experience.fired.add(row['remembered_jump']['id'])
                                try:row['sends_input']=executor.execute(prepared,observed_at=captured_at)
                                except Exception as error:
                                    row['dispatch_error']=str(error)
                                    row['sends_input']=getattr(executor,'dispatched_actions',0)>before
                                    log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush();raise
                                input_count += int(row['sends_input'])
                                actual=getattr(executor,'last_decision',prepared)
                                row['executed_decision']=asdict(actual)
                                if row['sends_input']:follower.dispatched(actual,time.perf_counter()-origin)
                                if row['sends_input'] and actual.kind=='turn' and heading and heading.valid:
                                    heading_reader.expect_rotation(actual.mouse_dx,follower.degrees_per_count,time.perf_counter()-origin)
                                    camera_meter_counts=input_meter.snapshot(time.perf_counter())['mouse_counts']
                # The legacy patrol controller remains proposals only.
                if controller:
                    proposed = controller.step(Observation(frames,stamp,position,position.valid,
                                               pickup['visible'],pickup['enabled']),time.perf_counter()-origin)
                    row['shadow_decision'] = asdict(proposed)
                log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush()
                canvas = overlay(reference,position,route,f'LIVE {estimator_mode.upper()} - F12 STOP' if live_route else ('TEACH - MANUAL INPUT' if teach_route else 'PASSIVE - pickup='+str(pickup['visible'])))
                if heading and heading.valid and position.valid:
                    start=(round(position.x),round(position.y));theta=np.deg2rad(heading.degrees)
                    end=(start[0]+round(28*np.cos(theta)),start[1]+round(28*np.sin(theta)))
                    cv2.arrowedLine(canvas,start,end,(0,150,255),2)
                    for edge in (-46,46):
                        bearing=theta+np.deg2rad(edge)
                        tip=(start[0]+round(45*np.cos(bearing)),start[1]+round(45*np.sin(bearing)))
                        cv2.line(canvas,start,tip,(0,200,255),1)
                    cv2.putText(canvas,f'CAM {heading.degrees:.1f} {heading.source} {heading.confidence:.2f}',(5,38),
                        cv2.FONT_HERSHEY_SIMPLEX,.36,(0,180,255),1)
                if follower:
                    h,w = canvas.shape[:2]
                    cv2.rectangle(canvas,(0,h-28),(w,h),(20,20,20),-1)
                    cv2.putText(canvas,f'FOLLOW {follower.index}/{len(follower.actions)} {advice.reason}',(5,h-9),
                        cv2.FONT_HERSHEY_SIMPLEX,.42,(80,230,160),1)
                    if advice.target:cv2.circle(canvas,tuple(round(v) for v in advice.target),8,(0,220,255),2)
                if experience:
                    for item in experience.jumps:cv2.circle(canvas,tuple(round(v) for v in item['xy']),5,(220,80,255),1)
                    cv2.putText(canvas,f'JUMP MEMORY {len(experience.jumps)}',(5,54),cv2.FONT_HERSHEY_SIMPLEX,.4,(220,80,255),1)
                if row.get('estimator',{}).get('prediction'):
                    cv2.circle(canvas,tuple(round(v) for v in row['estimator']['prediction']),4,(255,200,0),1)
                preview_open = viewer.show(canvas)
                if frames == 1:
                    write_image(args.output/'first-client.png',image)
                if stamp-last_status >= 2:
                    print(f'{frames}: ({position.x:.0f},{position.y:.0f}) {position.reason or "accepted"}; score={position.score:.3f}; pickup={pickup["visible"]}',flush=True)
                    last_status = stamp
                    if not fast_track:write_image(args.output/'latest-map.png',canvas)
                if not preview_open:
                    reason = 'preview_closed';break
                time.sleep(max(0,1/args.fps-(time.perf_counter()-tick)))
    except KeyboardInterrupt:
        reason = 'ctrl_c'
    except Exception as error:
        reason = str(error)
    finally:
        if executor and hasattr(executor,'close'):
            try:executor.close()
            except Exception as error:reason=f'cruise_close_error: {error}'
        if computer:computer.close()
        if space_monitor:space_monitor.close()
        if demonstration and demo_path:
            try:demo_path=demonstration.save(demo_path)
            except Exception as error:reason=f'demonstration_save_error: {error}'
        if capture:
            capture.close()
        viewer.close()
        cv2.destroyAllWindows()
        if frames:write_image(args.output/'last-client.png',image)
        input_actions=getattr(executor,'dispatched_actions',0) if executor else 0
        save_json(args.output/'summary.json',dict(reason=reason,frames=frames,sends_input=input_count>0 or input_actions>0,live_enabled=live_route,input_pulses=input_count,input_actions=input_actions,
                  collection_verified=False,reference_reviewed=config.get('reference_reviewed',False),
                  fast_tracking=fast_track,source_config=str(args.config.resolve()),
                  planned_route=str(args.planned_route) if planned else None,route_action_index=follower.index if follower else None,
                  control_mode='w_camera' if live_route else ('teaching' if teach_route else 'passive'),camera_calibration=str(camera_source) if camera_source else None,
                  route_name=planned.get('name') if planned else None,
                  estimator_mode=estimator_mode,estimator_comparison=estimator.summary() if estimator else None,
                  route_memory=str(experience.path) if experience else None,remembered_jump_count=len(experience.jumps) if experience else 0,
                  demonstration_file=str(demo_path) if demonstration else None,replaying_demonstration=replay_demo,
                  scene_diagnostics=gate.diagnostics if fast_track and isinstance(getattr(gate,'diagnostics',None),dict) else None,
                  navigation_parameters=dict(forward_speed=follower.speed,stop_distance=follower.stop_distance,arrival_radius=3,continuous_cruise=True,progress_first=True,forward_start_tolerance=30,moving_steering_limit=45,visual_lease=.5,lease_expirations=getattr(executor,'expirations',0),maximum_w_pulse=.30,coarse_coast_wait=.25,fine_coast_wait=.60,maximum_turn_counts=3600,turn_response_wait=.06,mouse_counts_per_second=7200,cruise_mouse_counts_per_second=2400) if live_route else None,
                  shadow_controller=controller.summary() if controller else None))
    print(f'Preview stopped: {reason}; output={args.output.resolve()}')
    return 0 if frames else 1


def main(argv=None):
    p = argparse.ArgumentParser(description='Game_agent minimap routes; passive by default, explicit --live-route enables input')
    p.add_argument('mode',choices=('offline','preview','edit-route','plan-route','calibrate'),nargs='?',default='preview')
    p.add_argument('--config',type=Path,help='fast mode defaults to the latest completed repair map')
    p.add_argument('--fast-track',action='store_true',help='passive fixed-map tracking; no graph optimization or map composition')
    p.add_argument('--image',type=Path)
    p.add_argument('--decorated',action='store_true',help='strip 38px title bar from supplied screenshots')
    p.add_argument('--route',type=Path,default=DATA/'route.json')
    p.add_argument('--planned-route',type=Path,help='annotation planner export; passive by default, explicit --live-route executes it')
    p.add_argument('--walk-mask',type=Path)
    p.add_argument('--samples',type=Path)
    p.add_argument('--motion-calibration',type=Path,help='measured fixed-camera WASD vectors for route proposals or explicit execution')
    p.add_argument('--live-route',action='store_true',help='execute route with W + camera mouse steering; verified jumps use W+Space; F12 stops')
    p.add_argument('--estimator',choices=('visual','fused'),default='visual',help='both estimates logged; fused bridges <=0.25s only during ongoing cruise')
    p.add_argument('--teach-route',action='store_true',help='record manually walked visual trajectory and physical Space, no automatic input')
    p.add_argument('--replay-demo',action='store_true',help='live follow latest demonstration for this map/route, with visual correction')
    p.add_argument('--experience-root',type=Path,help='persistent map/route memory folder; defaults to runtime/patrol/route-memory')
    p.add_argument('--auto-calibrate',action='store_true',help='legacy compatibility flag; live route no longer probes A/S/D')
    p.add_argument('--camera-calibration',type=Path,help='complete continuous camera calibration; defaults to latest valid full turn')
    p.add_argument('--forward-speed',type=float,default=28.5)
    p.add_argument('--stop-distance',type=float,default=6)
    p.add_argument('--cell',type=int,default=8)
    p.add_argument('--clearance',type=int,default=6)
    p.add_argument('--window-handle',type=int)
    p.add_argument('--window-title',default='hololive-dreams')
    p.add_argument('--start-delay',type=float,default=5)
    p.add_argument('--duration',type=float,default=1200)
    p.add_argument('--fps',type=float,default=4)
    p.add_argument('--stop-file',type=Path)
    p.add_argument('--output',type=Path,default=ROOT/'runtime/patrol'/datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    args = p.parse_args(argv)
    if args.teach_route and (args.live_route or args.replay_demo):p.error('--teach-route is passive and cannot combine with live/replay')
    if args.teach_route and not (args.fast_track and args.planned_route and args.mode=='preview'):p.error('--teach-route requires preview --fast-track --planned-route')
    if args.replay_demo and not args.live_route:p.error('--replay-demo requires --live-route')
    if args.auto_calibrate and not args.live_route:p.error('--auto-calibrate requires --live-route')
    if args.live_route and not (args.mode=='preview' and args.fast_track and args.planned_route):
        p.error('--live-route requires preview --fast-track --planned-route')
    if args.fast_track and args.mode!='preview':p.error('--fast-track supports preview only')
    if args.planned_route and args.mode!='preview':p.error('--planned-route supports preview only')
    if args.config is None:args.config = latest_repaired_config() if args.fast_track else DATA/'config.json'
    if not 0 < args.duration <= 7200 or not 0 < args.fps <= 30 or not 0 <= args.start_delay <= 30:
        p.error('invalid preview timing')
    if args.mode == 'offline' and not args.image:
        p.error('offline requires --image')
    if args.mode == 'plan-route' and not args.walk_mask:
        p.error('plan-route requires --walk-mask')
    if args.mode == 'calibrate' and not args.samples:
        p.error('calibrate requires --samples')
    cv2.setNumThreads(1)
    if args.mode == 'calibrate':
        return calibrate(args)
    config = read_json(args.config)
    if args.live_route or args.teach_route:
        with route_input_lease(ROOT/'runtime/patrol/route-input.lock'):
            return preview(args,config)
    return {'offline':offline,'preview':preview,'edit-route':edit_route,'plan-route':plan_route}[args.mode](args,config)


if __name__ == '__main__':
    raise SystemExit(main())
