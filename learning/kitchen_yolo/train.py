"""YOLO26m click training with atomic progress and an independent GUI."""
import argparse
from datetime import datetime
import json
import math
import os
import shutil
from pathlib import Path
import subprocess
import sys
import time
import traceback
from prepare import prepare,ROOT
from modular_agent.realtime.kitchen_labels import atomic_json
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'learning/kitchen_points/ultralytics-config'))


def publish_progress(path,state):
    """Transient Windows reader locks must never abort model training."""
    for attempt in range(5):
        try:
            atomic_json(path,state)
            return True
        except OSError:
            if attempt<4:time.sleep(.02*(attempt+1))
    return False


def augmentation_parameters(diagnostic=False,mild=False):
    if mild:
        return dict(degrees=30,translate=.03,scale=.10,fliplr=0,flipud=0,mosaic=0,mixup=0,copy_paste=0,hsv_h=0,hsv_s=.08,hsv_v=.08)
    if diagnostic:
        return dict(degrees=0,translate=0,scale=0,fliplr=0,flipud=0,mosaic=0,mixup=0,copy_paste=0,hsv_h=0,hsv_s=0,hsv_v=0)
    return dict(degrees=180,translate=.08,scale=.2,fliplr=.5,flipud=.5,mosaic=0,mixup=0,copy_paste=0,hsv_h=.01,hsv_s=.15,hsv_v=.15)


def main():
    p=argparse.ArgumentParser();p.add_argument('--epochs',type=int,default=150);p.add_argument('--batch',type=int,default=2)
    p.add_argument('--imgsz',type=int,default=None);p.add_argument('--run-dir',type=Path)
    p.add_argument('--model-size',choices=['m','l','x'],default='x')
    p.add_argument('--data',type=Path,help='frozen prepared data.yaml for controlled comparisons')
    p.add_argument('--no-progress-window',action='store_true');p.add_argument('--resume',type=Path)
    p.add_argument('--initial-weights',type=Path,help='fine-tune these weights in a fresh run, without resuming optimizer')
    p.add_argument('--no-augment',action='store_true')
    p.add_argument('--mild-augment',action='store_true',help='mild rotation/translation/scale/brightness; preserves diagnostic optimizer schedule')
    p.add_argument('--diagnostic',action='store_true',help='no-augmentation fit check with per-batch parameter updates');a=p.parse_args()
    run=(a.run_dir or (a.resume.resolve().parent.parent if a.resume else None) or ROOT/'learning/kitchen_yolo/runs'/('medium-'+datetime.now().strftime('%Y%m%d-%H%M%S'))).resolve()
    run.mkdir(parents=True,exist_ok=bool(a.resume));started=time.perf_counter()
    previous=json.loads((run/'progress.json').read_text(encoding='utf-8')) if a.resume and (run/'progress.json').exists() else {}
    prior_elapsed=previous.get('elapsed_seconds',0)
    state=dict(phase='preparing',epoch=0,epochs=a.epochs,percent=0,run_dir=str(run),pid=os.getpid())
    def write(**updates):
        state.update(updates);state['elapsed_seconds']=prior_elapsed+time.perf_counter()-started
        publish_progress(run/'progress.json',state)
    write()
    publish_progress(ROOT/'learning/kitchen_yolo/latest-run.json',dict(run_dir=str(run),pid=os.getpid(),status_file=str(run/'progress.json')))
    if not a.no_progress_window:
        pythonw=ROOT/'.conda/pythonw.exe'
        try:subprocess.Popen([str(pythonw),str(Path(__file__).with_name('progress.py')),'--status',str(run/'progress.json')],creationflags=0x08000000)
        except OSError as error:state['progress_window_error']=str(error)
    seen=0
    optimizer_steps=0
    def train_start(trainer):
        def counted_step(optimizer,args,kwargs):
            nonlocal optimizer_steps
            optimizer_steps+=1
        trainer.optimizer.register_step_post_hook(counted_step)
        write(optimizer_steps=0,nbs=a.batch,diagnostic=a.diagnostic,augmentation=augmentation_parameters(a.diagnostic or a.no_augment,a.mild_augment and not a.no_augment))
    def epoch_start(trainer):
        nonlocal seen
        seen=0;write(phase='training',epoch=trainer.epoch+1,percent=100*trainer.epoch/a.epochs)
    def batch_end(trainer):
        nonlocal seen
        seen+=1;fraction=trainer.epoch+seen/max(1,len(trainer.train_loader))
        losses=trainer.label_loss_items(trainer.tloss,prefix='train')
        write(phase='training',epoch=trainer.epoch+1,percent=min(99.8,100*fraction/a.epochs),losses=losses,optimizer_steps=optimizer_steps)
    def fit_end(trainer):
        done=min(trainer.epoch+1,a.epochs);elapsed=prior_elapsed+time.perf_counter()-started
        metrics={str(k):float(v) for k,v in trainer.metrics.items() if math.isfinite(float(v))}
        write(phase='training',epoch=done,percent=min(99.9,100*done/a.epochs),metrics=metrics,
              eta_seconds=(elapsed/done)*(a.epochs-done) if done>0 else None)
    best_box=[previous.get('best_box_map50',-math.inf)]
    def save_box_best(trainer):
        score=float(trainer.metrics.get('metrics/mAP50(B)',-math.inf))
        if math.isfinite(score) and score>best_box[0] and Path(trainer.last).is_file():
            destination=run/'weights/best-box.pt'
            shutil.copy2(trainer.last,destination);best_box[0]=score
            write(best_box_map50=score,best_box_epoch=trainer.epoch+1,best_box=str(destination))
    try:
        if a.data:
            data=a.data.resolve()
            snapshot=json.loads((data.parent/'label-snapshot.json').read_text(encoding='utf-8'))
            sizes=[v['input_size'][0] for v in snapshot.get('transforms',{}).values()]
            if not sizes:raise ValueError('native frozen dataset has no pixel-preserving transforms')
            report=dict(ready=True,input_size=max(sizes))
        else:report,data=prepare()
        if not report['ready']:raise ValueError(f'尚缺 {report["missing_boxes"]} 个真实实例框，其他问题 {len(report["errors"])} 项')
        if a.imgsz is not None and a.imgsz<report['input_size']:raise ValueError('输入尺寸不得小于原生像素补边尺寸')
        input_size=a.imgsz or report['input_size']
        write(model_size=a.model_size,input_size=input_size,preprocessing='native ROI pixels + padding; no baseline resizing')
        from ultralytics import YOLO
        weights=a.initial_weights.resolve() if a.initial_weights else ROOT/f'learning/kitchen_yolo/weights/yolo26{a.model_size}-pose.pt'
        write(initial_weights=str(weights),no_augment=a.no_augment)
        if not weights.exists():raise ValueError('缺少YOLO26m-pose预训练权重')
        model=YOLO(str(a.resume) if a.resume else str(weights))
        model.add_callback('on_train_start',train_start)
        model.add_callback('on_train_epoch_start',epoch_start)
        model.add_callback('on_train_batch_end',batch_end)
        model.add_callback('on_fit_epoch_end',fit_end)
        model.add_callback('on_model_save',save_box_best)
        model.add_callback('on_val_start',lambda validator:write(phase='validating'))
        model.train(data=str(data),epochs=a.epochs,batch=a.batch,imgsz=input_size,device=0,workers=0,
            project=str(run.parent),name=run.name,exist_ok=True,resume=str(a.resume) if a.resume else False,
            optimizer='AdamW',lr0=.0003,lrf=.1,cos_lr=True,patience=0 if a.diagnostic else 35,
            nbs=a.batch,warmup_epochs=0 if a.diagnostic else 3,warmup_bias_lr=.0003,
            **augmentation_parameters(a.diagnostic or a.no_augment,a.mild_augment and not a.no_augment),seed=17,deterministic=True,amp='bf16',plots=True)
        if (run/'weights/best-box.pt').exists():
            from ultralytics.utils.torch_utils import strip_optimizer
            strip_optimizer(run/'weights/best-box.pt')
        write(phase='completed',percent=100,eta_seconds=0,best=str(run/'weights/best.pt'),
              early_stopped=state['epoch']<a.epochs)
    except BaseException as error:
        write(phase='failed',error=str(error));(run/'error.txt').write_text(traceback.format_exc(),encoding='utf-8');raise


if __name__=='__main__':main()
