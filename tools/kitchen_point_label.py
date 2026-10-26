"""Offline point and ignore-region annotation GUI."""
import argparse
import copy
import json
import subprocess
import os
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox,filedialog
import cv2
from modular_agent.realtime.kitchen_labels import LabelStore,atomic_json


class Annotator:
    def __init__(self,root,recording,catalog_path,labels_dir=None,box_mode=False,selection_mode=False):
        self.root=root;self.store=LabelStore(recording,labels_dir);self.catalog_path=Path(catalog_path)
        self.catalog=json.loads(self.catalog_path.read_text(encoding='utf-8'))
        self.classes={c['id']:c for c in self.catalog['classes']}
        self.cap=cv2.VideoCapture(str(Path(recording)/'screen.avi'))
        self.index=min(range(len(self.store.stamps)),key=lambda i:abs(self.store.stamps[i]['t']-35))
        completed=sorted(int(k) for k,f in self.store.data['frames'].items() if f['complete'])
        if completed:self.index=completed[0]
        queue_path=self.store.labels_dir/'selection.json'
        self.selection=json.loads(queue_path.read_text(encoding='utf-8')) if queue_path.exists() else dict(frames=[])
        if self.selection.get('timestamps_sha256',self.store.data['timestamps_sha256'])!=self.store.data['timestamps_sha256']:raise ValueError('待标队列与录像不匹配')
        self.queue_indices=[f['video_index'] for f in self.selection['frames']]
        if any(not 0<=i<len(self.store.stamps) for i in self.queue_indices):raise ValueError('invalid selection frame')
        if self.queue_indices:
            self.index=next((i for i in self.queue_indices if not self.store.data['frames'].get(str(i),{}).get('complete')),self.queue_indices[0])
        self.selection_mode=selection_mode
        self.box_mode=box_mode
        if box_mode:
            candidates=self.queue_indices or sorted(int(k) for k in self.store.data['frames'])
            self.index=next((i for i in candidates if any('bbox' not in p for p in self.store.data['frames'].get(str(i),{}).get('points',[]))),self.index)
        self.prediction_items=[];self.show_predictions=tk.BooleanVar(value=True);self.zoom=1.0;self.prediction_job=None;self.prediction_poll=None;self.class_scores={}
        self.history=[];self.drag=None
        root.title('厨房实例点标注 — 一物一点，拖框忽略不确定区域')
        toolbar=ttk.Frame(root);toolbar.pack(fill='x')
        ttk.Button(toolbar,text='选择录像…',command=self.open_recording).pack(side='left')
        ttk.Button(toolbar,text='放大 +',command=lambda:self.set_zoom(self.zoom*1.25)).pack(side='left')
        ttk.Button(toolbar,text='缩小 −',command=lambda:self.set_zoom(self.zoom/1.25)).pack(side='left')
        ttk.Button(toolbar,text='适应窗口',command=lambda:self.set_zoom(1)).pack(side='left')
        self.predict_button=ttk.Button(toolbar,text='推理当前帧 / 排列类别',command=self.predict_classes);self.predict_button.pack(side='left')
        ttk.Checkbutton(toolbar,text='显示推理结果（蓝框，≥0.25）',variable=self.show_predictions,command=self.render).pack(side='left')
        top=ttk.Frame(root);top.pack(fill='x')
        self.choice=tk.StringVar()
        self.combo=ttk.Combobox(top,textvariable=self.choice,state='readonly',width=32)
        self.combo.pack(side='left');self.refresh_classes();self.combo.bind('<<ComboboxSelected>>',lambda e:self.reference())
        self.new_id=ttk.Entry(top,width=16);self.new_id.pack(side='left')
        self.new_name=ttk.Entry(top,width=16);self.new_name.pack(side='left')
        ttk.Button(top,text='添加类别（ID / 中文名）',command=self.add_class).pack(side='left')
        self.mode=tk.StringVar(value='browse' if selection_mode else 'box' if box_mode else 'point')
        if selection_mode:ttk.Radiobutton(top,text='仅浏览选帧',variable=self.mode,value='browse').pack(side='left')
        ttk.Radiobutton(top,text='实例点',variable=self.mode,value='point').pack(side='left')
        ttk.Radiobutton(top,text='忽略区域',variable=self.mode,value='ignore').pack(side='left')
        ttk.Radiobutton(top,text='补实例框',variable=self.mode,value='box').pack(side='left')
        review_bar=ttk.Frame(root);review_bar.pack(fill='x')
        ttk.Label(review_bar,text='已标注帧：').pack(side='left')
        self.review_choice=tk.StringVar()
        self.review_combo=ttk.Combobox(review_bar,textvariable=self.review_choice,state='readonly',width=55)
        self.review_combo.pack(side='left')
        self.review_combo.bind('<<ComboboxSelected>>',lambda e:self.navigate(self.review_indices[self.review_combo.current()]))
        ttk.Button(review_bar,text='上一标注帧',command=lambda:self.labeled_step(-1)).pack(side='left')
        ttk.Button(review_bar,text='下一标注帧',command=lambda:self.labeled_step(1)).pack(side='left')
        ttk.Button(review_bar,text='重新载入外部标注',command=self.reload_labels).pack(side='left')
        if self.queue_indices or selection_mode:
            queue_bar=ttk.Frame(root);queue_bar.pack(fill='x')
            ttk.Label(queue_bar,text='代表帧待标队列：').pack(side='left')
            self.queue_choice=tk.StringVar()
            self.queue_combo=ttk.Combobox(queue_bar,textvariable=self.queue_choice,state='readonly',width=72)
            self.queue_combo.pack(side='left')
            self.queue_combo.bind('<<ComboboxSelected>>',lambda e:self.navigate(self.queue_indices[self.queue_combo.current()]))
            ttk.Button(queue_bar,text='上一张待标帧',command=lambda:self.queue_step(-1)).pack(side='left')
            ttk.Button(queue_bar,text='下一张待标帧',command=lambda:self.queue_step(1)).pack(side='left')
            if selection_mode:
                ttk.Button(queue_bar,text='加入当前帧',command=self.select_current).pack(side='left')
                ttk.Button(queue_bar,text='移出当前帧',command=self.unselect_current).pack(side='left')
        body=ttk.Frame(root);body.pack(fill='both',expand=True)
        viewer=ttk.Frame(body);viewer.pack(side='left',fill='both',expand=True)
        viewer.rowconfigure(0,weight=1);viewer.columnconfigure(0,weight=1)
        self.canvas=tk.Canvas(viewer,width=1100,height=620,highlightthickness=0);self.canvas.grid(row=0,column=0,sticky='nsew')
        horizontal=ttk.Scrollbar(viewer,orient='horizontal',command=self.canvas.xview);horizontal.grid(row=1,column=0,sticky='ew')
        vertical=ttk.Scrollbar(viewer,orient='vertical',command=self.canvas.yview);vertical.grid(row=0,column=1,sticky='ns')
        self.canvas.configure(xscrollcommand=horizontal.set,yscrollcommand=vertical.set)
        side=ttk.Frame(body);side.pack(side='left',fill='y')
        self.ref_label=ttk.Label(side);self.ref_label.pack()
        self.listbox=tk.Listbox(side,width=30,height=22,exportselection=False);self.listbox.pack()
        self.listbox.bind('<<ListboxSelect>>',self.highlight_selection)
        ttk.Button(side,text='删除选中标签',command=self.delete).pack(fill='x')
        self.canvas.bind('<ButtonPress-1>',self.press)
        self.canvas.bind('<B1-Motion>',self.motion)
        self.canvas.bind('<ButtonRelease-1>',self.release)
        self.slider=tk.Scale(root,from_=0,to=len(self.store.stamps)-1,orient='horizontal',length=1100)
        self.slider.set(self.index);self.slider.pack(fill='x')
        self.slider.bind('<ButtonRelease-1>',lambda e:self.navigate(int(self.slider.get())))
        buttons=ttk.Frame(root);buttons.pack(fill='x')
        for label,step in [('前10秒',-10),('前1帧',-1),('后1帧',1),('后10秒',10)]:
            ttk.Button(buttons,text=label,command=lambda v=step:self.step(v)).pack(side='left')
        ttk.Button(buttons,text='撤销',command=self.undo).pack(side='left')
        ttk.Button(buttons,text='保存',command=self.save).pack(side='left')
        ttk.Button(buttons,text='导出已完成帧',command=self.export).pack(side='left')
        self.complete=tk.BooleanVar(value=False)
        ttk.Checkbutton(buttons,text='本帧已完成（有标注自动完成）',variable=self.complete,command=self.mark_complete).pack(side='left')
        self.status=tk.StringVar();ttk.Label(root,textvariable=self.status).pack(fill='x')
        ttk.Label(root,text=('拖动时间轴浏览，点击加入当前帧。队列自动保存；默认仅浏览，不会自动标注或训练。' if selection_mode else '补框：选右侧实例再拖框，框住可见部分且包含绿点（不猜遮挡部分）。红色加粗为当前选中实例，黄色为其他实例框；自动保存并选下一缺框实例。')).pack(fill='x')
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.navigate(self.index);self.reference()

    def persist_frame(self):
        # User policy: any frame with human instances is considered complete.
        if self.frame['points']:self.frame['complete']=True
        self.store.save()
        folder=self.store.labels_dir/'frames';folder.mkdir(parents=True,exist_ok=True)
        path=folder/f'frame-{self.index:06d}.png'
        if not path.exists() and not cv2.imwrite(str(path),self.image):raise OSError('无法保存帧图像')

    def set_zoom(self,value):
        selected=self.listbox.curselection()
        self.zoom=max(.5,min(4,value))
        h,w=self.image.shape[:2];self.scale=min(1100/w,680/h)*self.zoom
        self.render()
        if selected:
            self.listbox.selection_clear(0,'end');self.listbox.selection_set(selected[0]);self.highlight_selection()

    def open_recording(self):
        path=filedialog.askopenfilename(title='选择本项目录制的 screen.avi',initialdir=str(Path(__file__).resolve().parents[1]/'runtime/kitchen/sessions'),filetypes=[('录制视频','*.avi')])
        if not path:return
        recording=Path(path).parent
        if Path(path).name!='screen.avi' or not (recording/'timestamps.json').exists():
            messagebox.showerror('录像格式','请选择本项目录制目录里的 screen.avi，需保留同目录 timestamps.json。');return
        workspace=Path(__file__).resolve().parents[1]/'runtime/kitchen/manual-labeling'/recording.name
        try:
            # Validate the new source before closing the current editor.
            LabelStore(recording,workspace)
            self.persist_frame()
        except Exception as error:messagebox.showerror('打开失败',str(error));return
        if self.prediction_poll:self.root.after_cancel(self.prediction_poll)
        self.cap.release()
        for widget in self.root.winfo_children():widget.destroy()
        self.__init__(self.root,recording,self.catalog_path,workspace,self.box_mode,True)

    def apply_prediction(self,scores):
        previous=self.class_id()
        self.class_scores={key:float(value) for key,value in scores.items() if key in self.classes}
        self.refresh_classes()
        for option in self.options:
            if option.rsplit(' | ',1)[-1]==previous:self.choice.set(option);break

    def predict_classes(self):
        if self.prediction_job:return
        project=Path(__file__).resolve().parents[1]
        candidates=[]
        for progress in (project/'learning/kitchen_yolo/runs').glob('**/progress.json'):
            try:
                state=json.loads(progress.read_text(encoding='utf-8'));weights=progress.parent/'weights/best.pt'
                if state.get('phase')=='completed' and weights.exists():candidates.append(weights)
            except (OSError,ValueError):pass
        if not candidates:messagebox.showinfo('预测','还没有已训练完成的模型。');return
        profile=project/'data/kitchen/runtime-profile.json'
        pinned=json.loads(profile.read_text(encoding='utf-8')).get('weights','') if profile.exists() else ''
        model=project/pinned if pinned and (project/pinned).is_file() else max(candidates,key=lambda item:item.stat().st_mtime)
        folder=self.store.labels_dir/'predictions';folder.mkdir(parents=True,exist_ok=True)
        output=folder/f'frame-{self.index:06d}.json'
        if output.exists():output.unlink()
        log=(folder/'predict.log').open('w',encoding='utf-8')
        command=[str(project/'learning/jump_rope_yolo/.venv/Scripts/python.exe'),str(project/'tools/kitchen_suggest_classes.py'),'--recording',str(self.store.recording.resolve()),'--index',str(self.index),'--model',str(model),'--output',str(output),'--roi',json.dumps(self.store.data['roi'])]
        try:self.prediction_job=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,cwd=str(project),creationflags=0x08000000)
        except OSError as error:messagebox.showerror('预测启动失败',str(error));return
        finally:log.close()
        self.predict_button.configure(state='disabled');self.status.set('正在 CPU 预测，标注仍可编辑…')
        index=self.index
        def poll():
            if self.prediction_job.poll() is None:
                self.prediction_poll=self.root.after(250,poll);return
            returncode=self.prediction_job.returncode;self.prediction_job=None;self.prediction_poll=None
            self.predict_button.configure(state='normal')
            if returncode:
                self.status.set('预测失败，日志：'+str(folder/'predict.log'));return
            try:
                result=json.loads(output.read_text(encoding='utf-8'))
                if index==self.index:
                    self.prediction_items=result.get('detections',[]);self.apply_prediction(result['scores']);self.render();self.status.set('推理完成：蓝框为模型结果，菜单已按置信度排序；未修改人工标注。模型：'+model.parent.parent.name)
                else:self.status.set('上一帧预测已保存；当前帧菜单未改变。')
            except (OSError,ValueError) as error:self.status.set('读取预测失败：'+str(error))
        self.prediction_poll=self.root.after(250,poll)

    def save_selection(self):
        self.selection.update(schema_version=1,recording_id=self.store.recording.name,
                              timestamps_sha256=self.store.data['timestamps_sha256'],selected_by='user')
        self.selection['frames'].sort(key=lambda item:item['video_index'])
        atomic_json(self.store.labels_dir/'selection.json',self.selection)
        self.queue_indices=[item['video_index'] for item in self.selection['frames']]
        self.refresh_queue()

    def select_current(self):
        if self.index not in self.queue_indices:
            self.selection['frames'].append(dict(video_index=self.index,t=self.frame['t'],reason='用户选帧'))
            self.save_selection()
        self.status.set(f'已加入第 {self.index} 帧；共选择 {len(self.queue_indices)} 张。尚未自动标注。')

    def unselect_current(self):
        self.selection['frames']=[item for item in self.selection['frames'] if item['video_index']!=self.index]
        self.save_selection()
        self.status.set(f'已从队列移出第 {self.index} 帧；已有标注仍保留。')

    def refresh_queue(self):
        if not self.queue_indices:
            if self.selection_mode:
                self.queue_combo.configure(values=[]);self.queue_choice.set('队列为空：浏览录像后点击加入当前帧')
            return
        values=[]
        done=0
        for position,item in enumerate(self.selection['frames'],1):
            f=self.store.data['frames'].get(str(item['video_index']),{})
            complete=f.get('complete',False);done+=int(complete)
            state='已完成' if complete else '待标注'
            values.append(f'{position}/{len(self.queue_indices)} | {item["t"]:.1f}s | {state} | {item.get("reason","")}')
        self.queue_combo.configure(values=values)
        if self.index in self.queue_indices:self.queue_combo.current(self.queue_indices.index(self.index))
        else:self.queue_choice.set(f'当前为自由浏览；队列已完成 {done}/{len(self.queue_indices)}')

    def queue_step(self,direction):
        if not self.queue_indices:return
        if self.index in self.queue_indices:
            position=max(0,min(self.queue_indices.index(self.index)+direction,len(self.queue_indices)-1))
        else:
            position=0
        self.navigate(self.queue_indices[position])

    def refresh_review_frames(self):
        self.review_indices=sorted(int(k) for k,f in self.store.data['frames'].items()
                                   if f['points'] or f['ignore_regions'] or f['complete'])
        values=[]
        for i in self.review_indices:
            f=self.store.data['frames'][str(i)]
            state='已完成' if f['complete'] else '未完成'
            values.append(f'第 {i} 帧 | {f["t"]:.1f}s | {len(f["points"])} 个点 | {state}')
        self.review_combo.configure(values=values)
        if self.index in self.review_indices:self.review_combo.current(self.review_indices.index(self.index))
        else:self.review_choice.set('当前帧尚无标注')

    def labeled_step(self,direction):
        indices=self.review_indices
        if not indices:return
        options=[i for i in indices if (i-self.index)*direction>0]
        if options:self.navigate(min(options) if direction>0 else max(options))

    def reload_labels(self):
        try:
            self.store.save()
            self.store=LabelStore(self.store.recording,self.store.labels_dir)
            self.catalog=json.loads(self.catalog_path.read_text(encoding='utf-8'))
            self.classes={c['id']:c for c in self.catalog['classes']}
            self.refresh_classes()
            completed=sorted(int(k) for k,f in self.store.data['frames'].items() if f['complete'])
            self.navigate(next((i for i in self.queue_indices if not self.store.data['frames'].get(str(i),{}).get('complete')),self.queue_indices[0]) if self.queue_indices else completed[0] if completed else self.index)
            self.reference()
        except Exception as error:messagebox.showerror('载入失败',str(error))

    def refresh_classes(self):
        keys=sorted(self.classes,key=lambda key:-self.class_scores.get(key,0))
        self.options=[f'{self.classes[key]["name"]}'+(f'  [{self.class_scores[key]:.0%}]' if key in self.class_scores else '')+f' | {key}' for key in keys]
        self.combo.configure(values=self.options)
        if self.choice.get() not in self.options:self.choice.set(self.options[0])

    def class_id(self):return self.choice.get().rsplit(' | ',1)[-1]

    def reference(self):
        c=self.classes[self.class_id()];path=self.catalog_path.parent/c.get('reference','missing')
        image=cv2.imread(str(path)) if path.is_file() else None
        if image is not None:
            scale=min(160/image.shape[1],140/image.shape[0]);image=cv2.resize(image,(max(1,round(image.shape[1]*scale)),max(1,round(image.shape[0]*scale))))
            self.ref_photo=self.photo(image)
            self.ref_label.configure(image=self.ref_photo,text=c['name'],compound='top')
        else:self.ref_label.configure(image='',text=c['name'])

    def add_class(self):
        key=self.new_id.get().strip();name=self.new_name.get().strip()
        if not key or not name or key in self.classes:
            messagebox.showerror('类别','请填写未使用的英文ID和名称');return
        if not all(c.isascii() and (c.isalnum() or c=='_') for c in key):
            messagebox.showerror('类别','ID只支持英文、数字和下划线');return
        value=dict(id=key,name=name,name_status='user_defined')
        self.catalog['classes'].append(value);atomic_json(self.catalog_path,self.catalog)
        self.classes[key]=value;self.refresh_classes();self.choice.set(f'{name} | {key}');self.reference()

    @staticmethod
    def photo(image):
        rgb=cv2.cvtColor(image,cv2.COLOR_BGR2RGB)
        return tk.PhotoImage(data=b'P6\n%d %d\n255\n'%(rgb.shape[1],rgb.shape[0])+rgb.tobytes(),format='PPM')

    def navigate(self,index):
        if hasattr(self,'frame'):self.store.save()
        self.prediction_items=[];self.class_scores={};self.refresh_classes()
        index=max(0,min(index,len(self.store.stamps)-1))
        self.cap.set(cv2.CAP_PROP_POS_FRAMES,index);ok,image=self.cap.read()
        if not ok:raise RuntimeError(f'无法读取帧{index}')
        self.index=index;self.image=image;h,w=image.shape[:2]
        self.frame=self.store.frame(index,w,h);self.history=[];self.drag=None
        self.scale=min(1100/w,680/h)*self.zoom;self.slider.set(index);self.render()

    def render(self):
        h,w=self.image.shape[:2];small=cv2.resize(self.image,(round(w*self.scale),round(h*self.scale)))
        self.current_photo=self.photo(small);c=self.canvas;c.delete('all')
        c.configure(scrollregion=(0,0,small.shape[1],small.shape[0]));c.create_image(0,0,anchor='nw',image=self.current_photo)
        s=self.scale;l,t,r,b=self.store.data['roi'];c.create_rectangle(l*w*s,t*h*s,r*w*s,b*h*s,outline='#00cfff')
        if self.show_predictions.get():
            for prediction in self.prediction_items:
                if prediction['score']<.25:continue
                box=prediction['bbox'];name=self.classes.get(prediction['class_id'],{}).get('name',prediction['class_id'])
                c.create_rectangle(*[v*s for v in box],outline='#008cff',width=2,dash=(5,3))
                c.create_text(box[0]*s,box[1]*s,anchor='sw',fill='#008cff',text=f"预测 {name} {prediction['score']:.2f}")
        self.listbox.delete(0,'end')
        for i,p in enumerate(self.frame['points']):
            x,y=p['x']*s,p['y']*s;c.create_oval(x-5,y-5,x+5,y+5,outline='#00ff00',width=2,tags=(f'point:{i}',))
            label=f'{i+1}:{self.classes.get(p["class_id"],{}).get("name",p["class_id"])}'+(' [有框]' if 'bbox' in p else ' [缺框]')
            if 'bbox' in p:c.create_rectangle(*[v*s for v in p['bbox']],outline='#ffff00',width=2,tags=(f'box:{i}',))
            c.create_text(x+7,y-8,text=label,anchor='sw',fill='#00ff00',tags=(f'label:{i}',))
            self.listbox.insert('end',label)
        for box in self.frame['ignore_regions']:
            c.create_rectangle(*[v*s for v in box],outline='#ff00ff',width=2)
            self.listbox.insert('end',f'忽略区 {box}')
        if self.mode.get()=='box' and self.frame['points']:
            missing=next((i for i,p in enumerate(self.frame['points']) if 'bbox' not in p),0)
            self.listbox.selection_set(missing);self.listbox.see(missing)
        self.highlight_selection()
        self.complete.set(self.frame['complete'])
        self.refresh_review_frames()
        self.refresh_queue()
        count=sum(f['complete'] for f in self.store.data['frames'].values())
        missing_boxes=sum('bbox' not in p for p in self.frame['points'])
        self.status.set(f'帧 {self.index} | {self.frame["t"]:.2f}s | {len(self.frame["points"])} 实例 / 缺框 {missing_boxes} | 已完成 {count} 帧 | 保存于 {self.store.path}')

    def highlight_selection(self,event=None):
        selected=self.listbox.curselection()
        current=selected[0] if selected else None
        for i in range(len(self.frame['points'])):
            active=i==current
            color='#ff3b30' if active else '#00ff00'
            self.canvas.itemconfigure(f'point:{i}',outline=color,width=4 if active else 2)
            self.canvas.itemconfigure(f'box:{i}',outline='#ff3b30' if active else '#ffff00',width=4 if active else 2)
            self.canvas.itemconfigure(f'label:{i}',fill=color,font=('TkDefaultFont',12,'bold') if active else ('TkDefaultFont',10))
            if active:
                for kind in ('box','point','label'):self.canvas.tag_raise(f'{kind}:{i}')

    def snapshot(self):self.history.append(copy.deepcopy(self.frame))

    def changed(self):
        self.persist_frame();self.render()

    def point(self,event):
        return int(self.canvas.canvasx(event.x)/self.scale),int(self.canvas.canvasy(event.y)/self.scale)

    def inside(self,x,y):
        l,t,r,b=self.store.data['roi'];w,h=self.frame['width'],self.frame['height']
        return l*w<=x<r*w and t*h<=y<b*h

    def press(self,event):
        if self.mode.get()=='browse':return
        if self.mode.get() in ['ignore','box']:
            selected=self.listbox.curselection()
            self.box_instance=self.frame['points'][selected[0]]['instance_id'] if selected and selected[0]<len(self.frame['points']) else None
            self.drag=self.point(event);self.rectangle=self.canvas.create_rectangle(*([self.canvas.canvasx(event.x),self.canvas.canvasy(event.y)]*2),outline='#ff00ff')
        else:
            x,y=self.point(event)
            if not self.inside(x,y):return
            self.snapshot();self.store.add_point(self.frame,self.class_id(),x,y);self.changed()

    def motion(self,event):
        if self.drag:
            self.canvas.coords(self.rectangle,self.drag[0]*self.scale,self.drag[1]*self.scale,self.canvas.canvasx(event.x),self.canvas.canvasy(event.y))

    def release(self,event):
        if not self.drag:return
        ax,ay=self.drag;bx,by=self.point(event);self.drag=None
        l,t,r,b=self.store.data['roi'];w,h=self.frame['width'],self.frame['height']
        box=[max(round(l*w),min(ax,bx)),max(round(t*h),min(ay,by)),min(round(r*w),max(ax,bx)),min(round(b*h),max(ay,by))]
        if box[2]-box[0]>=2 and box[3]-box[1]>=2:
            if self.mode.get()=='box':
                instance=self.box_instance
                if instance is None:
                    inside=[p for p in self.frame['points'] if box[0]<=p['x']<box[2] and box[1]<=p['y']<box[3]]
                    if len(inside)==1:instance=inside[0]['instance_id']
                try:
                    # Validate on a copy before recording undo history.
                    trial=copy.deepcopy(self.frame);self.store.set_bbox(trial,instance,box)
                    self.snapshot();self.store.set_bbox(self.frame,instance,box);self.changed()
                except ValueError as error:
                    self.render();messagebox.showerror('实例框',str(error))
            else:
                self.snapshot();self.store.add_ignore(self.frame,box);self.changed()
        else:self.render()

    def delete(self):
        selected=self.listbox.curselection()
        if not selected:return
        i=selected[0];self.snapshot();n=len(self.frame['points'])
        if i<n:self.frame['points'].pop(i)
        else:self.frame['ignore_regions'].pop(i-n)
        self.frame['complete']=False;self.changed()

    def undo(self):
        if self.history:
            self.frame=self.history.pop();self.store.data['frames'][str(self.index)]=self.frame;self.changed()

    def mark_complete(self):
        self.frame['complete']=self.complete.get();self.changed()

    def save(self):self.persist_frame();self.status.set('已保存 '+str(self.store.path))

    def step(self,value):
        if abs(value)==1:self.navigate(self.index+value)
        else:
            target=self.frame['t']+value
            self.navigate(min(range(len(self.store.stamps)),key=lambda i:abs(self.store.stamps[i]['t']-target)))

    def export(self):
        try:
            self.store.save();path,count=self.store.export(self.classes)
            messagebox.showinfo('导出',f'已导出 {count} 张完整标注帧\n{path}')
        except Exception as error:messagebox.showerror('导出失败',str(error))

    def close(self):
        self.persist_frame()
        if self.prediction_poll:self.root.after_cancel(self.prediction_poll)
        self.cap.release();self.root.destroy()


def main():
    p=argparse.ArgumentParser();p.add_argument('--recording',type=Path)
    p.add_argument('--classes',type=Path,default=Path('data/kitchen/classes.json'))
    p.add_argument('--labels-dir',type=Path,help='独立标注目录，避免加载参考代标')
    p.add_argument('--box-mode',action='store_true',help='优先补齐YOLO所需实例框')
    p.add_argument('--select-mode',action='store_true',help='手动挑选录像帧加入待标队列');a=p.parse_args()
    if a.recording is None:
        paths=sorted(Path('runtime/kitchen/recordings').glob('*/summary.json'))
        if not paths:p.error('没有录像，请先录制')
        a.recording=paths[-1].parent
    if a.select_mode and a.labels_dir is None:a.labels_dir=Path('runtime/kitchen/manual-labeling')/a.recording.name
    root=tk.Tk();app=Annotator(root,a.recording,a.classes,a.labels_dir,a.box_mode,a.select_mode)
    try:root.mainloop()
    finally:app.cap.release()


if __name__=='__main__':main()
