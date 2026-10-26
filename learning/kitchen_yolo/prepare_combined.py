"""Freeze both user-labelled recordings; keep neighbouring frames together."""
import json, hashlib, argparse, shutil
from pathlib import Path
from collections import Counter
import cv2
from prepare import ROOT, LabelStore, atomic_json, label_row, native_square

def sampling_copies(entry,sparse_repeat,single_repeat=1):
    if entry['split']!='train':return 1
    count=len(entry['frame']['points'])
    if count==1:return max(sparse_repeat,single_repeat)
    return sparse_repeat if 0<count<10 else 1

def rotate_square(image,rows,turns):
    side=image.shape[0]
    if image.shape[1]!=side:raise ValueError('rotation requires padded square')
    result=[list(row) for row in rows]
    for _ in range(turns%4):
        image=cv2.rotate(image,cv2.ROTATE_90_CLOCKWISE)
        for row in result:
            cls,cx,cy,w,h,px,py,visible=row
            row[:]=[cls,1-cy,cx,h,w,1-1/side-py,px,visible]
    return image,result

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--sparse-repeat',type=int,choices=[1,2,3],default=1)
    parser.add_argument('--single-repeat',type=int,choices=[1,2,4],default=1,help='单实例训练帧额外方向数；4覆盖四个直角方向')
    parser.add_argument('--single-rotation',choices=['quarter','none'],default='quarter',help='单实例复制只加权或附加直角旋转')
    parser.add_argument('--exclude-frame',action='append',default=[],help='explicit recording:frame exclusions, preserved in audit')
    args=parser.parse_args()
    catalog=json.loads((ROOT/'data/kitchen/manual-classes.json').read_text(encoding='utf-8'))
    classes=[c['id'] for c in catalog['classes']]
    entries=[]
    for workspace in sorted((ROOT/'runtime/kitchen/manual-labeling').glob('*/annotations.json')):
        raw=json.loads(workspace.read_text(encoding='utf-8'))
        if not any(f.get('points') for f in raw['frames'].values()):continue
        recording=workspace.parent.name
        recording_path=ROOT/'runtime/kitchen/recordings'/recording
        if not (recording_path/'timestamps.json').exists():recording_path=ROOT/'runtime/kitchen/sessions'/recording
        if (recording_path/'timestamps.json').exists():
            data=LabelStore(recording_path,workspace.parent).data
        else:
            data=raw
            aliases_path=workspace.parent/'class-aliases.json'
            aliases=json.loads(aliases_path.read_text(encoding='utf-8')) if aliases_path.exists() else {}
            for frame in data['frames'].values():
                for point in frame['points']:point['class_id']=aliases.get(point['class_id'],point['class_id'])
        for key,f in data['frames'].items():
            if f'{recording}:{key}' in args.exclude_frame:continue
            if not f['points']:continue  # Human-labeled frames are complete by user policy.
            if f['ignore_regions']:raise ValueError('ignore regions unsupported')
            # Previous validation is preserved. The new recording's early scene
            # is one validation group; all its nearby frames remain together.
            val=(recording=='20261021-212928-866150' and int(key) in [1085,2715,4624]) or (recording=='20261022-142617-095737' and int(key) in [320,384,636])
            entries.append(dict(recording=recording,recording_path=str(recording_path.resolve()),frame_image=str((workspace.parent/'frames'/f'frame-{int(key):06d}.png').resolve()),frame=f,roi=data['roi'],split='val' if val else 'train',timestamps_sha256=data['timestamps_sha256']))
    entries.sort(key=lambda e:(e['recording'],e['frame']['video_index']))
    train_classes={p['class_id'] for e in entries if e['split']=='train' for p in e['frame']['points']}
    used={p['class_id'] for e in entries for p in e['frame']['points']}
    assert used<=train_classes, used-train_classes
    digest=hashlib.sha256(json.dumps(dict(entries=entries,classes=classes,sparse_repeat=args.sparse_repeat,single_repeat=args.single_repeat,single_rotation=args.single_rotation),sort_keys=True).encode()).hexdigest()[:12]
    out=ROOT/'learning/kitchen_yolo/datasets'/('combined-'+digest);transforms={}
    for e in entries:
        f=e['frame'];name=e['recording']+'-'+str(f['video_index']);split=e['split']
        frame_path=Path(e['frame_image'])
        if frame_path.exists():image=cv2.imread(str(frame_path))
        else:
            cap=cv2.VideoCapture(str(Path(e['recording_path'])/'screen.avi'))
            cap.set(cv2.CAP_PROP_POS_FRAMES,f['video_index']);ok,image=cap.read();cap.release()
        if image is None:raise ValueError(f'原始帧与录像均不可读取: {name}')
        h,w=image.shape[:2];assert (w,h)==(f['width'],f['height'])
        crop=[round(e['roi'][j]*(w if j%2==0 else h)) for j in range(4)];x0,y0,x1,y1=crop
        rows=[label_row(p,classes,crop) for p in f['points']]
        padded,rows,transforms[name]=native_square(image[y0:y1,x0:x1],rows)
        for kind in ['images','labels']:(out/kind/split).mkdir(parents=True,exist_ok=True)
        assert cv2.imwrite(str(out/'images'/split/(name+'.png')),padded)
        (out/'labels'/split/(name+'.txt')).write_text('\n'.join(' '.join(map(str,row)) for row in rows)+'\n',encoding='utf-8')
        for copy in range(1,sampling_copies(e,args.sparse_repeat,args.single_repeat)):
            replica=name+f'-sparse-repeat-{copy}'
            if len(f['points'])==1 and args.single_repeat>1 and args.single_rotation=='quarter':
                augmented,aug_rows=rotate_square(padded,rows,copy)
                assert cv2.imwrite(str(out/'images'/split/(replica+'.png')),augmented)
                (out/'labels'/split/(replica+'.txt')).write_text('\n'.join(' '.join(map(str,row)) for row in aug_rows)+'\n',encoding='utf-8')
                transforms[replica]={**transforms[name],'rotation_clockwise_degrees':90*(copy%4)}
            else:
                for kind,ext in [('images','.png'),('labels','.txt')]:shutil.copyfile(out/kind/split/(name+ext),out/kind/split/(replica+ext))
    cfg=dict(path=str(out.resolve()),train='images/train',val='images/val',names=dict(enumerate(classes)),kpt_shape=[1,3],flip_idx=[0],kpt_oks_sigmas=[.05],kpt_names={i:['click'] for i in range(len(classes))})
    atomic_json(out/'data.yaml',cfg)
    atomic_json(out/'label-snapshot.json',dict(classes=catalog,entries=entries,transforms=transforms,evaluation='fixed previous six-frame grouped validation; new recording groups train only; not independent-session testing'))
    report=dict(excluded_frames=args.exclude_frame,single_rotation=args.single_rotation,single_repeat=args.single_repeat,single_instance_train_frames=sum(e['split']=='train' and len(e['frame']['points'])==1 for e in entries),sparse_repeat=args.sparse_repeat,effective_train_images=sum(sampling_copies(e,args.sparse_repeat,args.single_repeat) for e in entries if e['split']=='train'),dataset=str(out),frames=len(entries),instances=sum(len(e['frame']['points']) for e in entries),splits={s:dict(frames=sum(e['split']==s for e in entries),instances=sum(len(e['frame']['points']) for e in entries if e['split']==s),classes=dict(Counter(p['class_id'] for e in entries if e['split']==s for p in e['frame']['points']))) for s in ['train','val']})
    atomic_json(out/'audit.json',report);print(json.dumps(report,ensure_ascii=False,indent=2))

if __name__=='__main__':main()
