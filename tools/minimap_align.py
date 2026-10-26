"""Native offline landmark and pixel alignment editor. No game input."""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import ttk,filedialog,messagebox

import cv2
import numpy as np

from modular_agent.realtime.minimap_alignment import AlignmentProject,matching_placements
from modular_agent.domains.hololive_dreams.patrol_vision import read_image

ROOT = Path(__file__).resolve().parents[1]


class AlignmentEditor:
    def __init__(self,root,recording,placements=None,project_file=None,*,from_zero=False):
        self.root = root;self.busy = False;self.cancel = threading.Event();self.events = queue.SimpleQueue()
        self.closing = False;self.photos = {};self.zoom = 1.;self.pans = {name:np.zeros(2) for name in ('a','b','overlay')}
        self.pending = {'a':None,'b':None};self.blink = False;self.drag = None;self.override = None
        self.stroke = None;self.polygon = None
        self.overview_drag = None;self.overview_override = None
        self.edit_mode = tk.StringVar(value='对齐/选地标');self.mask_scope = tk.StringVar(value='仅当前帧')
        self.brush_size = tk.StringVar(value='6');self.outer_size = tk.StringVar();self.center_size = tk.StringVar()
        self.all_frames = tk.BooleanVar(value=False);self.include = tk.BooleanVar(value=True)
        self.mode = tk.StringVar(value='透明叠加');self.opacity = tk.DoubleVar(value=.5)
        self.step = tk.StringVar(value='1');self.ref_var = tk.StringVar();self.cur_var = tk.StringVar()
        self.status = tk.StringVar(value='请选择固定道路/建筑角点；不使用角色、NPC、黄色视野纹作为地标。')
        root.title('小地图半自动对齐 · 离线编辑，不操作游戏');root.geometry('1380x860')
        bar = ttk.Frame(root,padding=5);bar.pack(fill='x')
        for label,command in [('选择扫描记录…',self.open_recording),('保存 Ctrl+S',self.save),('撤销 Ctrl+Z',self.undo),
                              ('从零新建',self.new_zero),('打开拼图项目…',self.open_project),
                              ('重建并导出地图',self.start_export),('取消导出',self.cancel.set)]:
            ttk.Button(bar,text=label,command=command).pack(side='left',padx=3)
        self.source_label = ttk.Label(root);self.source_label.pack(fill='x',padx=8)
        body = ttk.Panedwindow(root,orient='horizontal');body.pack(fill='both',expand=True,padx=6)
        sidebar = ttk.Frame(body);body.add(sidebar,weight=0)
        ttk.Checkbutton(sidebar,text='显示所有原始帧（含被拒绝帧）',variable=self.all_frames,command=self.refresh_list).pack(anchor='w')
        self.list_hint = ttk.Label(sidebar,text='默认仅列关键帧；双击设为参考 A');self.list_hint.pack(anchor='w')
        frame = ttk.Frame(sidebar);frame.pack(fill='both',expand=True)
        self.listbox = tk.Listbox(frame,width=29,exportselection=False)
        scroll = ttk.Scrollbar(frame,orient='vertical',command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=scroll.set);self.listbox.pack(side='left',fill='both',expand=True);scroll.pack(side='right',fill='y')
        self.listbox.bind('<<ListboxSelect>>',self.select_list);self.listbox.bind('<Double-Button-1>',lambda e:self.set_reference(self.current))
        self.notebook = ttk.Notebook(body);body.add(self.notebook,weight=1)
        align = ttk.Frame(self.notebook);overview = ttk.Frame(self.notebook)
        self.notebook.add(align,text='关键帧对齐');self.notebook.add(overview,text='地图总览（导出后刷新）')
        self.notebook.bind('<<NotebookTabChanged>>',lambda e:self.render_overview())
        toolbar = ttk.Frame(align);toolbar.pack(fill='x',pady=4)
        ttk.Label(toolbar,text='参考 A 帧号').pack(side='left')
        ttk.Entry(toolbar,textvariable=self.ref_var,width=7).pack(side='left')
        ttk.Button(toolbar,text='设定 A',command=self.apply_reference_entry).pack(side='left')
        ttk.Label(toolbar,text='待调 B 帧号').pack(side='left',padx=(10,0))
        entry = ttk.Entry(toolbar,textvariable=self.cur_var,width=7);entry.pack(side='left');entry.bind('<Return>',lambda e:self.apply_current_entry())
        ttk.Button(toolbar,text='跳转 B',command=self.apply_current_entry).pack(side='left')
        ttk.Button(toolbar,text='推荐重叠 A',command=lambda:self.set_reference(self.project.suggest_reference(self.current))).pack(side='left',padx=4)
        ttk.Button(toolbar,text='交换 A/B',command=self.swap).pack(side='left')
        images = ttk.Frame(align);images.pack(fill='both',expand=True)
        self.canvases = {}
        for name,title in [('a','A：参考帧，左键选地标'),('b','B：待调帧，左键选同一地标'),('overlay','叠加：左键拖动 B；滚轮缩放，右键平移')]:
            pane = ttk.Frame(images);pane.pack(side='left',fill='both',expand=True,padx=2)
            ttk.Label(pane,text=title).pack()
            canvas = tk.Canvas(pane,width=320,height=400,bg='#20242a',highlightthickness=1)
            canvas.pack(fill='both',expand=True);self.canvases[name] = canvas
            canvas.bind('<Configure>',lambda e:self.render())
            canvas.bind('<MouseWheel>',self.wheel)
            canvas.bind('<Button-3>',lambda e,key=name:self.start_pan(e,key))
            canvas.bind('<B3-Motion>',lambda e,key=name:self.pan(e,key))
            canvas.bind('<Button-1>',lambda e,key=name:self.click(e,key))
            canvas.bind('<B1-Motion>',lambda e,key=name:self.left_motion(e,key))
            canvas.bind('<ButtonRelease-1>',self.end_drag)
            canvas.bind('<Double-Button-1>',lambda e:self.finish_polygon() if self.edit_mode.get().startswith('多边形') else None)
        maskbar = ttk.Frame(align,padding=3);maskbar.pack(fill='x')
        ttk.Label(maskbar,text='掩膜工具（在 A/B 图上画）').pack(side='left')
        modes = ttk.Combobox(maskbar,textvariable=self.edit_mode,values=('对齐/选地标','画笔擦除','画笔恢复','多边形擦除','多边形恢复'),state='readonly',width=14)
        modes.pack(side='left');modes.bind('<<ComboboxSelected>>',lambda e:self.cancel_drawing())
        ttk.Combobox(maskbar,textvariable=self.mask_scope,values=('仅当前帧','全部帧通用'),state='readonly',width=12).pack(side='left',padx=3)
        ttk.Label(maskbar,text='笔刷半径(px)').pack(side='left')
        ttk.Spinbox(maskbar,textvariable=self.brush_size,from_=1,to=50,increment=1,width=5).pack(side='left')
        ttk.Button(maskbar,text='完成多边形 Enter',command=self.finish_polygon).pack(side='left',padx=3)
        ttk.Button(maskbar,text='取消绘制 Esc',command=self.cancel_drawing).pack(side='left')
        circlebar = ttk.Frame(align,padding=3);circlebar.pack(fill='x')
        ttk.Label(circlebar,text='外圆半径(px)').pack(side='left')
        ttk.Spinbox(circlebar,textvariable=self.outer_size,from_=1,to=82,increment=1,width=6).pack(side='left')
        ttk.Label(circlebar,text='中心遮挡半径(px)').pack(side='left',padx=(8,0))
        ttk.Spinbox(circlebar,textvariable=self.center_size,from_=0,to=80,increment=1,width=6).pack(side='left')
        ttk.Button(circlebar,text='应用圆范围（全帧）',command=self.apply_circle).pack(side='left',padx=3)
        ttk.Button(circlebar,text='外圆扩到90%',command=lambda:self.guarded(lambda:self.project.set_circle(self.project.settings.tile_size*.45,float(self.center_size.get())))).pack(side='left')
        ttk.Button(circlebar,text='清空此范围绘制',command=self.reset_mask).pack(side='left')
        ttk.Button(circlebar,text='复制 B 掩膜到 A',command=lambda:self.guarded(lambda:self.project.copy_frame_mask(self.current,self.reference))).pack(side='left',padx=3)
        ttk.Button(circlebar,text='导入黑白PNG…',command=self.import_mask).pack(side='left')
        ttk.Button(circlebar,text='导出 B 掩膜…',command=self.export_mask).pack(side='left')
        tools = ttk.Frame(align,padding=4);tools.pack(fill='x')
        self.pair_button = ttk.Button(tools,text='加入这组地标对应',command=self.add_pair);self.pair_button.pack(side='left')
        ttk.Button(tools,text='清空选点',command=self.clear_points).pack(side='left',padx=3)
        self.pin_button = ttk.Button(tools,text='固定参考 A 位置',command=self.pin_reference);self.pin_button.pack(side='left')
        ttk.Checkbutton(tools,text='B 参与合成',variable=self.include,command=self.toggle_include).pack(side='left',padx=8)
        ttk.Button(tools,text='确认加入 B',command=self.confirm_current).pack(side='left',padx=3)
        ttk.Label(tools,text='微调步长').pack(side='left')
        ttk.Combobox(tools,textvariable=self.step,values=('0.25','1','5'),state='readonly',width=5).pack(side='left')
        for label,dx,dy in [('←',-1,0),('↑',0,-1),('↓',0,1),('→',1,0)]:
            ttk.Button(tools,text=label,width=3,command=lambda x=dx,y=dy:self.nudge(x,y)).pack(side='left')
        ttk.Button(tools,text='适应窗口',command=self.fit).pack(side='left',padx=3)
        controls = ttk.Frame(align);controls.pack(fill='x')
        ttk.Label(controls,text='对比模式').pack(side='left')
        combo = ttk.Combobox(controls,textvariable=self.mode,values=('透明叠加','闪烁对比','差分增强'),state='readonly',width=12)
        combo.pack(side='left');combo.bind('<<ComboboxSelected>>',lambda e:self.render())
        ttk.Scale(controls,variable=self.opacity,from_=0,to=1,command=lambda value:self.render()).pack(side='left',fill='x',expand=True)
        self.metrics = ttk.Label(align);self.metrics.pack(fill='x',padx=5,pady=4)
        constraints = ttk.Frame(align);constraints.pack(fill='x')
        self.constraint_list = tk.Listbox(constraints,height=4,exportselection=False)
        self.constraint_list.pack(side='left',fill='x',expand=True)
        ttk.Button(constraints,text='删除选中约束',command=self.remove_constraint).pack(side='right')
        self.overview_canvas = tk.Canvas(overview,bg='#20242a');self.overview_canvas.pack(fill='both',expand=True)
        self.overview_canvas.bind('<Configure>',lambda e:self.render_overview())
        self.overview_canvas.bind('<Button-1>',self.overview_press)
        self.overview_canvas.bind('<B1-Motion>',self.overview_motion)
        self.overview_canvas.bind('<ButtonRelease-1>',self.overview_release)
        layerbar = ttk.Frame(overview);layerbar.pack(fill='x')
        ttk.Button(layerbar,text='选中的 B 置顶',command=lambda:self.guarded(lambda:self.project.layer_order(self.current,front=True))).pack(side='left')
        ttk.Button(layerbar,text='选中的 B 置底',command=lambda:self.guarded(lambda:self.project.layer_order(self.current,front=False))).pack(side='left')
        ttk.Label(layerbar,text='手工模式：左键选中并拖动任意已加入的图片；方向键微调。').pack(side='left',padx=8)
        ttk.Label(root,textvariable=self.status,wraplength=1330).pack(fill='x',padx=8,pady=6)
        root.bind('<Control-s>',lambda e:self.save());root.bind('<Control-z>',lambda e:self.undo())
        root.bind('<Escape>',lambda e:self.cancel_drawing())
        root.bind('<Return>',lambda e:self.finish_polygon() if self.polygon else None)
        for key,dx,dy in [('Left',-1,0),('Right',1,0),('Up',0,-1),('Down',0,1)]:
            root.bind('<'+key+'>',lambda e,x=dx,y=dy:self.arrow(e,x,y))
        root.protocol('WM_DELETE_WINDOW',self.close)
        self.load(recording,placements,project_file,from_zero=from_zero)
        root.after(400,self.flicker);root.after(100,self.poll)

    def load(self,recording,placements=None,project_file=None,*,from_zero=False):
        placements = Path(placements) if placements else Path(recording)/'frames.jsonl' if from_zero else matching_placements(recording,ROOT/'runtime/patrol')
        if project_file is None:
            import hashlib
            key = hashlib.sha256(placements.read_bytes()).hexdigest()[:8]
            name = Path(recording).name+('-manual-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f') if from_zero else '-'+key)
            project_file = ROOT/'runtime/patrol/alignments'/name/'alignment-project.json'
        self.project = AlignmentProject(recording,placements,project_file,from_zero=from_zero)
        self.all_frames.set(self.project.manual)
        self.list_hint.configure(text='素材库；双击设 A，确认加入才会合成' if self.project.manual else '默认仅列关键帧；双击设为参考 A')
        self.notebook.tab(0,text='素材掩膜 / 可选对齐' if self.project.manual else '关键帧对齐')
        self.notebook.tab(1,text='自由拼图画布' if self.project.manual else '地图总览（导出后刷新）')
        self.pair_button.configure(text='用地标对齐 B' if self.project.manual else '加入这组地标对应')
        self.pin_button.configure(state='disabled' if self.project.manual else 'normal')
        ids = self.project.ids if self.project.manual else self.project.keyframes()
        if not ids:
            raise ValueError('该记录没有可用定位帧')
        view = self.project.data.get('view',{})
        self.current = view.get('current',ids[0] if self.project.manual else ids[min(1,len(ids)-1)])
        self.reference = view.get('reference',ids[0])
        if self.current not in self.project.lookup:self.current = ids[0]
        if self.reference not in self.project.lookup:self.reference = ids[0]
        self.base_map_path = placements.parent/'map.png'
        self.overview_image = read_image(self.base_map_path) if not self.project.manual and self.base_map_path.exists() else None
        self.overview_dirty = self.project.manual
        self.pending = {'a':None,'b':None};self.stroke = None;self.polygon = None;self.drag = None;self.override = None
        self.overview_drag = None;self.overview_override = None
        if from_zero:
            self.zoom = 1.;self.pans = {name:np.zeros(2) for name in self.pans}
        self.refresh_list();self.refresh_constraints();self.sync()
        workflow = '自由拼图：每张图片独立摆放，确认后加入画布' if self.project.manual else '自动底图校正'
        self.source_label.configure(text=f'{workflow} | 记录：{self.project.recording.name} | 项目：{self.project.project_file}')
        self.render_overview()
        self.root.title('小地图自由拼图 · 拖动图片摆放，A/B对齐可选' if self.project.manual else '小地图半自动对齐 · 离线编辑，不操作游戏')
        if self.project.manual:self.project.save();self.status.set('挑截图 → 画掩膜 → 确认加入 B → 在自由画布拖动。A/B地标只是可选辅助。')

    def guarded(self,operation):
        if self.busy:return
        before = json.loads(json.dumps(self.project.data))
        try:
            operation();self.refresh_list();self.refresh_constraints();self.sync()
        except Exception as error:
            self.project.data = before;self.project.solve()
            messagebox.showerror('未应用本次修改',str(error),parent=self.root)

    def open_recording(self):
        if self.busy:return
        folder = filedialog.askdirectory(initialdir=ROOT/'runtime/patrol/maps',title='选择包含 tiles 和 frames.jsonl 的原始扫描目录')
        if folder:
            self.save()
            try:self.load(Path(folder))
            except Exception as error:messagebox.showerror('无法打开',str(error),parent=self.root)

    def new_zero(self):
        if self.busy:return
        self.save()
        if self.polygon or self.stroke:return
        try:self.load(self.project.recording,from_zero=True)
        except Exception as error:messagebox.showerror('无法新建',str(error),parent=self.root)

    def open_project(self):
        if self.busy:return
        self.save()
        if self.polygon or self.stroke:return
        path = filedialog.askopenfilename(initialdir=ROOT/'runtime/patrol/alignments',title='打开保存的 alignment-project.json',filetypes=[('拼图项目','*.json')])
        if path:
            try:
                data = json.loads(Path(path).read_text(encoding='utf-8'))
                self.load(Path(data['recording']),Path(data['placements']),Path(path))
            except Exception as error:messagebox.showerror('无法打开项目',str(error),parent=self.root)

    def refresh_list(self):
        if not hasattr(self,'project') or self.busy:return
        self.candidates = self.project.ids if self.all_frames.get() else self.project.keyframes()
        selected = set(self.project.selected_ids());self.listbox.delete(0,'end')
        for fid in self.candidates:
            state = ('已加入' if fid in selected else '未加入') if self.project.manual else ('参与' if fid in selected else '排除')
            self.listbox.insert('end',f'{fid:04d}  {self.project.time(fid):6.1f}s  '+state)
            if fid not in selected:self.listbox.itemconfigure('end',fg='#999999')
        if self.current in self.candidates:
            index = self.candidates.index(self.current);self.listbox.selection_set(index);self.listbox.see(index)

    def sync(self):
        self.ref_var.set(str(self.reference));self.cur_var.set(str(self.current))
        self.include.set(self.current in set(self.project.selected_ids()))
        n = self.project.settings.tile_size
        self.outer_size.set(f'{self.project.data["masks"]["outer_radius"]*n/2:.2f}')
        self.center_size.set(f'{self.project.data["masks"]["center_radius"]*n/2:.2f}')
        self.project.data['view'] = dict(current=self.current,reference=self.reference)
        if self.project.manual:self.overview_dirty = True
        self.render()
        if self.project.manual and self.notebook.index(self.notebook.select())==1:self.render_overview()

    def confirm_current(self):
        if self.busy:return
        self.save()
        if self.polygon or self.stroke:return
        empty = not self.project.selected_ids()
        self.guarded(lambda:self.project.set_included(self.current,True))
        if empty:self.set_reference(self.current)
        if self.project.manual:self.notebook.select(1);self.render_overview()
        self.status.set(f'帧 {self.current} 已确认加入。当前共 {len(self.project.selected_ids())} 帧参与；未加入的截图不会混入。')

    def select_list(self,event=None):
        if self.busy:return
        if self.polygon or self.stroke:
            self.status.set('先完成或取消当前绘制，再切换帧。');return
        selection = self.listbox.curselection()
        if selection:
            self.current = self.candidates[selection[0]];self.pending['b'] = None;self.sync()
            if self.project.manual:self.notebook.select(1 if self.current in self.project.selected_ids() else 0)

    def set_reference(self,fid):
        if self.busy:return
        if self.polygon or self.stroke:
            self.status.set('先完成或取消当前绘制，再切换参考帧。');return
        if fid not in self.project.lookup:raise ValueError('未知帧号')
        self.reference = fid;self.pending['a'] = None;self.sync()

    def apply_reference_entry(self):
        self.guarded(lambda:self.set_reference(int(self.ref_var.get())))

    def apply_current_entry(self):
        if self.polygon or self.stroke:
            self.status.set('先完成或取消当前绘制，再切换帧。');return
        def action():
            fid = int(self.cur_var.get())
            if fid not in self.project.lookup:raise ValueError('未知帧号')
            self.current = fid;self.pending['b'] = None
        self.guarded(action)

    def swap(self):
        if self.busy:return
        if self.polygon or self.stroke:
            self.status.set('先完成或取消当前绘制，再交换帧。');return
        self.reference,self.current = self.current,self.reference;self.pending = {'a':None,'b':None};self.sync()

    def clear_points(self):
        self.pending = {'a':None,'b':None};self.render()

    def fit(self):
        self.zoom = 1.;self.pans = {name:np.zeros(2) for name in self.pans};self.render()

    def wheel(self,event):
        if self.busy:return
        self.zoom = float(np.clip(self.zoom*(1.25 if event.delta>0 else .8),.4,8));self.render()

    def start_pan(self,event,name):
        self.pan_start = (name,np.array((event.x,event.y)),self.pans[name].copy())

    def pan(self,event,name):
        if self.busy or not hasattr(self,'pan_start'):return
        key,start,position = self.pan_start
        if key==name:self.pans[name] = position+np.array((event.x,event.y))-start;self.render()

    def click(self,event,name):
        if self.busy:return
        self.canvases[name].focus_set()
        if name=='overlay':
            if self.edit_mode.get()!='对齐/选地标':
                self.status.set('掩膜请在左侧 A 或 B 原图上绘制；叠加图显示实际排除效果。');return
            self.drag = (np.array((event.x,event.y)),self.project.pose(self.current),self.overlay_scale,self.overlay_center.copy());return
        transform = self.raw_transforms[name];point = (np.array((event.x,event.y))-transform[1])/transform[0]
        n = self.project.settings.tile_size
        if np.all(point>=0) and np.all(point<n):
            fid = self.reference if name=='a' else self.current
            mode = self.edit_mode.get();scope = 'global' if self.mask_scope.get()=='全部帧通用' else 'frame'
            if mode.startswith('画笔'):
                try:radius = float(self.brush_size.get())
                except ValueError:self.status.set('请输入有效笔刷半径');return
                if not 1<=radius<=n/2:self.status.set('笔刷半径超出范围');return
                self.stroke = dict(fid=fid,name=name,scope=scope,shape=dict(kind='brush',op='erase' if mode.endswith('擦除') else 'restore',radius=radius,points=[point.tolist()]))
            elif mode.startswith('多边形'):
                if self.polygon and (self.polygon['fid']!=fid or self.polygon['name']!=name):
                    self.status.set('请先完成或取消正在画的多边形。');return
                if not self.polygon:
                    self.polygon = dict(fid=fid,name=name,scope=scope,shape=dict(kind='polygon',op='erase' if mode.endswith('擦除') else 'restore',points=[]))
                self.polygon['shape']['points'].append(point.tolist())
                self.status.set('逐点圈住锥形黄光，Enter / 双击 / 完成按钮闭合；Esc取消。')
            else:self.pending[name] = point.tolist()
            self.render()

    def left_motion(self,event,name):
        if self.busy:return
        if self.stroke:
            if name!=self.stroke['name']:return
            scale,offset = self.raw_transforms[name];n = self.project.settings.tile_size
            point = np.clip((np.array((event.x,event.y))-offset)/scale,0,n-1)
            points = self.stroke['shape']['points']
            if np.linalg.norm(point-np.array(points[-1]))>=.35:points.append(point.tolist())
            self.render()
        elif self.drag is not None:self.drag_overlay(event)

    def drag_overlay(self,event):
        if self.busy or self.drag is None:return
        start,position,scale,center = self.drag
        self.override = position+(np.array((event.x,event.y))-start)/scale
        self.render()

    def end_drag(self,event):
        if self.stroke:
            drawing = self.stroke;self.stroke = None
            self.guarded(lambda:self.project.add_mask_shape(drawing['fid'],drawing['shape'],scope=drawing['scope']))
            return
        if self.busy or self.drag is None:return
        position = self.override;self.drag = None;self.override = None
        if position is not None:self.guarded(lambda:self.project.anchor(self.current,position))

    def finish_polygon(self):
        if self.busy or self.polygon is None:return
        if len(self.polygon['shape']['points'])<3:
            self.status.set('多边形至少点三个位置，再完成。');return
        drawing = self.polygon;self.polygon = None
        self.guarded(lambda:self.project.add_mask_shape(drawing['fid'],drawing['shape'],scope=drawing['scope']))

    def cancel_drawing(self):
        self.stroke = None;self.polygon = None;self.drag = None;self.override = None;self.render()

    def apply_circle(self):
        self.guarded(lambda:self.project.set_circle(float(self.outer_size.get()),float(self.center_size.get())))

    def reset_mask(self):
        scope = 'global' if self.mask_scope.get()=='全部帧通用' else 'frame'
        self.cancel_drawing();self.guarded(lambda:self.project.clear_mask(self.current,scope=scope))

    def import_mask(self):
        if self.busy:return
        path = filedialog.askopenfilename(title='白色保留、黑色排除；必须与小地图方块同尺寸',filetypes=[('PNG掩膜','*.png')])
        if path:
            scope = 'global' if self.mask_scope.get()=='全部帧通用' else 'frame'
            self.guarded(lambda:self.project.import_mask(self.current,path,scope=scope))

    def export_mask(self):
        if self.busy:return
        path = filedialog.asksaveasfilename(title='导出当前 B 的有效掩膜：白色保留、黑色排除',defaultextension='.png',filetypes=[('PNG掩膜','*.png')])
        if path:
            from modular_agent.domains.hololive_dreams.patrol_vision import write_image
            try:write_image(path,self.project.mask(self.current));self.status.set(f'已导出掩膜：{path}')
            except Exception as error:messagebox.showerror('导出失败',str(error),parent=self.root)

    def visible_mask(self,fid):
        drawing = self.stroke or self.polygon
        if drawing and (drawing['scope']=='global' or drawing['fid']==fid):
            shape = drawing['shape']
            if shape['kind']=='polygon' and len(shape['points'])<3:return self.project.mask(fid)
            return self.project.mask(fid,extra=shape,scope=drawing['scope'])
        return self.project.mask(fid)

    def arrow(self,event,dx,dy):
        if isinstance(self.root.focus_get(),tk.Canvas):
            self.nudge(dx,dy);return 'break'

    def nudge(self,dx,dy):
        self.guarded(lambda:self.project.anchor(self.current,self.project.pose(self.current)+np.array((dx,dy))*float(self.step.get())))

    def pin_reference(self):
        self.guarded(lambda:self.project.anchor(self.reference,self.project.pose(self.reference)))

    def add_pair(self):
        if self.pending['a'] is None or self.pending['b'] is None:
            self.status.set('先在 A、B 两张图中分别左键点选同一个固定地标。');return
        self.guarded(lambda:self.project.add_pair(self.reference,self.pending['a'],self.current,self.pending['b']))
        self.clear_points()

    def toggle_include(self):
        if self.polygon or self.stroke:
            self.include.set(self.current in self.project.selected_ids());self.status.set('先完成或取消绘制，再确认参与拼图。');return
        empty = not self.project.selected_ids();enabled = self.include.get()
        self.guarded(lambda:self.project.set_included(self.current,enabled));self.refresh_list()
        if self.project.manual and empty and enabled and self.current in self.project.selected_ids():self.set_reference(self.current)

    def undo(self):
        if self.polygon:
            self.polygon['shape']['points'].pop()
            if not self.polygon['shape']['points']:self.polygon = None
            self.render();return
        if self.stroke:self.cancel_drawing();return
        self.guarded(self.project.undo);self.refresh_list()

    def refresh_constraints(self):
        self.constraint_items = [];self.constraint_list.delete(0,'end')
        for fid,position in self.project.data['anchors'].items():
            self.constraint_items.append(('anchor',fid))
            self.constraint_list.insert('end',f'固定帧 {fid} → ({position[0]:.2f}, {position[1]:.2f})')
        for i,pair in enumerate(self.project.data['pairs']):
            self.constraint_items.append(('pair',i))
            self.constraint_list.insert('end',f'地标 {i+1}：帧 {pair["a"]} ↔ {pair["b"]}，残差 {self.project.residuals[i]:.3f}px')

    def remove_constraint(self):
        selection = self.constraint_list.curselection()
        if selection:
            kind,key = self.constraint_items[selection[0]]
            self.guarded(lambda:self.project.remove_constraint(kind,key))

    def photo(self,name,image):
        self.photos[name] = tk.PhotoImage(data=cv2.imencode('.png',image)[1].tobytes())
        canvas = self.canvases.get(name,self.overview_canvas);canvas.delete('all')
        canvas.create_image(0,0,image=self.photos[name],anchor='nw')

    def render(self):
        if not hasattr(self,'project') or self.busy:return
        n = self.project.settings.tile_size;self.raw_transforms = {}
        images = {'a':self.project.tile(self.reference),'b':self.project.tile(self.current)}
        masks = {'a':self.visible_mask(self.reference),'b':self.visible_mask(self.current)}
        for name,image in images.items():
            canvas = self.canvases[name];w,h = max(80,canvas.winfo_width()),max(80,canvas.winfo_height())
            scale = min((w-12)/n,(h-12)/n)*self.zoom
            offset = np.array(((w-n*scale)/2,(h-n*scale)/2))+self.pans[name]
            self.raw_transforms[name] = (scale,offset)
            image = image.copy();mask = masks[name]
            image[mask==0] = np.rint(image[mask==0]*.45+np.array((100,0,120))*.55).astype(np.uint8)
            transform = np.float32([[scale,0,offset[0]],[0,scale,offset[1]]])
            display = cv2.warpAffine(image,transform,(w,h),flags=cv2.INTER_NEAREST,borderValue=(32,36,42))
            if self.pending[name] is not None:
                xy = np.rint(np.array(self.pending[name])*scale+offset).astype(int)
                cv2.drawMarker(display,tuple(xy),(0,0,255),cv2.MARKER_CROSS,19,2)
            if self.polygon and self.polygon['name']==name:
                pts = np.rint(np.array(self.polygon['shape']['points'])*scale+offset).astype(np.int32)
                if len(pts)>1:cv2.polylines(display,[pts],False,(0,255,255),2)
                for point in pts:cv2.circle(display,tuple(point),3,(0,255,255),-1)
            self.photo(name,display)
        canvas = self.canvases['overlay'];w,h = max(80,canvas.winfo_width()),max(80,canvas.winfo_height())
        pa = self.project.pose(self.reference);pb = self.override if self.override is not None else self.project.pose(self.current)
        extent = max(n+abs(pa[0]-pb[0]),n+abs(pa[1]-pb[1]))+12
        scale = min(w,h)/extent*self.zoom;self.overlay_scale = scale
        center = (pa+pb)/2
        if self.drag is not None:scale,center = self.drag[2],self.drag[3]
        self.overlay_scale = scale;self.overlay_center = center.copy();warped = [];valids = []
        for name,position in [('a',pa),('b',pb)]:
            offset = (position-center-n/2)*scale+np.array((w/2,h/2))+self.pans['overlay']
            matrix = np.float32([[scale,0,offset[0]],[0,scale,offset[1]]])
            warped.append(cv2.warpAffine(images[name],matrix,(w,h),flags=cv2.INTER_NEAREST))
            valids.append(cv2.warpAffine(masks[name],matrix,(w,h),flags=cv2.INTER_NEAREST)>0)
        a,b = warped;va,vb = valids;both = va&vb
        display = np.full((h,w,3),(32,36,42),np.uint8);display[va] = a[va];display[vb&~va] = b[vb&~va]
        if self.mode.get()=='差分增强':
            display[both] = np.clip(np.abs(a[both].astype(float)-b[both])*3,0,255).astype(np.uint8)
        elif self.mode.get()=='闪烁对比':
            display[both] = b[both] if self.blink else a[both]
        else:
            alpha = self.opacity.get();display[both] = np.rint(a[both]*(1-alpha)+b[both]*alpha).astype(np.uint8)
        self.photo('overlay',display)
        delta = self.project.pose(self.current)-self.project.base[self.project.lookup[self.current]]
        residual = max(self.project.residuals,default=0)
        masked = self.project.masked_landmarks();pixels = np.count_nonzero(masks['b'])
        self.metrics.configure(text=f'B 修正：({delta[0]:+.3f}, {delta[1]:+.3f}) px | 残差 {residual:.3f}px | 有效像素 {pixels} | 被掩膜挡住的旧地标 {masked} | 参与帧 {len(self.project.selected_ids())}',foreground='#b34a00' if residual>1.5 or masked else '#333333')

    def render_overview(self):
        if not hasattr(self,'overview_image'):return
        if self.project.manual and (self.overview_dirty or self.overview_override is not None) and not self.busy:
            try:
                override = {self.current:self.overview_override} if self.overview_override is not None else None
                self.overview_image = self.project.preview(overrides=override);self.overview_dirty = False
                self.overview_origin = np.array(self.project.preview_origin,dtype=float)
            except Exception as error:self.status.set(str(error));return
        if self.overview_image is None:
            canvas = self.overview_canvas;canvas.delete('all')
            canvas.create_text(max(100,canvas.winfo_width())/2,max(100,canvas.winfo_height())/2,
                               text='空白拼图\n挑截图 → 画掩膜 → 确认加入 B → 在这里随意拖动摆放',fill='white',justify='center')
            return
        image = self.overview_image;canvas = self.overview_canvas
        w,h = max(100,canvas.winfo_width()),max(100,canvas.winfo_height());scale = min(w/image.shape[1],h/image.shape[0])
        origin = getattr(self,'overview_origin',np.zeros(2))
        if self.overview_drag is not None:
            scale = self.overview_drag[3];offset = (origin-self.overview_drag[4])*scale
        else:offset = np.zeros(2)
        self.overview_scale = scale
        matrix = np.float32([[scale,0,offset[0]],[0,scale,offset[1]]])
        display = cv2.warpAffine(image,matrix,(w,h),flags=cv2.INTER_NEAREST,borderValue=(32,36,42))
        self.photo('overview',display)

    def overview_press(self,event):
        if self.busy or not self.project.manual or self.overview_image is None:return
        self.overview_canvas.focus_set()
        world = self.overview_origin+np.array((event.x,event.y))/self.overview_scale
        n = self.project.settings.tile_size
        for fid in reversed(self.project.selected_ids()):
            point = world-self.project.pose(fid)+n/2
            if np.all(point>=0) and np.all(point<n):
                x,y = np.floor(point).astype(int)
                if self.project.mask(fid)[y,x]:
                    self.current = fid;self.sync()
                    self.overview_drag = (fid,np.array((event.x,event.y)),self.project.pose(fid),self.overview_scale,self.overview_origin.copy())
                    self.status.set(f'已选中帧 {fid}，拖动仅改变这张图片的位置。');return

    def overview_motion(self,event):
        if self.busy or self.overview_drag is None:return
        fid,start,position,scale,origin = self.overview_drag
        self.overview_override = position+(np.array((event.x,event.y))-start)/scale
        self.render_overview()

    def overview_release(self,event):
        if self.overview_drag is None:return
        fid = self.overview_drag[0];position = self.overview_override
        self.overview_drag = None;self.overview_override = None
        if position is not None:self.guarded(lambda:self.project.anchor(fid,position))

    def flicker(self):
        self.blink = not self.blink
        if not self.busy and self.mode.get()=='闪烁对比':self.render()
        if not self.closing:self.root.after(400,self.flicker)

    def save(self):
        if not hasattr(self,'project') or self.busy:return
        if self.stroke:self.end_drag(None)
        if self.polygon:
            if len(self.polygon['shape']['points'])<3:
                self.status.set('当前多边形不足三个点，完成或取消后再保存/导出。');return
            self.finish_polygon()
        self.project.data['view'] = dict(current=self.current,reference=self.reference);self.project.save()
        self.status.set(f'已保存修正项目：{self.project.project_file}；原始截图和原地图未修改。')

    def start_export(self):
        if self.busy:return
        self.save()
        if self.polygon or self.stroke:return
        if not self.project.selected_ids():
            self.status.set('拼图仍为空，请先选帧、画掩膜，再点“确认加入 B”。');return
        self.busy = True;self.cancel.clear()
        output = self.project.project_file.parent/'exports'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        output.parent.mkdir(parents=True,exist_ok=True)
        self.status.set('正在重建修正地图…可取消，原始记录始终保留。')
        def worker():
            try:
                self.project.export(output,cancelled=self.cancel.is_set,progress=lambda a,b:self.events.put(('progress',f'重建 {a}/{b}')))
                self.events.put(('done',output))
            except Exception as error:self.events.put(('error',str(error)))
        threading.Thread(target=worker,daemon=True).start()

    def poll(self):
        while not self.events.empty():
            kind,value = self.events.get()
            if kind=='progress':self.status.set(value)
            else:
                self.busy = False
                self.sync()
                if kind=='done':
                    self.overview_image = read_image(value/'map.png');self.overview_dirty = False;self.render_overview();self.notebook.select(1)
                    self.status.set(f'已导出：{value}；保留原始记录。地标校正不等于全图已经准确，请用闪烁/差分检查。')
                else:self.status.set(value)
                if self.closing:self.root.destroy();return
        if not self.closing or self.busy:self.root.after(100,self.poll)

    def close(self):
        self.closing = True
        if self.busy:self.cancel.set();self.status.set('正在取消导出并保存…')
        else:self.save();self.root.destroy()


def main(argv=None):
    p = argparse.ArgumentParser(description='Offline minimap alignment editor; never sends game input')
    p.add_argument('recording',type=Path,nargs='?')
    p.add_argument('--placements',type=Path)
    p.add_argument('--project',type=Path)
    p.add_argument('--from-zero',action='store_true',help='new empty manual project: no frames or automatic placements imported')
    p.add_argument('--smoke',action='store_true',help='create/update/destroy UI for diagnostics')
    args = p.parse_args(argv);cv2.setNumThreads(1)
    recording = args.recording
    if args.project and args.project.exists():
        saved = json.loads(args.project.read_text(encoding='utf-8'))
        if recording is None:recording = Path(saved['recording'])
        if args.placements is None:args.placements = Path(saved['placements'])
    if recording is None:
        candidates = [v for v in (ROOT/'runtime/patrol/maps').glob('*') if (v/'frames.jsonl').exists() and (v/'tiles').is_dir()]
        if not candidates:p.error('no recorded minimaps; specify a recording directory')
        recording = max(candidates,key=lambda v:v.stat().st_mtime)
    root = tk.Tk()
    try:
        app = AlignmentEditor(root,recording,args.placements,args.project,from_zero=args.from_zero)
        if args.smoke:
            root.update();app.render();app.render_overview()
            print(f'UI smoke OK: {len(app.project.ids)} frames, {len(app.candidates)} keyframes',flush=True)
            root.destroy();return 0
        root.mainloop()
    except Exception:
        try:root.destroy()
        except tk.TclError:pass
        raise
    return 0


if __name__=='__main__':
    raise SystemExit(main())
