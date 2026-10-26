"""Interactive on-demand YOLO video replay; no game input, tracking, or full-video precompute."""
import argparse
from collections import deque
from datetime import datetime
import json
import os
from pathlib import Path
import queue
import threading
import time

import cv2
import numpy as np

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent.parent
DEFAULT_VIDEO=ROOT/'runtime/jump-rope/recordings/20261006-115004-094950/screen.avi'
DEFAULT_WEIGHTS=HERE/'runs/temporal-control-05/weights/last.pt'
(HERE/'.ultralytics').mkdir(exist_ok=True)
os.environ.setdefault('YOLO_CONFIG_DIR',str(HERE/'.ultralytics'))


def roi_bounds(shape,bottom=540):
    h,w=shape[:2]
    return round(w*240/1280),0,round(w*1120/1280),round(h*bottom/720)


def render_frame(packet,mask_enabled=True,roi_only=False):
    view=packet['image'].copy();x0,y0,x1,y1=packet['roi']
    if mask_enabled:
        part=view[y0:y1,x0:x1];mask=packet['mask']
        tint=np.empty_like(part);tint[:]=(255,230,0)
        blend=cv2.addWeighted(part,.25,tint,.75,0);part[mask]=blend[mask]
    if roi_only:return view[y0:y1,x0:x1]
    cv2.rectangle(view,(x0,y0),(x1-1,y1-1),(0,220,255),1)
    return view


class Engine:
    def __init__(self,args):
        import torch
        from ultralytics import YOLO
        if not args.weights.is_file():raise FileNotFoundError(f'模型文件不存在：{args.weights}')
        if not torch.cuda.is_available():raise RuntimeError('CUDA 不可用；本程序不会静默切换到 CPU。')
        self.torch=torch;self.model=YOLO(args.weights)
        self.history_enabled=getattr(args,'history',False)
        self.history_masks=deque(maxlen=2);self.history_last=None;self.history_config=None
        seed_path=getattr(args,'history_seed_weights',None) or (HERE/'runs/temporal-control-05/weights/last.pt' if any(version in str(args.weights) for version in ('06-', '07-')) else HERE/'runs/hard-full-02/weights/best.pt')
        if self.history_enabled and not Path(seed_path).is_file():
            if getattr(args,'history_seed_weights',None):raise FileNotFoundError(seed_path)
            seed_path=HERE/'runs/temporal-history-07-late/weights/last.pt'
            print('未携带旧单帧权重：用07版原图推理初始化两帧历史；不影响后续递归模式。',flush=True)
        self.history_seed=YOLO(seed_path) if self.history_enabled else None
        self.cap=cv2.VideoCapture(str(args.video))
        if not self.cap.isOpened():raise RuntimeError(f'无法打开录像：{args.video}')
        self.count=int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps=float(self.cap.get(cv2.CAP_PROP_FPS)) or 60.
        self.gpu=torch.cuda.get_device_name(0);self.position=None;self.stamps=None
        if args.video.resolve()==DEFAULT_VIDEO.resolve():
            path=args.video.parent/'timestamps.json'
            if path.exists():
                data=json.loads(path.read_bytes())
                stamps=[float(r['t']) for r in data]
                if len(stamps)==self.count and all(b>=a for a,b in zip(stamps,stamps[1:])):self.stamps=stamps
        self.time_source='recorded timestamps' if self.stamps else 'video nominal FPS'

    def seconds(self,frame):
        return self.stamps[frame]-self.stamps[0] if self.stamps else frame/self.fps

    def period(self,frame):
        if self.stamps and frame+1<self.count:return max(.001,self.stamps[frame+1]-self.stamps[frame])
        return 1/self.fps

    def read(self,frame):
        frame=max(0,min(self.count-1,int(frame)))
        if self.position!=frame:self.cap.set(cv2.CAP_PROP_POS_FRAMES,frame)
        ok,image=self.cap.read()
        if not ok:raise RuntimeError(f'录像第 {frame} 帧读取失败')
        actual=int(round(self.cap.get(cv2.CAP_PROP_POS_FRAMES)))-1
        if actual!=frame:raise RuntimeError(f'录像跳转不一致：请求 {frame}，实际 {actual}')
        self.position=frame+1
        return image

    def predict(self,crop,config,model=None):
        result=(self.model if model is None else model).predict(crop,imgsz=config['imgsz'],rect=False,device=0,quantize=16,
                                  conf=config['conf'],retina_masks=True,verbose=False)[0]
        mask=np.zeros(crop.shape[:2],bool)
        if result.masks is not None:
            values=result.masks.data.any(0).cpu().numpy().astype(np.uint8)
            mask=cv2.resize(values,(crop.shape[1],crop.shape[0]),interpolation=cv2.INTER_NEAREST)>0
        return mask,len(result.boxes)

    def warmup(self,frame,config):
        image=self.read(frame);x0,y0,x1,y1=roi_bounds(image.shape,540)
        crop=image[y0:y1,x0:x1].copy()
        for _ in range(3):self.predict(crop,config)
        self.torch.cuda.synchronize()

    def process(self,frame,config):
        start=time.perf_counter();image=self.read(frame);read_done=time.perf_counter()
        x0,y0,x1,y1=roi_bounds(image.shape,540);crop=image[y0:y1,x0:x1].copy()
        self.torch.cuda.synchronize();infer_start=time.perf_counter()
        history_seeded=False
        if self.history_enabled:
            from run_temporal_trial import composite
            signature=(config['imgsz'],config['conf'],crop.shape)
            if frame!=self.history_last or signature!=self.history_config:
                self.history_masks.clear();history_seeded=True
                for previous in [frame-2,frame-1]:
                    if previous<0:self.history_masks.append(np.zeros(crop.shape[:2],bool))
                    else:
                        prior=self.read(previous);a,b,c,d=roi_bounds(prior.shape,540)
                        value,_=self.predict(prior[b:d,a:c].copy(),config,self.history_seed)
                        self.history_masks.append(value)
            input_image=composite(crop,*self.history_masks)
            mask,instances=self.predict(input_image,config)
            self.history_masks.append(mask.copy());self.history_last=frame+1;self.history_config=signature
        else:mask,instances=self.predict(crop,config)
        self.torch.cuda.synchronize();done=time.perf_counter()
        return dict(kind='frame',frame=frame,video_seconds=self.seconds(frame),image=image,mask=mask,
                    roi=[x0,y0,x1,y1],instances=instances,pixels=int(mask.sum()),
                    read_ms=(read_done-start)*1000,inference_ms=(done-infer_start)*1000,
                    worker_ms=(done-start)*1000,started=start,completed=done,config=dict(config),
                    history_enabled=self.history_enabled,history_seeded=history_seeded)

    def close(self):self.cap.release()


class Worker(threading.Thread):
    def __init__(self,args,engine_factory=Engine):
        super().__init__(daemon=True)
        self.args=args;self.factory=engine_factory;self.condition=threading.Condition()
        self.results=queue.Queue(maxsize=1);self.messages=queue.Queue()
        self.config={'imgsz':args.imgsz,'conf':args.conf,'roi_bottom':540};self.pending=args.start
        self.playing=args.autoplay;self.stopped=False;self.version=0;self.last=args.start

    def seek(self,frame):
        with self.condition:
            self.playing=False;self.pending=int(frame);self.version+=1;self.condition.notify_all()

    def play(self,value):
        with self.condition:self.playing=value;self.condition.notify_all()

    def settings(self,config,frame):
        with self.condition:
            self.config=dict(config);self.pending=frame;self.version+=1;self.condition.notify_all()

    def stop(self):
        with self.condition:self.stopped=True;self.condition.notify_all()

    def run(self):
        engine=None
        try:
            engine=self.factory(self.args)
            with self.condition:self.pending=max(0,min(engine.count-1,self.pending))
            self.messages.put(dict(kind='info',count=engine.count,fps=engine.fps,gpu=engine.gpu,time_source=engine.time_source))
            engine.warmup(self.pending,self.config)
            while True:
                with self.condition:
                    while not self.stopped and self.pending is None and not self.playing:self.condition.wait()
                    if self.stopped:break
                    requested=self.pending if self.pending is not None else self.last+1
                    self.pending=None
                    if requested>=engine.count:
                        self.playing=False;self.messages.put({'kind':'eof'});continue
                    frame=max(0,min(engine.count-1,requested));version=self.version;config=dict(self.config)
                packet=engine.process(frame,config);packet['version']=version
                with self.condition:
                    self.last=frame
                    if version==self.version and not self.stopped:
                        try:self.results.get_nowait()
                        except queue.Empty:pass
                        self.results.put_nowait(packet)
                    # Process every source frame; slow inference slows replay, never skips source frames.
                    if self.playing and self.pending is None and not self.stopped:
                        self.condition.wait(max(0,engine.period(frame)-(time.perf_counter()-packet['started'])))
        except Exception as exc:
            self.messages.put(dict(kind='error',error=str(exc)))
        finally:
            if engine is not None:engine.close()


class Viewer:
    def __init__(self,root,args):
        import tkinter as tk
        from tkinter import ttk
        from PIL import Image,ImageTk
        self.tk=tk;self.Image=Image;self.ImageTk=ImageTk;self.root=root;self.args=args
        self.worker=Worker(args);self.packet=None;self.photo=None;self.count=0;self.running=args.autoplay
        self.display_times=deque(maxlen=60);self.closing=False;self.updating=False;self.config_timer=None
        model_label=args.weights.parent.name+' · TensorRT' if args.weights.suffix=='.engine' else args.weights.parent.parent.name
        root.title(f'YOLO 两帧历史 · {model_label}' if getattr(args,'history',False) else 'YOLO 完整绳形 · 方形输入修正版');root.geometry('1160x860')
        row=ttk.Frame(root);row.pack(fill='x',padx=10,pady=8)
        self.play_button=ttk.Button(row,text='暂停' if self.running else '播放 / 空格',command=self.toggle);self.play_button.pack(side='left')
        ttk.Button(row,text='上一帧',command=lambda:self.step(-1)).pack(side='left',padx=4)
        ttk.Button(row,text='下一帧',command=lambda:self.step(1)).pack(side='left')
        self.jump=tk.StringVar(value=str(args.start));ttk.Entry(row,textvariable=self.jump,width=8).pack(side='left',padx=8)
        ttk.Button(row,text='跳到帧号',command=self.jump_to).pack(side='left')
        self.preset=ttk.Combobox(row,values=['763','1595','2100','4000','4433','5100','6600','8800'],width=8,state='readonly')
        self.preset.pack(side='left',padx=8);self.preset.bind('<<ComboboxSelected>>',lambda e:self.seek(int(self.preset.get())))
        ttk.Button(row,text='保存当前帧',command=self.save).pack(side='right')
        row=ttk.Frame(root);row.pack(fill='x',padx=10)
        self.mask_enabled=tk.BooleanVar(value=True);self.roi_only=tk.BooleanVar(value=False)
        ttk.Checkbutton(row,text='青色预测（取消看原图）',variable=self.mask_enabled,command=self.redraw).pack(side='left')
        ttk.Checkbutton(row,text='只看识别区域',variable=self.roi_only,command=self.redraw).pack(side='left',padx=12)
        ttk.Label(row,text='输入尺寸').pack(side='left');self.size=tk.StringVar(value=str(args.imgsz))
        select=ttk.Combobox(row,textvariable=self.size,values=['960'] if args.weights.suffix=='.engine' else ['640','960','1280'],width=6,state='readonly');select.pack(side='left',padx=5)
        select.bind('<<ComboboxSelected>>',lambda e:self.configure())
        ttk.Label(row,text='裁剪底边：540').pack(side='left',padx=5)
        ttk.Label(row,text='阈值').pack(side='left');self.conf=tk.DoubleVar(value=args.conf)
        slider=ttk.Scale(row,from_=.05,to=.9,variable=self.conf,command=lambda v:self.configure());slider.pack(side='left',fill='x',expand=True,padx=5)
        self.conf_text=ttk.Label(row,text=f'{args.conf:.2f}',width=5);self.conf_text.pack(side='left')
        self.image_widget=ttk.Label(root,anchor='center');self.image_widget.pack(fill='both',expand=True,padx=10,pady=6)
        self.progress=ttk.Scale(root,from_=0,to=1);self.progress.pack(fill='x',padx=12)
        self.progress.bind('<ButtonRelease-1>',lambda e:self.seek(round(self.progress.get())))
        self.position=ttk.Label(root,text='正在加载模型、录像并预热…');self.position.pack(anchor='w',padx=12)
        self.stats=ttk.Label(root,text='',wraplength=1120);self.stats.pack(anchor='w',padx=12,pady=3)
        self.info=ttk.Label(root,text='逐帧识别、不主动跳帧；速度不足时播放会变慢。未检出会清空，不保留旧掩膜。',wraplength=1120)
        self.info.pack(anchor='w',padx=12,pady=3)
        ttk.Label(root,text='单帧网络，无历史预测/曲线补全后处理，无游戏按键。界面提交耗时不等于显示器实际呈现延迟。',wraplength=1120).pack(anchor='w',padx=12,pady=3)
        root.protocol('WM_DELETE_WINDOW',self.close)
        root.bind('<space>',self.space);root.bind('<Left>',lambda e:self.key_step(e,-1));root.bind('<Right>',lambda e:self.key_step(e,1))
        self.worker.start();root.after(10,self.poll)

    def config(self):return {'imgsz':int(self.size.get()),'conf':float(self.conf.get()),'roi_bottom':540}
    def configure(self):
        self.conf_text.configure(text=f'{self.conf.get():.2f}')
        if self.config_timer:self.root.after_cancel(self.config_timer)
        def apply():
            self.config_timer=None
            if self.packet:self.worker.settings(self.config(),self.packet['frame'])
        self.config_timer=self.root.after(180,apply)
    def seek(self,frame):
        if not self.count:return
        frame=max(0,min(self.count-1,int(frame)));self.running=False;self.play_button.configure(text='播放 / 空格')
        self.display_times.clear();self.worker.seek(frame);self.position.configure(text=f'正在跳到第 {frame} 帧…')
    def jump_to(self):
        try:self.seek(int(self.jump.get()))
        except ValueError:self.position.configure(text='请输入整数帧号。')
    def step(self,direction):
        if self.packet:self.seek(self.packet['frame']+direction)
    def toggle(self):
        if not self.count:return
        self.running=not self.running;self.display_times.clear();self.worker.play(self.running)
        self.play_button.configure(text='暂停' if self.running else '播放 / 空格')
    def space(self,event):
        if event.widget.winfo_class() not in ('TEntry','TCombobox','Entry'):self.toggle();return 'break'
    def key_step(self,event,direction):
        if event.widget.winfo_class() not in ('TEntry','TCombobox','Entry'):self.step(direction);return 'break'

    def redraw(self):
        if self.packet:self.draw(self.packet,count_frame=False)
    def draw(self,packet,count_frame=True):
        start=time.perf_counter();view=render_frame(packet,self.mask_enabled.get(),self.roi_only.get())
        prepared=time.perf_counter();im=self.Image.fromarray(cv2.cvtColor(view,cv2.COLOR_BGR2RGB))
        w=max(320,self.image_widget.winfo_width());h=max(180,self.image_widget.winfo_height())
        im.thumbnail((w,h),self.Image.Resampling.BILINEAR)
        self.photo=self.ImageTk.PhotoImage(im);self.image_widget.configure(image=self.photo)
        done=time.perf_counter()
        if count_frame:self.display_times.append((done,packet['video_seconds']))
        fps=speed=0.
        if len(self.display_times)>=2:
            dt=self.display_times[-1][0]-self.display_times[0][0]
            if dt>0:
                fps=(len(self.display_times)-1)/dt;speed=(self.display_times[-1][1]-self.display_times[0][1])/dt
        self.jump.set(str(packet['frame']));self.progress.set(packet['frame'])
        self.position.configure(text=f'帧 {packet["frame"]} / {self.count-1}   录像 {packet["video_seconds"]:.2f}s   实例 {packet["instances"]}   掩膜 {packet["pixels"]} 像素   '+('未检出' if not packet['instances'] else '预测不等于正确'))
        end_to_end=(done-packet['started'])*1000 if count_frame else None
        self.stats.configure(text=f'解码 {packet["read_ms"]:.1f}ms ｜识别含前后处理/回传 {packet["inference_ms"]:.1f}ms ｜叠加 {(prepared-start)*1000:.1f}ms ｜界面提交 {(done-prepared)*1000:.1f}ms ｜'+(f'解码到界面提交 {end_to_end:.1f}ms ｜' if end_to_end is not None else '')+f'展示 {fps:.1f}FPS / 播放 {speed:.2f}×')
        if count_frame:packet['display_submit_ms']=(done-prepared)*1000;packet['end_to_end_submit_ms']=end_to_end

    def poll(self):
        if self.closing:return
        try:
            while True:
                msg=self.worker.messages.get_nowait()
                if msg['kind']=='info':
                    self.count=msg['count'];self.progress.configure(to=self.count-1)
                    self.info.configure(text=f'{msg["gpu"]} ｜{self.args.weights.parent.parent.name}/{self.args.weights.name} ｜录像时间来自 {msg["time_source"]}。逐帧处理，慢时放慢播放。')
                elif msg['kind']=='eof':self.running=False;self.play_button.configure(text='播放 / 空格');self.info.configure(text='已到录像末尾，可跳转继续查看。')
                else:self.running=False;self.play_button.configure(text='播放 / 空格');self.info.configure(text='处理失败：'+msg['error'])
        except queue.Empty:pass
        try:
            packet=self.worker.results.get_nowait()
            if packet['version']==self.worker.version:
                first=self.packet is None;self.packet=packet;self.draw(packet)
                if first:print(f'Preview ready: frame={packet["frame"]}, instances={packet["instances"]}',flush=True)
        except queue.Empty:pass
        self.root.after(5,self.poll)

    def save(self):
        if not self.packet:return
        packet=self.packet;folder=HERE/'results'/('live-preview-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir(parents=True)
        cv2.imwrite(str(folder/'original.jpg'),packet['image'])
        cv2.imwrite(str(folder/'overlay.jpg'),render_frame(packet,True,False))
        full=np.zeros(packet['image'].shape[:2],np.uint8);x0,y0,x1,y1=packet['roi'];full[y0:y1,x0:x1]=np.uint8(packet['mask'])*255
        cv2.imwrite(str(folder/'prediction-mask.png'),full)
        record={k:v for k,v in packet.items() if k not in ('image','mask','started','completed')}
        record.update(video=str(self.args.video),weights=str(self.args.weights),meaning='two prior predicted masks fed back; square inference; snapshot not accuracy ground truth' if getattr(self.args,'history',False) else 'raw complete-rope prediction; no temporal memory; snapshot not accuracy ground truth')
        (folder/'record.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        self.info.configure(text='当前帧已保存：'+str(folder))

    def close(self):
        self.closing=True;self.worker.stop();self.worker.join(timeout=2);self.root.destroy()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--video',type=Path,default=DEFAULT_VIDEO)
    p.add_argument('--weights',type=Path,default=DEFAULT_WEIGHTS)
    p.add_argument('--history',action='store_true',help='Feed two previous predicted masks into the historical model.')
    p.add_argument('--history-seed-weights',type=Path)
    p.add_argument('--start',type=int,default=650)
    p.add_argument('--imgsz',type=int,choices=[640,960,1280],default=960)
    p.add_argument('--conf',type=float,default=.25)
    p.add_argument('--roi-bottom',type=int,choices=[540],default=540)
    p.add_argument('--autoplay',action='store_true')
    p.add_argument('--headless',action='store_true')
    p.add_argument('--frames',type=int,default=8)
    p.add_argument('--output',type=Path)
    args=p.parse_args()
    if args.history and args.weights==DEFAULT_WEIGHTS:args.weights=HERE/'runs/temporal-history-07-late/weights/last.pt'
    if args.weights.suffix=='.engine' and args.imgsz!=960:p.error('This static TensorRT preview engine requires --imgsz960.')
    if not .01<=args.conf<=.99:p.error('--conf must be between0.01 and0.99')
    if args.frames<1:p.error('--frames must be positive')
    if args.headless:
        engine=Engine(args);config={'imgsz':args.imgsz,'conf':args.conf,'roi_bottom':args.roi_bottom};rows=[]
        start=max(0,min(args.start,engine.count-1))
        try:
            engine.warmup(start,config)
            for frame in range(start,min(engine.count,start+args.frames)):
                packet=engine.process(frame,config)
                rows.append({k:v for k,v in packet.items() if k not in ('image','mask','started','completed')})
            if args.output:
                args.output.mkdir(parents=True,exist_ok=False)
                cv2.imwrite(str(args.output/'last-overlay.jpg'),render_frame(packet))
                (args.output/'smoke.json').write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(dict(processed=[r['frame'] for r in rows],gpu=engine.gpu,
                                  median_worker_ms=float(np.median([r['worker_ms'] for r in rows])),ui_verified=False),ensure_ascii=False))
        finally:engine.close()
    else:
        import tkinter as tk
        root=tk.Tk();Viewer(root,args);root.mainloop()


if __name__=='__main__':main()
