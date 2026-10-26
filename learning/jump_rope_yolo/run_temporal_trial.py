"""Plugged-in only: controlled RGB-history pilot, training and short closed-loop evaluation."""
import argparse
from collections import deque
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent
DATA=HERE/'datasets/temporal-trial-03'
BASE=HERE/'runs/hard-full-02/weights/best.pt'
EXACT=ROOT/'runtime/jump-rope/frame-review/recording-20261006-115004-094950/exact-frames'
os.environ.setdefault('YOLO_CONFIG_DIR',str(HERE/'.ultralytics'))


def composite(image,older,newer):
    out=image.copy()
    # OpenCV BGR: older orange and faint; newer cyan and stronger.
    for mask,color,alpha in [(older,(0,140,255),.12),(newer,(255,230,0),.25)]:
        y,x=np.nonzero(mask)
        if len(x):
            values=out[y,x].astype(np.float64)
            values=values*(1-alpha)+np.asarray(color,np.float64)*alpha
            out[y,x]=np.clip(np.rint(values),0,255).astype(np.uint8)
    return out


def perturb(mask,dx,dy):
    matrix=np.float32([[1,0,dx],[0,1,dy]])
    return cv2.warpAffine(mask.astype(np.uint8),matrix,(mask.shape[1],mask.shape[0]),flags=cv2.INTER_NEAREST,borderMode=cv2.BORDER_CONSTANT)>0


def score(pred,full,visible,occluded):
    nearby=cv2.dilate(pred.astype(np.uint8),cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(7,7)))>0
    _,_,components,_=cv2.connectedComponentsWithStats(pred.astype(np.uint8),8)
    areas=components[1:,4];columns=np.where(full.any(0))[0];ends=np.zeros_like(full)
    if len(columns):
        ends[:,:columns[0]+9]=full[:,:columns[0]+9];ends[:,max(0,columns[-1]-8):]=full[:,max(0,columns[-1]-8):]
    return dict(iou=float((pred&full).sum()/max(1,(pred|full).sum())),
                visible_recall=float((pred&visible).sum()/max(1,visible.sum())),
                hidden_recall=float((pred&occluded).sum()/occluded.sum()) if occluded.any() else None,
                visible_recall_3px=float((nearby&visible).sum()/max(1,visible.sum())),
                hidden_recall_3px=float((nearby&occluded).sum()/occluded.sum()) if occluded.any() else None,
                large_components=int((areas>=16).sum()),largest_component_fraction=float(areas.max()/max(1,pred.sum())) if len(areas) else 0.,
                covered_reference_columns_3px=float((nearby&full).any(0).sum()/max(1,len(columns))),
                endpoint_recall_3px=float((nearby&ends).sum()/max(1,ends.sum())),empty=not bool(pred.any()))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--epochs',type=int,default=20)
    parser.add_argument('--batch',type=int,default=4)
    parser.add_argument('--dataset',type=Path,default=DATA)
    parser.add_argument('--name',default='03')
    parser.add_argument('--history-only',action='store_true')
    parser.add_argument('--initial-weights',type=Path,default=BASE)
    parser.add_argument('--prior-weights',type=Path,default=BASE)
    parser.add_argument('--continuity-loss',action='store_true')
    parser.add_argument('--evaluate-only',action='store_true')
    args=parser.parse_args()
    if args.epochs<1 or args.batch<1:parser.error('epochs and batch must be positive')
    if not args.name.replace('-','').isalnum():parser.error('name must be alphanumeric or hyphenated')
    dataset=args.dataset
    initial=args.initial_weights
    manifest=json.loads((dataset/'MANIFEST.json').read_text(encoding='utf-8'))
    output=HERE/f'results/temporal-trial-{args.name}'
    if output.exists() and not args.evaluate_only:raise FileExistsError('Pilot output already exists; preserve it and choose a new experiment name before rerunning.')
    train_modes=['history'] if args.history_only else ['control','history']
    if args.evaluate_only:train_modes=[]
    for name in [f'temporal-{mode}-{args.name}' for mode in train_modes]:
        if (HERE/'runs'/name).exists():raise FileExistsError(name)
    output.mkdir(exist_ok=args.evaluate_only);(output/'prior-cache').mkdir(exist_ok=args.evaluate_only)
    if args.evaluate_only and (output/'report.json').exists() and not (output/'report-before-metric-audit.json').exists():
        shutil.copyfile(output/'report.json',output/'report-before-metric-audit.json')
    import torch
    from ultralytics import YOLO
    if args.continuity_loss:
        from rope_continuity_loss import install
        install()
    if not torch.cuda.is_available():raise RuntimeError('CUDA unavailable; no CPU training fallback.')
    original_hash=hashlib.sha256(initial.read_bytes()).hexdigest()
    base=YOLO(args.prior_weights);roi=manifest['roi'];x0,y0,x1,y1=roi

    def raw(frame):
        path=EXACT/f'{frame:06d}.jpg';im=cv2.imread(str(path))
        if im is None:raise FileNotFoundError(path)
        return im[y0:y1,x0:x1].copy()

    def predict(model,image):
        result=model.predict(image,imgsz=960,rect=False,device=0,quantize=16,conf=.25,retina_masks=True,verbose=False)[0]
        if result.masks is None:return np.zeros(image.shape[:2],bool)
        a=result.masks.data.any(0).cpu().numpy().astype(np.uint8)
        return cv2.resize(a,(image.shape[1],image.shape[0]),interpolation=cv2.INTER_NEAREST)>0

    # Predicted history only. Manual masks are never used as input channels or overlays.
    needed=sorted({f for r in manifest['frames'] for f in r['history_frames']})
    priors={}
    for i,f in enumerate(needed):
        cached=output/'prior-cache'/f'{f:06d}.png'
        priors[f]=cv2.imread(str(cached),0)>0 if args.evaluate_only and cached.exists() else predict(base,raw(f))
        cv2.imwrite(str(output/'prior-cache'/f'{f:06d}.png'),priors[f].astype(np.uint8)*255)
        (output/'progress.json').write_text(json.dumps(dict(status='priors',done=i+1,total=len(needed))),encoding='utf-8')
    rng=np.random.default_rng(42);corruptions=[]
    for mode in ([] if args.evaluate_only else ['control','history']):
        folder=output/f'dataset-{mode}'
        for part in ['images/train','labels/train']:(folder/part).mkdir(parents=True)
        for row in manifest['frames']:
            if row['split']!='train':continue
            f=row['frame'];name=f'{f:06d}';image=raw(f)
            if mode=='history':
                older,newer=[priors[i].copy() for i in row['history_frames']]
                draw=float(rng.random());kind='unaltered'
                if draw<.15:older[:]=False;newer[:]=False;kind='both_missing'
                elif draw<.30:
                    (older if rng.random()<.5 else newer)[:]=False;kind='one_missing'
                elif draw<.65:
                    dx,dy=map(int,rng.integers(-6,7,size=2));older=perturb(older,dx,dy);newer=perturb(newer,dx,dy);kind=f'shift_{dx}_{dy}'
                image=composite(image,older,newer);corruptions.append(dict(frame=f,kind=kind))
            cv2.imwrite(str(folder/'images/train'/f'{name}.jpg'),image,[cv2.IMWRITE_JPEG_QUALITY,95])
            shutil.copyfile(dataset/'labels/train'/f'{name}.txt',folder/'labels/train'/f'{name}.txt')
        (folder/'rope.yaml').write_text(f'path: {folder.as_posix()}\ntrain: images/train\nval: images/train\nnames:\n  0: rope\n',encoding='utf-8')
    if not args.evaluate_only:
        (output/'history-corruptions.json').write_text(json.dumps(corruptions,indent=2),encoding='utf-8')
    del base;torch.cuda.empty_cache()
    checkpoints={mode:str(HERE/f'runs/temporal-{mode}-{args.name}/weights/last.pt') for mode in (['history'] if args.history_only else ['control','history'])} if args.evaluate_only else {}
    for mode in train_modes:
        model=YOLO(initial)
        def progress(trainer):
            item=dict(mode=mode,epoch=trainer.epoch+1,epochs=args.epochs)
            (output/'progress.json').write_text(json.dumps(item),encoding='utf-8')
            print('PROGRESS',json.dumps(item),flush=True)
        model.add_callback('on_fit_epoch_end',progress)
        model.train(data=str(output/f'dataset-{mode}/rope.yaml'),project=str(HERE/'runs'),name=f'temporal-{mode}-{args.name}',exist_ok=False,
                    epochs=args.epochs,patience=0,imgsz=960,batch=args.batch,nbs=args.batch,device=0,workers=0,
                    amp=True,mask_ratio=2,overlap_mask=False,optimizer='AdamW',lr0=.0003,lrf=.1,warmup_epochs=3,warmup_bias_lr=.0003,
                    seed=42,deterministic=True,cache=False,mosaic=0,mixup=0,copy_paste=0,fliplr=0,flipud=0,degrees=0,
                    shear=0,perspective=0,translate=0,scale=0,hsv_h=0,hsv_s=0,hsv_v=0,close_mosaic=0,plots=True,val=True)
        # Fixed final epoch avoids selecting checkpoints using either evaluation set.
        checkpoints[mode]=str(model.trainer.save_dir/'weights/last.pt')
        del model;torch.cuda.empty_cache()
    (output/'progress.json').write_text(json.dumps(dict(status='evaluation')),encoding='utf-8')
    if args.history_only:checkpoints['control']=str(initial)
    models={k:YOLO(v) for k,v in checkpoints.items()};baseline=YOLO(initial)
    rows=[];cards=[]
    test_groups=[g for g in manifest['groups'] if g['split']=='test']
    for group in test_groups:
        start=group['frames'][0]
        histories={k:deque([priors[start-2].copy(),priors[start-1].copy()],maxlen=2) for k in ['closed_loop','shifted_start']}
        histories['shifted_start']=deque([perturb(a,0,30) for a in histories['shifted_start']],maxlen=2)
        for f in group['frames']:
            im=raw(f);name=f'{f:06d}'
            full,visible,occ=[cv2.imread(str(dataset/'masks'/k/f'{name}.png'),0)>0 for k in ['full','visible','occluded']]
            predicted={'baseline':predict(baseline,im),'control':predict(models['control'],im)}
            predicted['fixed_baseline_history']=predict(models['history'],composite(im,priors[f-2],priors[f-1]))
            predicted['blank_history']=predict(models['history'],im)
            for mode,hist in histories.items():
                predicted[mode]=predict(models['history'],composite(im,*hist));hist.append(predicted[mode])
            item=dict(frame=f,clip_id=group['clip_id'],metrics={k:score(v,full,visible,occ) for k,v in predicted.items()})
            rows.append(item)
            annotation=im.copy();annotation[visible]=(0,0,255);annotation[occ]=(0,255,0)
            figures=[]
            for key,view in [('original',im),('annotation',annotation)]+[(k,composite(im,np.zeros_like(mask),mask)) for k,mask in predicted.items()]:
                filename=f'{f}-{key}.jpg';cv2.imwrite(str(output/filename),view)
                figures.append(f'<figure><img loading="lazy" src="{filename}"><figcaption>{key}</figcaption></figure>')
            cards.append(f'<h2>{f} / {group["clip_id"]}</h2><div class="grid">'+''.join(figures)+'</div>')
    def aggregate(items,mode):
        values=[r['metrics'][mode] for r in items];keys=['iou','visible_recall','hidden_recall','visible_recall_3px','hidden_recall_3px','large_components','largest_component_fraction','covered_reference_columns_3px','endpoint_recall_3px']
        return {k:float(np.mean([v[k] for v in values if v[k] is not None])) if any(v[k] is not None for v in values) else None for k in keys}|dict(empty_frames=sum(v['empty'] for v in values))
    modes=list(rows[0]['metrics'])
    groups={g['clip_id']:{k:aggregate([r for r in rows if r['clip_id']==g['clip_id']],k) for k in modes} for g in test_groups}
    assert hashlib.sha256(initial.read_bytes()).hexdigest()==original_hash
    report=dict(summary={k:aggregate(rows,k) for k in modes},per_group=groups,frames=rows,checkpoints=checkpoints,
                epochs=args.epochs,batch=args.batch,initial_weights=str(initial),initial_weights_sha256=original_hash,
                input_encoding=dict(newer_alpha=.25,older_alpha=.12,order='older orange, newer cyan; BGR in code'),
                interpretation='Compare control vs closed_loop for history benefit; baseline vs control for extra-data benefit. Fixed history is diagnostic only. Shifted start and blank history probe overreliance.',
                limitations='Only three held-out triples, nine correlated frames. Frozen model priors during training differ from recursive deployment. This is a feasibility pilot, not long-sequence or all-speed validation.')
    primary=set(manifest.get('primary_eval_groups',[g['clip_id'] for g in test_groups]))
    report['primary_summary']={k:aggregate([r for r in rows if r['clip_id'] in primary],k) for k in modes}
    report['evaluation_groups']=dict(primary=sorted(primary),all=sorted(groups))
    report['training_design']=dict(history_only=args.history_only,continuity_loss=args.continuity_loss,prior_weights=str(args.prior_weights),rect=False,
                                  note='In history-only mode baseline/control are the preserved single-frame initial model, not retrained controls.')
    if args.evaluate_only and (output/'report-before-metric-audit.json').exists():
        previous=json.loads((output/'report-before-metric-audit.json').read_text(encoding='utf-8'))
        report['training_design']=previous.get('training_design',report['training_design'])
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    (output/'index.html').write_text('<meta charset="utf-8"><style>body{background:#19212b;color:white;max-width:1400px;margin:auto}.grid{display:grid;grid-template-columns:1fr 1fr}figure{margin:8px}img{width:100%}</style><h1>两帧历史小试验</h1><p>baseline：原48图模型；control：同数据当前帧训练；closed_loop：两帧历史递归反馈；fixed_baseline_history：固定旧模型历史；blank_history：无历史；shifted_start：初始历史下移30像素。</p><p>三组评估片段仅支持初步判断，不能证明长遮挡和连续漂移已解决。</p><pre>'+json.dumps(report['summary'],ensure_ascii=False,indent=2)+'</pre>'+''.join(cards),encoding='utf-8')
    (output/'progress.json').write_text(json.dumps(dict(status='complete',page=str(output/'index.html'))),encoding='utf-8')
    print('FINISHED',output/'index.html',flush=True)


if __name__=='__main__':main()
