"""Export real instance boxes + existing click keypoint; reject point-only labels."""
import argparse
import collections
import hashlib
import itertools
import json
from pathlib import Path
import sys
import cv2
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'src'))
from modular_agent.realtime.kitchen_labels import LabelStore,atomic_json

ROOT=Path(__file__).resolve().parents[2]
DEFAULT_WORK=ROOT/'runtime/kitchen/manual-labeling/20261021-212928-866150'
DEFAULT_REC=ROOT/'runtime/kitchen/recordings/20261021-212928-866150'
DEFAULT_CLASSES=ROOT/'data/kitchen/manual-classes.json'


def label_row(point,classes,crop):
    x0,y0,x1,y1=crop;w,h=x1-x0,y1-y0
    if 'bbox' not in point:raise ValueError('missing real instance bbox')
    a,b,c,d=point['bbox'];px,py=point['x'],point['y']
    if not a<=px<c or not b<=py<d:raise ValueError('click point outside bbox')
    a,b,c,d=max(a,x0),max(b,y0),min(c,x1),min(d,y1)
    if not a<c or not b<d or not x0<=px<x1 or not y0<=py<y1:raise ValueError('bbox/point outside ROI')
    return [classes.index(point['class_id']),((a+c)/2-x0)/w,((b+d)/2-y0)/h,(c-a)/w,(d-b)/h,(px-x0)/w,(py-y0)/h,2]


def native_square(image,rows,stride=32):
    """Preserve every source pixel; center-pad to a stride-aligned square."""
    h,w=image.shape[:2];side=((max(h,w)+stride-1)//stride)*stride
    left=(side-w)//2;top=(side-h)//2
    padded=cv2.copyMakeBorder(image,top,side-h-top,left,side-w-left,cv2.BORDER_CONSTANT,value=(114,114,114))
    labels=[]
    for cls,cx,cy,bw,bh,px,py,visible in rows:
        labels.append([cls,(cx*w+left)/side,(cy*h+top)/side,bw*w/side,bh*h/side,(px*w+left)/side,(py*h+top)/side,visible])
    return padded,labels,dict(original_roi_size=[w,h],input_size=[side,side],padding_left=left,padding_top=top,scale=1.0)


def choose_split(frames):
    if len(frames)<4:raise ValueError('need at least four frames for diagnostic holdout')
    total=collections.Counter(p['class_id'] for f in frames for p in f['points'])
    options=[]
    for subset in itertools.combinations(range(len(frames)),max(1,len(frames)//4)):
        held=collections.Counter(p['class_id'] for i in subset for p in frames[i]['points'])
        if any(total[k]-v<=0 for k,v in held.items()):continue
        options.append((len(held),sum(min(held[k],total[k]-held[k]) for k in held),subset))
    if not options:raise ValueError('no holdout split leaves all categories in training; add data')
    subset=max(options)[2]
    return [f for i,f in enumerate(frames) if i not in subset],[frames[i] for i in subset]


def prepare(work=DEFAULT_WORK,recording=DEFAULT_REC,classes_path=DEFAULT_CLASSES,check=False,native_padding=True):
    store=LabelStore(recording,work)
    catalog=json.loads(Path(classes_path).read_text(encoding='utf-8'));class_ids=[c['id'] for c in catalog['classes']]
    selection=json.loads((Path(work)/'selection.json').read_text(encoding='utf-8'))
    frames=[];missing=[];errors=[]
    for selected in selection['frames']:
        i=selected['video_index'];f=store.data['frames'].get(str(i))
        if not f or not f['points']:errors.append(dict(frame=i,error='frame has no human labels'));continue
        frames.append(f)
        if f['ignore_regions']:errors.append(dict(frame=i,error='YOLO does not consume ignore rectangles; finish labeling or exclude frame explicitly'))
        crop=[round(store.data['roi'][j]*f['width' if j%2==0 else 'height']) for j in range(4)]
        for point in f['points']:
            if point['class_id'] not in class_ids:errors.append(dict(frame=i,error='unknown class'));continue
            if 'bbox' not in point:missing.append(dict(frame=i,instance_id=point['instance_id'],class_id=point['class_id']));continue
            try:label_row(point,class_ids,crop)
            except ValueError as error:errors.append(dict(frame=i,instance_id=point['instance_id'],error=str(error)))
    report=dict(frames=len(frames),points=sum(len(f['points']) for f in frames),missing_boxes=len(missing),missing=missing,errors=errors,ready=not missing and not errors,
                holdout_scope='same recording diagnostic only, not independent-session validation')
    atomic_json(Path(work)/'yolo-readiness.json',report)
    if check or not report['ready']:return report,None
    train,val=choose_split(frames)
    digest=hashlib.sha256(json.dumps(dict(frames=frames,classes=class_ids,roi=store.data['roi'],native_padding=native_padding),sort_keys=True).encode()).hexdigest()[:12]
    out=ROOT/'learning/kitchen_yolo/datasets'/digest
    transforms={}
    capture=cv2.VideoCapture(str(Path(recording)/'screen.avi'))
    try:
        for split,rows in [('train',train),('val',val)]:
            (out/'images'/split).mkdir(parents=True,exist_ok=True);(out/'labels'/split).mkdir(parents=True,exist_ok=True)
            for f in rows:
                i=f['video_index'];capture.set(cv2.CAP_PROP_POS_FRAMES,i);ok,image=capture.read()
                if not ok:raise RuntimeError(f'cannot read frame {i}')
                crop=[round(store.data['roi'][j]*f['width' if j%2==0 else 'height']) for j in range(4)]
                x0,y0,x1,y1=crop;name=f'frame-{i:06d}'
                exported=image[y0:y1,x0:x1]
                rows=[label_row(p,class_ids,crop) for p in f['points']]
                if native_padding:exported,rows,transforms[str(i)]=native_square(exported,rows)
                if not cv2.imwrite(str(out/'images'/split/(name+'.png')),exported):raise RuntimeError('image write failed')
                labels=[' '.join(str(v) for v in row) for row in rows]
                (out/'labels'/split/(name+'.txt')).write_text('\n'.join(labels)+'\n',encoding='utf-8')
    finally:capture.release()
    cfg=dict(path=str(out.resolve()),train='images/train',val='images/val',names={i:k for i,k in enumerate(class_ids)},
             kpt_shape=[1,3],flip_idx=[0],kpt_oks_sigmas=[.05],kpt_names={i:['click'] for i in range(len(class_ids))})
    atomic_json(out/'data.yaml',cfg)
    atomic_json(out/'label-snapshot.json',dict(classes=catalog,roi=store.data['roi'],frames=frames,train=[f['video_index'] for f in train],val=[f['video_index'] for f in val],evaluation='same-session holdout; independent validation required',native_padding=native_padding,transforms=transforms))
    report.update(dataset=str(out),train_frames=len(train),val_frames=len(val),native_padding=native_padding,input_size=max((v['input_size'][0] for v in transforms.values()),default=None))
    atomic_json(Path(work)/'yolo-readiness.json',report)
    return report,out/'data.yaml'


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    report,path=prepare(check=args.check)
    print(json.dumps({k:v for k,v in report.items() if k not in ['missing']},ensure_ascii=False,indent=2))
    if not report['ready']:sys.exit(2)
