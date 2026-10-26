"""Offline, reproducible rotation atlas extraction from an explicitly chosen cycle."""
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np


def fit_curve(x, y, rng):
    if len(x)<80:raise ValueError('insufficient training rope pixels')
    if len(x)>800:
        take=rng.choice(len(x),800,replace=False);x=x[take];y=y[take]
    design=np.vander((x-.52)/.30,6);best=None;score=-1
    for _ in range(100):
        take=rng.choice(len(x),6,replace=False)
        if np.ptp(x[take])<.4:continue
        coefficient=np.linalg.lstsq(design[take],y[take],rcond=None)[0]
        inlier=abs(design@coefficient-y)<.008
        value=int(np.sum(inlier))
        if value>score:score=value;best=coefficient
    if best is None or score/len(x)<.50:raise ValueError('unreliable training curve')
    for _ in range(3):
        use=abs(design@best-y)<.012
        best=np.linalg.lstsq(design[use],y[use],rcond=None)[0]
    xx=np.linspace(.225,.819,41)
    curve=np.column_stack([xx,np.polyval(best,(xx-.52)/.30)])
    if not np.all(np.isfinite(curve)) or np.min(curve[:,1])<-.2 or np.max(curve[:,1])>1.2:
        raise ValueError('training curve outside screen')
    return curve,float(score/len(x))


def build(root, recipe_path):
    root=Path(root);recipe=json.loads(Path(recipe_path).read_text(encoding='utf-8'))
    recording=root/recipe['recording'];stamp_path=recording/'timestamps.json'
    stamps=json.loads(stamp_path.read_text(encoding='utf-8'))
    times=np.array([s['t'] for s in stamps])
    if len(times)<30 or not np.all(np.isfinite(times)) or np.any(np.diff(times)<=0):raise ValueError('invalid recording timestamps')
    stream=cv2.VideoCapture(str(recording/'screen.avi'))
    if not stream.isOpened():raise ValueError('training video unavailable')
    def frame_at(timestamp):
        index=int(np.argmin(abs(times-timestamp)));stream.set(cv2.CAP_PROP_POS_FRAMES,index)
        ok,image=stream.read()
        if not ok:raise ValueError('training frame unavailable')
        return index,image
    try:
        background=np.median([frame_at(t)[1] for t in np.linspace(*recipe['background_interval'],30)],axis=0).astype(np.uint8)
        start,end=recipe['cycle_interval'];rng=np.random.default_rng(recipe.get('seed',7));records=[];tiles=[]
        indices=sorted(set(frame_at(t)[0] for t in np.arange(start,end+.001,recipe.get('sample_seconds',.05))))
        for index in indices:
            stream.set(cv2.CAP_PROP_POS_FRAMES,index);ok,image=stream.read()
            if not ok:raise ValueError('training frame unavailable')
            h,w=image.shape[:2];hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
            mask=cv2.inRange(hsv,np.array([95,50,140]),np.array([115,200,255]))>0
            changed=np.max(cv2.absdiff(image,background),axis=2)>18
            yy,xx=np.where(mask&changed);x=xx/w;y=yy/h
            use=(x>.215)&(x<.83)&(y>.02)&(y<.69)
            curve,support=fit_curve(x[use],y[use],rng)
            records.append(dict(time=float(times[index]),frame=index,curve=curve.tolist(),training_inlier_fraction=support))
            if len(records)%3==1:
                rendered=image.copy()
                for xy in curve:cv2.circle(rendered,tuple(np.rint(xy*[w,h]).astype(int)),3,(0,0,255),-1)
                cv2.putText(rendered,f'{times[index]:.3f}s source #{index}',(230,35),0,.7,(0,0,255),2)
                tiles.append(cv2.resize(rendered,(396,223)))
    finally:stream.release()
    period=records[-1]['time']-records[0]['time']
    samples=[dict(phase=(s['time']-records[0]['time'])/period,curve=s['curve'],source_frame=s['frame'],training_inlier_fraction=s['training_inlier_fraction']) for s in records[:-1]]
    data=dict(schema=1,name='rotation_recorded_cycle_v1',mode='rotation',reference_period=period,
        verified=False,coordinate_space='normalized_game_client',samples=samples,
        provenance=dict(recording=recipe['recording'],recipe=str(Path(recipe_path).relative_to(root)) if Path(recipe_path).is_absolute() else str(recipe_path),
            timestamps_sha256=hashlib.sha256(stamp_path.read_bytes()).hexdigest(),cycle_times=[records[0]['time'],records[-1]['time']],
            method='blue HSV + static median subtraction + robust quintic fit, OFFLINE ONLY',
            closing_curve_mean_difference=float(np.mean(np.linalg.norm(np.array(records[-1]['curve'])-np.array(records[0]['curve']),axis=1))),
            limits='One ordinary rotation cycle; interpolated/occluded points are not ground truth. No swing path or danger/input calibration.'))
    output=root/recipe['output'];output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(data,indent=2),encoding='utf-8')
    montage=root/'runtime/jump-rope/phase/atlas-training-contact.jpg';montage.parent.mkdir(parents=True,exist_ok=True)
    tiles=tiles[:9]
    if len(tiles)==9:cv2.imwrite(str(montage),np.vstack([np.hstack(tiles[i:i+3]) for i in range(0,9,3)]))
    return dict(output=str(output.resolve()),samples=len(samples),reference_period=period,training_contact=str(montage.resolve()))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--project-root',default='.');parser.add_argument('--recipe',default='domains/hololive_dreams/data/jump_rope_phase/rotation_recipe.json')
    args=parser.parse_args();root=Path(args.project_root).resolve();cv2.setNumThreads(1)
    print(json.dumps(build(root,root/args.recipe),ensure_ascii=False))

if __name__=='__main__':main()
