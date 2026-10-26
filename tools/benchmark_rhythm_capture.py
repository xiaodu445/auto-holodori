"""Read-only screen-capture benchmark. No input or image files are produced."""
import argparse,json,time,zlib
from pathlib import Path
import numpy as np
import mss
from modular_agent.realtime.rhythm_capture import release_camera

def measure(kind,region,seconds):
    import dxcam
    left,top,right,bottom=region
    if kind=='dxcam':
        session=dxcam.create(output_idx=0,backend='dxgi',output_color='BGR')
        grab=lambda:session.grab(region=region,copy=True,new_frame_only=True)
    else:
        session=mss.mss()
        grab=lambda:np.asarray(session.grab(dict(left=left,top=top,width=right-left,height=bottom-top)))[:,:,:3].copy()
    samples=[];new=none=duplicates=0;previous=None;start=time.perf_counter()
    try:
        while time.perf_counter()-start<seconds:
            before=time.perf_counter();frame=grab();done=time.perf_counter()
            if frame is None:none+=1;time.sleep(.001);continue
            samples.append((done-before)*1000);signature=zlib.crc32(memoryview(frame))
            if signature==previous:duplicates+=1
            else:new+=1
            previous=signature
    finally:
        if kind=='dxcam':release_camera(session)
        else:session.close()
    elapsed=time.perf_counter()-start
    return dict(backend=kind,region=region,seconds=elapsed,captures=len(samples),changed_regions=new,
                changed_region_fps=new/elapsed,no_new_desktop_frame=none,duplicates=duplicates,
                capture_median_ms=float(np.median(samples)) if samples else None,
                capture_p95_ms=float(np.percentile(samples,95)) if samples else None)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--seconds',type=float,default=3)
    p.add_argument('--region',nargs=4,type=int,default=[0,0,1280,720]);p.add_argument('--output')
    a=p.parse_args()
    if not .1<=a.seconds<=30 or not 0<=a.region[0]<a.region[2] or not 0<=a.region[1]<a.region[3]:p.error('invalid region/seconds')
    results=[measure(k,tuple(a.region),a.seconds) for k in ('mss','dxcam')]
    payload=json.dumps(dict(scope='desktop region; changed pixels are not guaranteed new game frames',results=results),indent=2)
    print(payload)
    if a.output:
        path=Path(a.output);path.parent.mkdir(parents=True,exist_ok=True);path.write_text(payload,encoding='utf-8')
