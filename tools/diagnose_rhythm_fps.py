"""Measure foreground game capture separately from vision; never inject input."""
import json,time,zlib,importlib.util,sys
from pathlib import Path
import cv2,numpy as np
from modular_agent.realtime.rhythm_capture import DXGICapture
from modular_agent.computer.windows import WindowsBackend

root=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('rhythm_diagnose',root/'domains/hololive_dreams/models/rhythm_game.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
backend=WindowsBackend()
windows=[w for w in backend.windows() if w['title'].lower()=='hololive-dreams']
if len(windows)!=1:raise SystemExit('Open hololive-Dreams first.')
handle=windows[0]['handle']
print('No inputs. Switch to game and PLAY a moving chart. Waiting up to 45 seconds.',flush=True)
deadline=time.perf_counter()+45
while backend.api.GetForegroundWindow()!=handle:
    if backend.emergency_pressed() or time.perf_counter()>deadline:raise SystemExit('cancelled / game not foreground')
    time.sleep(.05)
time.sleep(1)
capture=DXGICapture(handle);results=[]
try:
    for threads in (None,16,1):
        if threads is not None:cv2.setNumThreads(threads)
        vision=m.RhythmVision(m.load_config(root));start=time.perf_counter();accepted=0;costs=[];present=[]
        before_stats=capture.stats.copy()
        print('Sampling '+('capture only' if threads is None else f'vision threads={threads}'),flush=True)
        while time.perf_counter()-start<4:
            tick=time.perf_counter();image,bounds=capture.grab((0,0,1,1));grabbed=time.perf_counter()
            if image is None:time.sleep(.001);continue
            accepted+=1
            present.append(capture.camera._duplicator.latest_frame_time)
            if threads is not None:
                image=cv2.resize(image,(720,round(image.shape[0]*720/image.shape[1])))
                vision.detect(image,grabbed)
            costs.append(((grabbed-tick)*1000,(time.perf_counter()-grabbed)*1000))
        elapsed=time.perf_counter()-start
        results.append(dict(vision_threads=threads,seconds=elapsed,changed_frames=accepted,
            changed_fps=accepted/elapsed,counts={k:capture.stats[k]-before_stats[k] for k in before_stats if isinstance(before_stats[k],int)},
            median_capture_ms=float(np.median([r[0] for r in costs])) if costs else None,
            median_vision_ms=float(np.median([r[1] for r in costs])) if costs else None,
            changed_present_interval_ms=float(np.median(np.diff(present))*1000) if len(present)>1 else None))
finally:capture.close()
payload=dict(scope='foreground game only; play moving chart; no input injection or saved images',results=results)
out=root/'runtime/rhythm/foreground-fps-diagnosis.json';out.parent.mkdir(parents=True,exist_ok=True)
out.write_text(json.dumps(payload,indent=2),encoding='utf-8')
print(json.dumps(payload,indent=2),flush=True)
print('Saved: '+str(out),flush=True)
