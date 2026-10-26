"""Explicit assistance entry, also callable by an exclusive top-level owner."""
import argparse
import importlib.util
import json
import math
from pathlib import Path
import cv2
from modular_agent.computer import ActionComputer
from modular_agent.perception.screen import load_image
from modular_agent.realtime.runtime import WindowCapture, run_loop

def load(root, config_path=None):
    root=Path(root)
    path=root/'domains/hololive_dreams/models/fishing'
    config=json.loads(Path(config_path or path/'fishing_config.json').read_text(encoding='utf-8-sig'))
    positive=('fps','timeout','hook_press_seconds','hook_timeout','max_speed','short_loss_seconds','long_loss_seconds')
    nonnegative=('lookahead_seconds','minimum_hold','edge_speed')
    for key in positive+nonnegative:
        value=config[key]
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0 or (key in positive and value==0):
            raise ValueError('invalid '+key)
    if config['fps']>240 or config['minimum_hold']>=30 or config['hook_press_seconds']>=30: raise ValueError('unsafe timing')
    for key in ('velocity_alpha','inside_margin','edge_margin','bite_threshold'):
        if not 0<=config[key]<=1: raise ValueError('invalid '+key)
    for key in ('velocity_samples','bite_stable_frames'):
        if type(config[key]) is not int or not 1<=config[key]<=120: raise ValueError('invalid '+key)
    if config['long_loss_seconds']<=config['short_loss_seconds']: raise ValueError('loss thresholds out of order')
    config.setdefault('inertia_braking',False)
    if type(config['inertia_braking']) is not bool: raise ValueError('invalid inertia_braking')
    if config['inertia_braking']:
        for key in ('approach_seconds','approach_max_speed','velocity_deadband'):
            value=config[key]
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                raise ValueError('invalid '+key)
    config.setdefault('control_mode','bang_bang')
    if config['control_mode'] not in ('bang_bang','pwm'): raise ValueError('invalid control_mode')
    if config['control_mode']=='pwm':
        for key in ('pwm_period_seconds','pwm_position_gain','pwm_velocity_gain'):
            value=config[key]
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
                raise ValueError('invalid '+key)
        for key in ('pwm_hover_duty','pwm_min_duty','pwm_max_duty'):
            value=config[key]
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<value<1:
                raise ValueError('invalid '+key)
        if not config['pwm_min_duty']<=config['pwm_hover_duty']<=config['pwm_max_duty']:
            raise ValueError('PWM duty bounds invalid')
        pulse=min(config['pwm_min_duty'],1-config['pwm_max_duty'])*config['pwm_period_seconds']
        if pulse < max(config['minimum_hold'],2/config['fps']):
            raise ValueError('PWM pulses must allow minimum_hold and at least two frames')
        if config['pwm_period_seconds']>=30: raise ValueError('PWM period too long')
    if config['start_phase'] not in ('waiting','control'): raise ValueError('invalid start_phase')
    config.setdefault('continue_roi',[.60,.65,1,1])
    for key in ('control_roi','bite_roi','continue_roi'):
        l,t,r,b=config[key]
        if not 0<=l<r<=1 or not 0<=t<b<=1: raise ValueError('invalid '+key)
    for key in ('yellow_hsv','fish_hsv'):
        low,high=config[key]
        if len(low)!=3 or len(high)!=3 or any(type(a) is not int or type(b) is not int or not 0<=a<=b<=limit for a,b,limit in zip(low,high,(179,255,255))): raise ValueError('invalid '+key)
    spec=importlib.util.spec_from_file_location('hololive_fishing',path/'fishing.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    reference=load_image(root/'domains/hololive_dreams/data/fishing_samples/bite.png')
    # Attached reference includes title bar: TAP! only, not scenery.
    template=reference[330:394,489:652]
    return config,module,module.FishingVision(config,template)

def crop(image,roi):
    h,w=image.shape[:2]; l,t,r,b=roi
    return image[round(t*h):round(b*h),round(l*w):round(r*w)].copy()

def run_fishing(root, computer, handle, *, live=False, config_path=None, phase=None, timeout=None, should_yield=lambda:False, progress=print, boundary_probe=None):
    config,module,vision=load(root,config_path)
    if timeout is not None:
        if not math.isfinite(timeout) or timeout<=0: raise ValueError('invalid timeout')
        config['timeout']=min(config['timeout'],timeout)
    if phase is not None:
        if phase not in ('waiting','control'): raise ValueError('invalid phase')
        config['start_phase']=phase
    if live and not computer.live: raise ValueError('live requires a live computer session')
    if computer.keys or computer.buttons: raise ValueError('release existing input before exclusive fishing handoff')
    program=module.FishingProgram(config,vision)
    result=run_loop(WindowCapture(handle),program,computer,config,live=live,should_yield=should_yield,progress=progress,boundary_probe=boundary_probe)
    destination=Path(root)/'runtime/fishing/last-result.json'
    destination.parent.mkdir(parents=True,exist_ok=True)
    destination.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

def main():
    parser=argparse.ArgumentParser(description='Fishing assistance: default judgment only')
    parser.add_argument('--project-root',default='.')
    parser.add_argument('--config')
    parser.add_argument('--phase',choices=['waiting','control'])
    parser.add_argument('--start-delay',type=float,default=3,help='seconds to manually return focus to game')
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--window-handle',type=int)
    parser.add_argument('--image',help='offline screenshot')
    parser.add_argument('--replay',help='offline original-speed video; never sends input')
    parser.add_argument('--title-bar',type=int,default=0,help='pixels to remove from offline screenshot/video')
    args=parser.parse_args(); root=Path(args.project_root).resolve()
    if not math.isfinite(args.start_delay) or not 0<=args.start_delay<=30: parser.error('invalid start-delay')
    if args.title_bar<0: parser.error('title-bar must be nonnegative')
    config,module,vision=load(root,args.config)
    if args.phase: config['start_phase']=args.phase
    if args.image or args.replay:
        if args.live: parser.error('offline mode cannot be live')
        records=[]; program=module.FishingProgram(config,vision); down=False
        if args.image:
            frames=[(0,load_image(Path(args.image)))]; stream=None
        else:
            stream=cv2.VideoCapture(args.replay)
            fps=stream.get(cv2.CAP_PROP_FPS)
            if not stream.isOpened() or not math.isfinite(fps) or fps<=0: raise ValueError('invalid replay video')
            def iterator():
                index=0
                while True:
                    ok,image=stream.read()
                    if not ok: break
                    yield index/fps,image; index+=1
            frames=iterator()
        out=root/'runtime/fishing/replay'; out.mkdir(parents=True,exist_ok=True)
        try:
            for index,(timestamp,image) in enumerate(frames):
                image=image[args.title_bar:]
                if not image.size: raise ValueError('empty cropped image')
                roi=program.roi(); local=crop(image,roi)
                observation=program.detect(local)
                decision=program.step(observation,timestamp,down); down=decision['down']
                records.append(dict(time=timestamp,state=program.state,observation=observation,decision=decision))
                if observation.get('valid'):
                    h,w=local.shape[:2]
                    for key,color in [('fish',(255,255,0)),('bar_top',(0,0,255)),('bar_bottom',(0,0,255))]:
                        y=round(observation[key]*h); cv2.line(local,(0,y),(w-1,y),color,1)
                if index%60==0: cv2.imwrite(str(out/f'frame-{index:06d}.png'),local)
                if decision.get('stop'): break
        finally:
            if stream: stream.release()
        (out/'observations.json').write_text(json.dumps(records,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(records[-1] if records else {'error':'no_frames'},ensure_ascii=False,indent=2)); return
    if args.window_handle is None:
        from modular_agent.computer.windows import WindowsBackend
        matches=[w for w in WindowsBackend().windows() if 'hololive-dreams' in w['title'].lower()]
        if len(matches)!=1: parser.error('specify --window-handle; game window must be unique')
        args.window_handle=matches[0]['handle']
    with ActionComputer(live=args.live,audit_path=root/'runtime/computer-actions.jsonl') as computer:
        import time
        print(f'请切回游戏；{args.start_delay:g}秒后开始，live={args.live}',flush=True)
        deadline=time.monotonic()+args.start_delay
        while time.monotonic()<deadline and not computer.stopped: time.sleep(.01)
        if computer.stopped: return
        print(json.dumps(run_fishing(root,computer,args.window_handle,live=args.live,config_path=args.config,phase=args.phase),ensure_ascii=False,indent=2))

if __name__=='__main__': main()
