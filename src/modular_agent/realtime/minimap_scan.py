"""Minimap-only mapping: manual walking, offline replay, opt-in bounded exploration."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import time

import cv2
import numpy as np

from modular_agent.domains.hololive_dreams.minimap_mapper import MinimapMapper,MapperSettings,FrontierExplorer
from modular_agent.domains.hololive_dreams.patrol import Decision,MotionCalibration,Position
from modular_agent.domains.hololive_dreams.patrol_vision import MinimapSpec,read_image,write_image
from modular_agent.realtime.patrol import ROOT,DATA,read_json,save_json,GuardedPulseExecutor


class FreeWorldGate:
    """Fresh minimap plus the fixed jump HUD, not a general popup classifier.

    Used only for WASD exploration. Unknown scenes inhibit input; unchanged map
    displacement stops probing. No interaction/claim/menu keys are generated.
    """
    def __init__(self):
        source = read_image(DATA/'references/free-world.png')[38:,:1260]
        self.template = cv2.cvtColor(source[542:608,1060:1135],cv2.COLOR_BGR2GRAY)

    def read(self,frame):
        frame = cv2.resize(frame,(1260,709))
        roi = cv2.cvtColor(frame[500:655,1015:1185],cv2.COLOR_BGR2GRAY)
        score = cv2.minMaxLoc(cv2.matchTemplate(roi,self.template,cv2.TM_CCOEFF_NORMED))[1]
        return score>=.90,float(score)


class ProbeCalibration:
    """Four independent measured pulses. Never assumes camera north alignment."""
    def __init__(self):
        self.motion = MotionCalibration();self.pending = None;self.rows = []

    def step(self,mapper,t):
        if self.pending:
            key,before,stamp,duration = self.pending
            after = Position(*mapper.position,t)
            self.motion.add_sample(key,Position(*before,stamp),after,duration)
            if np.linalg.norm(mapper.position-before)<1.2:
                raise ValueError('calibration displacement too small; use manual walking or longer measured samples')
            self.rows.append(dict(key=key,before=asdict(Position(*before,stamp)),after=asdict(after),held_seconds=duration))
            self.pending = None
        missing = [k for k in ('w','a','s','d') if k not in self.motion.vectors]
        if not missing:
            self.motion.validate()
            return None
        return Decision('move','measure_wasd_map_displacement',(missing[0],),.3)

    def dispatched(self,mapper,decision,t):
        self.pending = (decision.keys[0],mapper.position.copy(),t,decision.duration)


def update_preview(name,mapper,result):
    canvas = mapper.display(max_width=100000)
    label = f'{result.reason}: ({result.x:.1f},{result.y:.1f}) score={result.score:.3f} new={result.new_pixels} tiles={mapper.tiles}'
    hints={'registration_lost_return_to_last_area':'LOST: slowly return to the last mapped area; do not keep walking away.',
           'cone_direction_unknown_no_write':'MASK: pointer direction unclear; turn character or move a little, raw tile saved.',
           'scene_not_confirmed':'PAUSED: free-world HUD not confirmed; raw tile saved.'}
    hint=hints.get(result.reason)
    canvas = cv2.copyMakeBorder(canvas,52 if hint else 30,0,0,0,cv2.BORDER_CONSTANT,value=(20,20,20))
    cv2.putText(canvas,label,(5,21),cv2.FONT_HERSHEY_SIMPLEX,.42,(255,255,255),1)
    if hint:cv2.putText(canvas,hint,(5,43),cv2.FONT_HERSHEY_SIMPLEX,.38,(80,200,255),1)
    if hasattr(name,'show'):return name.show(canvas)
    cv2.imshow(name,canvas)
    return cv2.waitKey(1)&255 not in (27,ord('q')) and cv2.getWindowProperty(name,cv2.WND_PROP_VISIBLE)>=1


def offline(args,mapper):
    """Decode full-client video or a lexically ordered folder of minimap tiles."""
    count = 0;cap = None
    paths = sorted(args.tiles.glob('*.png')) if args.tiles else None
    if paths is not None and not paths:
        raise ValueError('tile folder contains no PNGs')
    if args.video:
        cap = cv2.VideoCapture(str(args.video))
        if not cap.isOpened():
            raise ValueError('cannot open video')
    try:
        with (args.output/'frames.jsonl').open('w',encoding='utf-8') as log:
            while count<args.max_frames:
                if paths is not None:
                    if count>=len(paths):
                        break
                    image = read_image(paths[count]);n = image.shape[0]
                    yy,xx = np.ogrid[:n,:n]
                    rr = ((xx-n/2)**2+(yy-n/2)**2)/(n/2)**2
                    mask = ((rr<.94**2)&(rr>.28**2)).astype(np.uint8)*255
                    result = mapper.add_tile(image,mask,count/args.fps)
                else:
                    ok,image = cap.read()
                    if not ok:
                        break
                    index = int(cap.get(cv2.CAP_PROP_POS_FRAMES))-1
                    if index%args.stride:
                        continue
                    if args.decorated:
                        image = image[38:,:1260]
                    result = mapper.observe(image,index/max(cap.get(cv2.CAP_PROP_FPS),1))
                log.write(json.dumps(asdict(result))+'\n');count += 1
                if result.reason in ('tile_budget','canvas_budget'):
                    break
    finally:
        if cap:
            cap.release()
        mapper.save(args.output)
    print(f'Processed {count}: accepted={mapper.accepted}, rejected={mapper.rejected}; {args.output.resolve()}')
    return 0 if mapper.accepted else 1


def run(args,mapper):
    from modular_agent.computer.windows import WindowsBackend
    from modular_agent.computer.controller import ActionComputer
    from modular_agent.realtime.keyboard import GuardedCapture
    backend = WindowsBackend()
    handle = args.window_handle
    if handle is None:
        matches = [w for w in backend.windows() if w['title'].casefold()==args.window_title.casefold()]
        if len(matches)!=1:
            raise ValueError('specify --window-handle; exactly one matching window required')
        handle = matches[0]['handle']
    gate = FreeWorldGate();name = None
    if not args.no_preview:
        from modular_agent.realtime.minimap_preview import MapPreview
        name = MapPreview('Minimap mapper - move preview aside then focus game',mapper.display(max_width=100000))
    mode = 'AUTO WASD EXPLORATION' if args.auto_walk else 'Manual walking; no game input.'
    if getattr(args,'repair_map',False):
        mode += ' CONE MASK + RAW-TILE POSE GRAPH; separate repair-map output.'
    print(f'{args.start_delay:g}s to focus game. '+mode+' F12/focus loss/window change stops.',flush=True)
    time.sleep(args.start_delay)
    capture = None;computer = None;reason = 'duration';frames = 0;input_count = 0
    origin = time.perf_counter();last_save = origin;last_status = origin-5
    initial = None;scene_stamp = -float('inf');scene_valid = False;scene_stable = 0
    probes = ProbeCalibration() if args.auto_calibrate else None
    explorer = None
    if args.motion_calibration:
        motion = MotionCalibration(read_json(args.motion_calibration)['vectors']);motion.validate()
        explorer = FrontierExplorer(motion,max_actions=args.max_actions)
    def check():
        if args.stop_file and args.stop_file.exists():
            raise RuntimeError('stop_file')
        if computer and computer.stopped:
            raise RuntimeError('cancelled')
        if capture.bounds()!=initial:
            raise RuntimeError('window_moved_or_resized')
        if args.auto_walk and (not scene_valid or time.perf_counter()-scene_stamp>.65):
            raise RuntimeError('fresh_free_scene_required')
    try:
        capture = GuardedCapture(handle,[(.11,.18),(.5,.5),(.87,.82)])
        initial = capture.bounds()
        if args.auto_walk:
            computer = ActionComputer(live=True,audit_path=args.output/'input-audit.jsonl')
        executor = GuardedPulseExecutor(computer,check,live=True) if computer else None
        with (args.output/'frames.jsonl').open('w',encoding='utf-8') as log:
            while time.perf_counter()-origin<args.duration and frames<args.max_frames:
                tick = time.perf_counter()
                if args.stop_file and args.stop_file.exists():
                    reason = 'stop_file';break
                image,bounds = capture.grab((0,0,1,1));scene_stamp = time.perf_counter()
                if bounds!=initial:
                    reason = 'window_moved_or_resized';break
                scene_valid,hud_score = gate.read(image)
                scene_stable = scene_stable+1 if scene_valid else 0
                result = mapper.observe(image,scene_stamp-origin,scene_valid=scene_valid)
                frames += 1
                row = dict(frame_id=frames,**asdict(result),hud_score=hud_score,sends_input=args.auto_walk)
                # Keep raw accepted and rejected minimaps so a faulty registration
                # can be replayed, rather than only preserving the blended mosaic.
                patch,_ = mapper.spec.crop(image,mask_icons=False)
                write_image(args.output/'tiles'/f'{frames:06d}.png',patch)
                decision = None
                if result.reason in ('tile_budget','canvas_budget'):
                    reason = result.reason
                elif args.auto_walk and not result.accepted:
                    reason = 'mapping_lost_auto_stopped'
                elif args.auto_walk and scene_stable>=2:
                    if probes:
                        decision = probes.step(mapper,scene_stamp-origin)
                        if decision is None:
                            explorer = FrontierExplorer(probes.motion,max_actions=args.max_actions)
                            save_json(args.output/'motion-calibration.json',dict(vectors=probes.motion.vectors,
                                      camera_fixed=True,reviewed=False,samples=probes.rows))
                            probes = None
                    if not probes:
                        decision = explorer.propose(mapper)
                    if decision:
                        row['decision'] = asdict(decision)
                        if decision.kind=='stop':
                            reason = decision.reason
                        elif executor.execute(decision,observed_at=scene_stamp,max_age=.5):
                            input_count += 1
                            if probes:
                                probes.dispatched(mapper,decision,scene_stamp-origin)
                            else:
                                explorer.dispatched(mapper,decision)
                            time.sleep(.18)
                log.write(json.dumps(row,ensure_ascii=False)+'\n');log.flush()
                if not args.no_preview and not update_preview(name,mapper,result):
                    reason = 'preview_closed'
                if time.perf_counter()-last_status>=2:
                    print(f'{frames}: {result.reason} ({result.x:.1f},{result.y:.1f}) new={result.new_pixels} accepted={mapper.accepted}',flush=True)
                    last_status = time.perf_counter()
                if reason!='duration':
                    break
                if time.perf_counter()-last_save>=args.save_interval:
                    mapper.save(args.output);last_save = time.perf_counter()
                time.sleep(max(0,1/args.fps-(time.perf_counter()-tick)))
            if frames>=args.max_frames:
                reason = 'frame_budget'
    except KeyboardInterrupt:
        reason = 'ctrl_c'
    except Exception as error:
        reason = str(error)
    finally:
        if computer:
            computer.close()
        if capture:
            capture.close()
        if name:name.close()
        cv2.destroyAllWindows()
        mapper.save(args.output)
        save_json(args.output/'session.json',dict(reason=reason,frames=frames,sends_input=args.auto_walk,
                  entire_world_explored=False,live_verified=False,inputs_dispatched=input_count,
                  exploration_actions=explorer.actions if explorer else 0))
    print(f'Mapping stopped: {reason}; output={args.output.resolve()}',flush=True)
    return 0 if mapper.accepted else 1


def main(argv=None):
    p = argparse.ArgumentParser(description='Explore and stitch the north-up MINIMAP; no overview map required')
    p.add_argument('--video',type=Path,help='offline full-client video')
    p.add_argument('--tiles',type=Path,help='offline square minimap PNGs in filename order')
    p.add_argument('--resume',type=Path,help='resume a saved mapping folder; return to last mapped area first')
    p.add_argument('--reference-config',type=Path,help='live continuation against a fixed manual export; candidate capture only')
    p.add_argument('--repair-map',action='store_true',help='cone-free raw-tile pose graph; manual walking only, outputs a separate revised map')
    p.add_argument('--clean-overlays',action='store_true',help='new-map first pass excluding pointer cone and random markers')
    p.add_argument('--continue-manual',action='store_true',help='legacy shortcut: use latest manual export unless --reference-config is supplied')
    p.add_argument('--config',type=Path,default=DATA/'config.json',help='only minimap ROI is read; reference image is unused')
    p.add_argument('--auto-walk',action='store_true',help='explicitly enable bounded WASD exploration')
    p.add_argument('--auto-calibrate',action='store_true',help='first measure four 0.3s WASD pulses')
    p.add_argument('--motion-calibration',type=Path)
    p.add_argument('--max-actions',type=int,default=500)
    p.add_argument('--max-frames',type=int,default=3000)
    p.add_argument('--max-canvas-side',type=int,default=4096)
    p.add_argument('--window-handle',type=int)
    p.add_argument('--window-title',default='hololive-dreams')
    p.add_argument('--duration',type=float,default=1200)
    p.add_argument('--fps',type=float,default=4)
    p.add_argument('--stride',type=int,default=6)
    p.add_argument('--start-delay',type=float,default=8)
    p.add_argument('--save-interval',type=float,default=15)
    p.add_argument('--stop-file',type=Path)
    p.add_argument('--no-preview',action='store_true')
    p.add_argument('--decorated',action='store_true')
    p.add_argument('--output',type=Path,default=ROOT/'runtime/patrol/maps'/datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    a = p.parse_args(argv)
    if a.continue_manual and a.reference_config is None:
        candidates = [v for v in (ROOT/'runtime/patrol/alignments').glob('*/exports/*/patrol-config.json') if (v.parent/'alignment.json').exists()]
        if not candidates:p.error('no manual export found; specify --reference-config')
        a.reference_config = max(candidates,key=lambda v:v.stat().st_mtime)
    if a.clean_overlays and (a.reference_config or a.auto_walk):p.error('--clean-overlays is for passive new-map scanning')
    if a.reference_config:print(f'Reference config: {a.reference_config.resolve()}',flush=True)
    if a.video and a.tiles or (a.video or a.tiles) and a.auto_walk:
        p.error('choose one offline source; offline never sends input')
    if a.reference_config and (a.resume or a.auto_walk):
        p.error('fixed-reference continuation currently supports manual walking only; cannot combine with resume/auto-walk')
    if a.repair_map and not a.reference_config:
        p.error('--repair-map requires --reference-config pointing to the original manual export')
    if not 0<a.duration<=7200 or not 0<a.fps<=20 or not 0<=a.start_delay<=60 or a.stride<1 or a.max_frames<1 or a.max_actions<1 or a.save_interval<=0:
        p.error('invalid timing/budget')
    if a.auto_walk and not (a.motion_calibration or a.auto_calibrate):
        p.error('--auto-walk requires --auto-calibrate or --motion-calibration')
    if a.auto_calibrate and (not a.auto_walk or a.motion_calibration):
        p.error('--auto-calibrate requires --auto-walk and no supplied calibration')
    cv2.setNumThreads(1)
    spec = MinimapSpec(**read_json(a.config).get('minimap',{}))
    if a.reference_config:
        if a.repair_map:
            from modular_agent.domains.hololive_dreams.repair_mapping import RepairMapper
            mapper = RepairMapper(a.reference_config,MapperSettings(max_canvas_side=a.max_canvas_side,max_tiles=a.max_frames))
        else:
            from modular_agent.domains.hololive_dreams.anchored_mapping import AnchoredMapper
            mapper = AnchoredMapper(a.reference_config,MapperSettings(max_canvas_side=a.max_canvas_side,max_tiles=a.max_frames))
    else:
        if a.clean_overlays:
            from modular_agent.domains.hololive_dreams.clean_minimap_mapper import CleanMinimapMapper
            mapper = CleanMinimapMapper.resume(a.resume,spec) if a.resume else CleanMinimapMapper(MapperSettings(max_canvas_side=a.max_canvas_side,terrain_radius=.89),spec)
        else:mapper = MinimapMapper.resume(a.resume,spec) if a.resume else MinimapMapper(MapperSettings(max_canvas_side=a.max_canvas_side),spec)
    a.output.mkdir(parents=True,exist_ok=True);(a.output/'tiles').mkdir(exist_ok=True)
    # Never overwrite a previous session's raw tiles/log on an accidental rerun.
    if (a.output/'frames.jsonl').exists():
        p.error('output already contains a session; choose a new --output directory')
    return offline(a,mapper) if a.video or a.tiles else run(a,mapper)


if __name__=='__main__':
    raise SystemExit(main())
