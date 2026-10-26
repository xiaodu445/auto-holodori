"""Offline treasure/route and terrain annotation UI; no game capture or input."""
from copy import deepcopy
from datetime import datetime
import math
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox,filedialog,simpledialog
import uuid

import cv2
import numpy as np
from PIL import Image,ImageTk
from modular_agent.domains.hololive_dreams.navigation_annotations import NavigationProject,digest
from modular_agent.realtime.patrol import ROOT,latest_repaired_config


LABELS = dict(treasure='宝藏',waypoint='拐点',walkable='可走区',blocked='禁行区')


def default_project(config=None):
    config = Path(config or latest_repaired_config()).resolve()
    from modular_agent.realtime.patrol import read_json
    signature = digest(config.parent/read_json(config)['reference'])
    root = ROOT/'runtime/patrol/navigation'
    for path in sorted(root.glob('*/project.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        try:
            if read_json(path)['map']['sha256']==signature:return NavigationProject(path)
        except (OSError,ValueError,KeyError):continue
    folder = root/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
    return NavigationProject.create(config,folder)


class NavigationEditor:
    def __init__(self,project,*,visible=True):
        self.project = project;self.root = tk.Tk()
        if not visible:self.root.withdraw()
        self.root.title('地图导航标注 · 宝藏点 / 巡逻路线')
        self.root.geometry(f'{min(1220,int(self.root.winfo_screenwidth()*.92))}x{min(930,int(self.root.winfo_screenheight()*.88))}')
        self.root.columnconfigure(0,weight=1);self.root.rowconfigure(1,weight=1)
        self.zoom = 1.;self.selected = None;self.draft = [];self.drag_before = None
        self.plan = None;self.cell = tk.IntVar(value=4);self.clearance = tk.IntVar(value=2)
        self.allow_jumps = tk.BooleanVar(value=False);self.jump_verified = tk.BooleanVar(value=False)
        self.estimator=tk.StringVar(value='小地图（同时记录预测误差）')
        self.save_job = None;self.closed = False;self.refreshing = False
        self.mode = tk.StringVar(value='treasure');self.status = tk.StringVar()
        self.name = tk.StringVar();self.loop = tk.BooleanVar();self.refresh_seconds = tk.StringVar()
        toolbar = ttk.Frame(self.root,padding=5);toolbar.grid(row=0,column=0,columnspan=2,sticky='ew')
        for text,command in [('打开项目',self.open_project),('新建项目',self.new_project),('保存 Ctrl+S',self.save),
            ('导出路线/标注',self.export),('撤销 Ctrl+Z',self.undo),('－',lambda:self.set_zoom(self.zoom/1.25)),
            ('100%',lambda:self.set_zoom(1.)),('＋',lambda:self.set_zoom(self.zoom*1.25))]:
            ttk.Button(toolbar,text=text,command=command).pack(side='left',padx=2)
        viewport = ttk.Frame(self.root);viewport.grid(row=1,column=0,sticky='nsew')
        viewport.columnconfigure(0,weight=1);viewport.rowconfigure(0,weight=1)
        self.canvas = tk.Canvas(viewport,bg='#20242a',highlightthickness=0)
        xs = ttk.Scrollbar(viewport,orient='horizontal',command=self.canvas.xview)
        ys = ttk.Scrollbar(viewport,orient='vertical',command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xs.set,yscrollcommand=ys.set)
        self.canvas.grid(row=0,column=0,sticky='nsew');xs.grid(row=1,column=0,sticky='ew');ys.grid(row=0,column=1,sticky='ns')
        side = ttk.Frame(self.root,padding=8,width=365);side.grid(row=1,column=1,sticky='ns')
        tools = ttk.LabelFrame(side,text='地图操作',padding=5);tools.pack(fill='x')
        for i,(value,text) in enumerate([('treasure','宝藏点'),('route','路线拐点/选点'),('select','选择/拖动点'),
            ('walkable','可走区多边形'),('blocked','墙体/禁行区'),('jump','定向跳跃')]):
            ttk.Radiobutton(tools,text=text,value=value,variable=self.mode,command=self.cancel_draft).grid(row=i//2,column=i%2,sticky='w',padx=3)
        ttk.Button(tools,text='完成多边形 Enter',command=self.finish_polygon).grid(row=3,column=0)
        ttk.Button(tools,text='取消草稿 Esc',command=self.cancel_draft).grid(row=3,column=1)
        self.tabs = ttk.Notebook(side);self.tabs.pack(fill='both',expand=True,pady=8)
        objects = ttk.Frame(self.tabs,padding=5);route_tab = ttk.Frame(self.tabs)
        route_canvas = tk.Canvas(route_tab,width=340,height=480,highlightthickness=0)
        route_scroll = ttk.Scrollbar(route_tab,orient='vertical',command=route_canvas.yview)
        route_canvas.configure(yscrollcommand=route_scroll.set)
        route_scroll.pack(side='right',fill='y');route_canvas.pack(side='left',fill='both',expand=True)
        routes = ttk.Frame(route_canvas,padding=5)
        route_window = route_canvas.create_window(0,0,window=routes,anchor='nw')
        routes.bind('<Configure>',lambda e:route_canvas.configure(scrollregion=route_canvas.bbox('all')))
        route_canvas.bind('<Configure>',lambda e:route_canvas.itemconfigure(route_window,width=e.width))
        self.tabs.add(objects,text='点位 / 区域');self.tabs.add(route_tab,text='巡逻路线')
        self.objects = ttk.Treeview(objects,columns=('kind','name'),show='headings',height=12,selectmode='browse')
        self.objects.heading('kind',text='类型');self.objects.heading('name',text='名称')
        self.objects.column('kind',width=65,stretch=False);self.objects.column('name',width=245)
        self.objects.pack(fill='both',expand=True);self.objects.bind('<<TreeviewSelect>>',self.object_select)
        ttk.Label(objects,text='名称').pack(anchor='w');ttk.Entry(objects,textvariable=self.name).pack(fill='x')
        ttk.Label(objects,text='备注（刷新规律、观察情况等）').pack(anchor='w')
        self.notes = tk.Text(objects,height=3,width=35);self.notes.pack(fill='x')
        ttk.Label(objects,text='刷新间隔秒（未知留空，仅宝藏点）').pack(anchor='w')
        ttk.Entry(objects,textvariable=self.refresh_seconds).pack(fill='x')
        ttk.Checkbutton(objects,text='该跳跃已手动验证',variable=self.jump_verified).pack(anchor='w')
        ttk.Button(objects,text='应用名称 / 备注',command=self.apply_properties).pack(fill='x',pady=3)
        row = ttk.Frame(objects);row.pack(fill='x')
        ttk.Button(row,text='选中点加入路线',command=self.add_selected).pack(side='left')
        ttk.Button(row,text='反转跳跃方向',command=self.reverse_jump).pack(side='left')
        ttk.Button(objects,text='删除选中标注',command=self.delete_selected).pack(fill='x',pady=4)
        self.route_combo = ttk.Combobox(routes,state='readonly');self.route_combo.pack(fill='x')
        self.route_combo.bind('<<ComboboxSelected>>',self.select_route)
        row = ttk.Frame(routes);row.pack(fill='x',pady=3)
        ttk.Button(row,text='新路线',command=self.new_route).pack(side='left')
        ttk.Button(row,text='重命名',command=self.rename_route).pack(side='left')
        ttk.Checkbutton(row,text='闭环',variable=self.loop,command=self.set_loop).pack(side='left',padx=8)
        self.stops = tk.Listbox(routes,height=11,width=38,exportselection=False)
        self.stops.pack(fill='both',expand=True);self.stops.bind('<<ListboxSelect>>',self.stop_select)
        row = ttk.Frame(routes);row.pack(fill='x',pady=3)
        for text,command in [('↑',lambda:self.move_stop(-1)),('↓',lambda:self.move_stop(1)),
            ('移出路线',self.remove_stop),('反转顺序',self.reverse_route)]:ttk.Button(row,text=text,command=command).pack(side='left')
        ttk.Button(routes,text='全部宝藏追加到路线',command=self.append_treasures).pack(fill='x')
        ttk.Button(routes,text='建议顺序（直线距离，保留首点）',command=self.suggest_order).pack(fill='x',pady=3)
        row = ttk.Frame(routes);row.pack(fill='x',pady=2)
        ttk.Label(row,text='网格 px').pack(side='left');ttk.Spinbox(row,from_=1,to=16,width=3,textvariable=self.cell).pack(side='left')
        ttk.Label(row,text='安全边距 px').pack(side='left');ttk.Spinbox(row,from_=0,to=30,width=3,textvariable=self.clearance).pack(side='left')
        ttk.Checkbutton(routes,text='规划可使用已验证的定向跳跃',variable=self.allow_jumps).pack(anchor='w')
        ttk.Button(routes,text='按可走区绕障规划',command=self.plan_route).pack(fill='x',pady=2)
        ttk.Button(routes,text='定位 + 路线跟随辅助预览',command=self.follow_preview).pack(fill='x',pady=2)
        ttk.Button(routes,text='仅W + 转镜头自动行走 / 跳跃（F12停止）',command=lambda:self.follow_preview(live=True)).pack(fill='x',pady=2)
        ttk.Combobox(routes,state='readonly',textvariable=self.estimator,values=('小地图（同时记录预测误差）','融合（巡航短暂丢帧预测）')).pack(fill='x')
        row=ttk.Frame(routes);row.pack(fill='x',pady=2)
        ttk.Button(row,text='示教记录（手动走）',command=lambda:self.follow_preview(teach=True)).pack(side='left',expand=True,fill='x')
        ttk.Button(row,text='复走示教（自动）',command=lambda:self.follow_preview(live=True,replay=True)).pack(side='left',expand=True,fill='x')
        ttk.Button(routes,text='查看最近运行对照',command=self.show_comparison).pack(fill='x')
        ttk.Button(routes,text='W加速 / 镜头一圈标定工具',command=self.motion_probe).pack(fill='x',pady=2)
        self.report = tk.Text(routes,height=6,width=38,wrap='word',state='disabled');self.report.pack(fill='x')
        ttk.Label(side,text='路线模式：点击已有点加入路线；\n点击空白添加拐点。右键拖动画布。\n滚轮滚动，Ctrl+滚轮等比缩放。',justify='left').pack(anchor='w')
        ttk.Label(self.root,textvariable=self.status,anchor='w',padding=5).grid(row=2,column=0,columnspan=2,sticky='ew')
        self.canvas.bind('<Button-1>',self.click);self.canvas.bind('<B1-Motion>',self.drag)
        self.canvas.bind('<ButtonRelease-1>',self.release);self.canvas.bind('<Double-Button-1>',lambda e:self.finish_polygon())
        self.canvas.bind('<Button-3>',lambda e:self.canvas.scan_mark(e.x,e.y))
        self.canvas.bind('<B3-Motion>',lambda e:self.canvas.scan_dragto(e.x,e.y,gain=1))
        self.canvas.bind('<MouseWheel>',lambda e:self.canvas.yview_scroll(-1 if e.delta>0 else 1,'units'))
        self.canvas.bind('<Control-MouseWheel>',lambda e:self.set_zoom(self.zoom*(1.25 if e.delta>0 else .8)))
        self.root.bind('<Control-s>',lambda e:self.save());self.root.bind('<Control-z>',lambda e:self.undo())
        self.root.bind('<Return>',lambda e:self.finish_polygon() if not self.editing_text() else None)
        self.root.bind('<Escape>',lambda e:self.cancel_draft());self.root.bind('<Delete>',self.keyboard_delete)
        self.root.protocol('WM_DELETE_WINDOW',self.close)
        self.refresh();self.root.update_idletasks()

    def editing_text(self):return isinstance(self.root.focus_get(),(tk.Entry,ttk.Entry,tk.Text))

    def keyboard_delete(self,event=None):
        if self.editing_text():return
        if self.root.focus_get()==self.stops:self.remove_stop()
        else:self.delete_selected()

    def point_from_event(self,event):
        return self.project.xy((self.canvas.canvasx(event.x)/self.zoom,self.canvas.canvasy(event.y)/self.zoom))

    def hit_point(self,xy):
        choices = [(math.dist(p['xy'],xy),p['id']) for p in self.project.data['points']]
        return min(choices)[1] if choices and min(choices)[0]<=12/self.zoom else None

    def click(self,event):
        try:xy = self.point_from_event(event)
        except ValueError:return
        mode = self.mode.get()
        if mode=='select':
            self.selected = self.hit_point(xy)
            if self.selected:self.drag_before = deepcopy(self.project.data)
            self.refresh();return
        if mode in ('walkable','blocked','jump'):
            if not self.draft or math.dist(self.draft[-1],xy)>1:self.draft.append(xy)
            if mode=='jump' and len(self.draft)==2:
                try:self.selected = self.project.add_jump(*self.draft);self.draft = [];self.changed()
                except ValueError as error:self.status.set(str(error))
            self.draw();return
        existing = self.hit_point(xy)
        if mode=='treasure':
            if existing:self.selected = existing;self.refresh();return
            self.selected = self.project.add_point(xy)
        elif mode=='route':
            if existing and self.project.route['nodes'] and self.project.route['nodes'][-1]==existing:
                self.selected = existing;self.refresh();return
            self.selected = self.project.add_route_stop(xy,existing)
        self.changed()

    def drag(self,event):
        if self.mode.get()!='select' or not self.selected or self.drag_before is None:return
        try:xy = self.point_from_event(event)
        except ValueError:return
        category,item = self.project.find(self.selected)
        if category=='points':item['xy'] = xy;self.draw()

    def release(self,event):
        if self.drag_before is not None:
            if self.drag_before!=self.project.data:
                self.project.history.append(self.drag_before);self.project.history = self.project.history[-60:];self.changed()
            self.drag_before = None

    def finish_polygon(self):
        if self.mode.get() not in ('walkable','blocked'):return
        if len(self.draft)<3:self.status.set('多边形至少需要三个点。');return
        try:self.selected = self.project.add_region(self.draft,self.mode.get());self.draft = [];self.changed()
        except ValueError as error:self.status.set(str(error))

    def cancel_draft(self):self.draft = [];self.draw()

    def set_zoom(self,value):
        self.zoom = max(.25,min(4.,value));self.draw()
        self.status.set(f'显示 {self.zoom:.0%}；地图坐标与标注不随缩放变化。')

    def draw(self):
        self.canvas.delete('all');z = self.zoom
        image = Image.fromarray(cv2.cvtColor(self.project.image,cv2.COLOR_BGR2RGB))
        if z!=1:image = image.resize((round(self.project.width*z),round(self.project.height*z)),Image.Resampling.LANCZOS)
        self.photo = ImageTk.PhotoImage(image,master=self.root)
        self.canvas.create_image(0,0,anchor='nw',image=self.photo)
        self.canvas.configure(scrollregion=(0,0,self.project.width*z,self.project.height*z))
        def coords(points):return [coordinate*z for p in points for coordinate in p]
        for region in self.project.data['regions']:
            color = '#36dc80' if region['kind']=='walkable' else '#ff5964'
            self.canvas.create_polygon(*coords(region['polygon']),fill=color,stipple='gray25',outline=color,width=2)
        route = self.project.route_points();pairs = list(zip(route,route[1:]))
        if self.project.route['loop'] and len(route)>1:pairs.append((route[-1],route[0]))
        if self.plan:
            for segment in self.plan['segments']:
                if len(segment['points'])>1:self.canvas.create_line(*coords(segment['points']),fill='#e080ff' if segment['kind']=='jump' else '#28eda0',width=3,arrow='last')
        else:
            for a,b in pairs:self.canvas.create_line(*coords([a['xy'],b['xy']]),fill='#52aaff',width=3,arrow='last')
        for jump in self.project.data['jumps']:
            self.canvas.create_line(*coords([jump['start'],jump['end']]),fill='#e080ff',width=3,arrow='last')
            self.canvas.create_text(*coords([jump['start']]),text=jump['name'],fill='#edc2ff',anchor='sw')
        for point in self.project.data['points']:
            x,y = np.asarray(point['xy'])*z;r = 6 if point['kind']=='treasure' else 4
            self.canvas.create_oval(x-r,y-r,x+r,y+r,fill='#ffbe24' if point['kind']=='treasure' else '#52aaff',outline='black')
            if point['id']==self.selected:self.canvas.create_oval(x-10,y-10,x+10,y+10,outline='white',width=2)
            self.canvas.create_text(x+9,y-7,text=point['name'],fill='white',anchor='sw')
        for i,point in enumerate(route):
            x,y = np.asarray(point['xy'])*z;self.canvas.create_text(x-9,y+13,text=str(i+1),fill='white')
        if self.draft:
            if len(self.draft)>1:self.canvas.create_line(*coords(self.draft),fill='white',width=2,dash=(5,3))
            for x,y in self.draft:self.canvas.create_oval(x*z-3,y*z-3,x*z+3,y*z+3,fill='white')

    def refresh(self):
        self.refreshing = True
        self.objects.delete(*self.objects.get_children())
        for category in ('points','regions','jumps'):
            for item in self.project.data[category]:
                self.objects.insert('',tk.END,iid=item['id'],values=(LABELS.get(item.get('kind'),'跳跃'),item['name']))
        if self.selected and self.objects.exists(self.selected):self.objects.selection_set(self.selected)
        else:self.selected = None
        self.route_combo['values'] = [r['name'] for r in self.project.data['routes']]
        self.route_combo.current(next(i for i,r in enumerate(self.project.data['routes']) if r['id']==self.project.data['active_route']))
        self.loop.set(self.project.route['loop']);self.stops.delete(0,tk.END)
        for i,p in enumerate(self.project.route_points()):self.stops.insert(tk.END,f"{i+1}. {p['name']} [{LABELS[p['kind']]}]")
        self.load_properties();self.draw()
        report = self.project.route_report()
        self.report.configure(state='normal');self.report.delete('1.0',tk.END)
        if self.plan:
            jumps = sum(s['kind']=='jump' for s in self.plan['segments'])
            self.report.insert(tk.END,f"已规划 {self.plan['length_pixels']} 地图像素 · 跳跃 {jumps} 处\n绿色为绕障路线，紫色跳跃需手动操作。\n仅使用已标可走区；通行仍需实地核对。")
        else:self.report.insert(tk.END,f"{report['point_count']} 个途经点 · {report['length_pixels']} 地图像素\n"+'\n'.join(report['warnings'] or ['当前标注检查未发现冲突；仍需实地确认。']))
        self.report.configure(state='disabled')
        self.status.set(f"{self.project.path} · {self.zoom:.0%} · 宝藏 {sum(p['kind']=='treasure' for p in self.project.data['points'])} 个")
        self.refreshing = False

    def load_properties(self):
        self.name.set('');self.refresh_seconds.set('');self.jump_verified.set(False);self.notes.delete('1.0',tk.END)
        if self.selected:
            _,item = self.project.find(self.selected);self.name.set(item['name'])
            self.notes.insert('1.0',item.get('notes',''))
            self.jump_verified.set(item.get('verified',False))
            if item.get('refresh_seconds') is not None:self.refresh_seconds.set(str(item['refresh_seconds']))

    def object_select(self,event=None):
        if self.refreshing:return
        selected = self.objects.selection()
        if selected:self.selected = selected[0];self.load_properties();self.draw()

    def stop_select(self,event=None):
        if self.stops.curselection():
            self.selected = self.project.route['nodes'][self.stops.curselection()[0]];self.load_properties();self.draw()

    def apply_properties(self,refresh=True):
        if not self.selected:return True
        try:
            _,item = self.project.find(self.selected)
            seconds = float(self.refresh_seconds.get()) if self.refresh_seconds.get().strip() else None
            if seconds is not None and (not math.isfinite(seconds) or seconds<=0):raise ValueError('刷新间隔需为正数，未知请留空。')
            values = dict(name=self.name.get().strip() or item['name'],notes=self.notes.get('1.0','end-1c'),
                **({'refresh_seconds':seconds} if item.get('kind')=='treasure' else {}))
            if 'direction' in item:values['verified'] = self.jump_verified.get()
            if any(item.get(key)!=value for key,value in values.items()):
                self.project.change(lambda:item.update(values))
                if refresh:self.changed()
            return True
        except ValueError as error:self.status.set(str(error));return False

    def add_selected(self):
        try:self.project.add_to_route(self.selected);self.changed();self.tabs.select(1)
        except ValueError as error:self.status.set(str(error))

    def delete_selected(self):
        if self.selected:self.project.delete(self.selected);self.selected = None;self.changed()

    def reverse_jump(self):
        if not self.selected:return
        category,item = self.project.find(self.selected)
        if category!='jumps':self.status.set('先在列表中选择一条跳跃连接。');return
        self.project.change(lambda:item.update(start=item['end'],end=item['start'],verified=False));self.changed()

    def move_stop(self,delta):
        if not self.stops.curselection():return
        i = self.stops.curselection()[0];j = i+delta
        if not 0<=j<len(self.project.route['nodes']):return
        def operation():self.project.route['nodes'][i],self.project.route['nodes'][j] = self.project.route['nodes'][j],self.project.route['nodes'][i]
        self.project.change(operation);self.changed();self.stops.selection_set(j)

    def remove_stop(self):
        if self.stops.curselection():
            i = self.stops.curselection()[0];self.project.change(lambda:self.project.route['nodes'].pop(i));self.changed()

    def reverse_route(self):self.project.change(lambda:self.project.route['nodes'].reverse());self.changed()
    def set_loop(self):self.project.change(lambda:self.project.route.update(loop=self.loop.get()));self.changed()
    def suggest_order(self):self.project.suggest_order();self.changed();self.status.set('已按直线距离建议顺序；请检查禁行区并添加绕行拐点。可撤销。')

    def append_treasures(self):
        identifiers = [p['id'] for p in self.project.data['points'] if p['kind']=='treasure' and p['id'] not in self.project.route['nodes']]
        self.project.change(lambda:self.project.route['nodes'].extend(identifiers));self.changed()

    def select_route(self,event=None):
        if not self.refreshing:
            self.project.data['active_route'] = self.project.data['routes'][self.route_combo.current()]['id'];self.changed()

    def new_route(self):
        name = simpledialog.askstring('新路线','路线名称',parent=self.root)
        if name:
            identifier = uuid.uuid4().hex[:12]
            def operation():
                self.project.data['routes'].append(dict(id=identifier,name=name,nodes=[],loop=False));self.project.data['active_route'] = identifier
            self.project.change(operation);self.changed()

    def rename_route(self):
        name = simpledialog.askstring('路线名称','名称',initialvalue=self.project.route['name'],parent=self.root)
        if name:self.project.change(lambda:self.project.route.update(name=name));self.changed()

    def changed(self):
        self.plan = None
        self.refresh()
        if self.save_job:self.root.after_cancel(self.save_job)
        self.save_job = self.root.after(500,self.save)

    def save(self):
        if self.save_job:self.root.after_cancel(self.save_job);self.save_job = None
        if not self.apply_properties(refresh=False):return False
        try:self.project.save();self.status.set(f'已保存：{self.project.path}');return True
        except (OSError,ValueError) as error:messagebox.showerror('保存失败',str(error),parent=self.root);return False

    def undo(self):
        if self.project.undo():self.draft = [];self.changed()

    def export(self):
        try:
            if not self.save():return
            folder = self.project.export(self.plan);self.status.set(f'已导出：{folder}')
            messagebox.showinfo('导出完成',f'{folder}\n\n包含路线 JSON、完整标注、标注预览及可走/禁行掩膜。',parent=self.root)
        except (OSError,ValueError) as error:messagebox.showerror('导出失败',str(error),parent=self.root)

    def open_project(self):
        filename = filedialog.askopenfilename(parent=self.root,title='打开标注项目',filetypes=[('标注项目','project.json'),('JSON','*.json')])
        if filename:
            try:
                project = NavigationProject(filename)
                if not self.save():return
                self.project = project;self.plan = None;self.selected = None;self.draft = [];self.refresh()
            except (OSError,ValueError,KeyError) as error:messagebox.showerror('打开失败',str(error),parent=self.root)

    def new_project(self):
        filename = filedialog.askopenfilename(parent=self.root,title='选择地图定位配置 patrol-config.json',filetypes=[('JSON','*.json')])
        if filename:
            try:
                if not self.save():return
                folder = ROOT/'runtime/patrol/navigation'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6])
                self.project = NavigationProject.create(filename,folder);self.plan = None;self.selected = None;self.draft = [];self.refresh()
            except (OSError,ValueError,KeyError) as error:messagebox.showerror('新建失败',str(error),parent=self.root)

    def close(self):
        if not self.closed and self.save():self.closed = True;self.root.destroy()

    def run(self):self.root.mainloop()

    def plan_route(self):
        from modular_agent.domains.hololive_dreams.navigation_planner import plan_project
        try:
            if not self.save():return
            self.plan = plan_project(self.project,cell=self.cell.get(),clearance=self.clearance.get(),allow_jumps=self.allow_jumps.get())
            self.refresh()
        except (ValueError,tk.TclError) as error:
            self.plan = None;self.refresh();self.status.set(str(error))

    def motion_probe(self):
        import subprocess,sys,os
        if not self.plan:self.status.set('请先按可走区规划路线，标定工具需要该地图的可走掩膜。');return
        try:
            if not self.save():return
            folder=self.project.export(self.plan)
            if not (folder/'patrol-config.json').is_file():raise ValueError('缺少原地图定位配置')
            env=os.environ.copy();env['PYTHONPATH']=str(ROOT/'src');env['PYTHONIOENCODING']='utf-8'
            subprocess.Popen([sys.executable,'-B','-m','modular_agent.realtime.motion_probe','--config',str(folder/'patrol-config.json'),
                '--walk-mask',str(folder/'planning-mask.png')],cwd=ROOT,env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.status.set('标定工具已打开，请选择测镜头或测W；结果不会自动改写现有寻路参数。')
        except (OSError,ValueError) as error:self.status.set(str(error))

    def show_comparison(self):
        from modular_agent.realtime.patrol import read_json
        paths=sorted((self.project.path.parent/'exports').glob('*/run/summary.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:10]
        rows=['模式 / 路线 · 单步预测误差 / 纯输入累计偏差 · 结束原因']
        for path in paths:
            try:
                data=read_json(path);metrics=data.get('estimator_comparison') or {}
                error=metrics.get('mean_innovation');drift=metrics.get('inertial_end_error')
                format_error=lambda value:f'{value:.1f}px' if isinstance(value,(float,int)) else '—'
                mode='示教' if data.get('control_mode')=='teaching' else data.get('estimator_mode','旧版')
                rows.append(f"{mode} / {data.get('route_name','')} · {format_error(error)} / {format_error(drift)} · {data.get('reason','')}\n{path.parent.parent.name}")
            except (OSError,ValueError):continue
        rows.append('预测偏差是与小地图的一致性，不是物理真值；先比较同一路线。')
        self.report.configure(state='normal');self.report.delete('1.0',tk.END)
        self.report.insert('1.0','\n'.join(rows));self.report.configure(state='disabled')

    def follow_preview(self,live=False,teach=False,replay=False):
        import subprocess,sys,os
        if getattr(self,'route_process',None) is not None and self.route_process.poll() is None:
            self.status.set('已有路线窗口运行，请先关闭预览或按F12停止。');return
        if not self.plan:self.status.set('请先按可走区规划路线。');return
        try:
            if not self.save():return
            folder = self.project.export(self.plan)
            if not (folder/'patrol-config.json').is_file():raise ValueError('缺少原地图定位配置，请恢复 source_config 后再预览')
            env = os.environ.copy();env['PYTHONPATH'] = str(ROOT/'src');env['PYTHONIOENCODING'] = 'utf-8'
            with (folder/'follow-preview.log').open('w',encoding='utf-8') as log:
                self.route_process=subprocess.Popen([sys.executable,'-m','modular_agent.realtime.patrol','preview','--fast-track',
                    '--config',str(folder/'patrol-config.json'),'--planned-route',str(folder/'planned-route.json'),
                    '--fps','10','--start-delay','8','--output',str(folder/'run'),
                    '--estimator','fused' if self.estimator.get().startswith('融合') else 'visual']+
                    (['--live-route'] if live else [])+(['--teach-route'] if teach else [])+(['--replay-demo'] if replay else []),cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            self.status.set('示教已启动：8秒内切回游戏，手动走动/转向/空格，F12结束保存。' if teach else
                ('自动路线已启动，8秒内切回游戏；手动空格记忆跳跃点，F12停止。' if live else '路线辅助预览已启动，8秒内切回游戏；仅定位和建议，不发送按键。'))
            self.root.after(1000,lambda:self.watch_route_process(folder))
        except (OSError,ValueError) as error:self.status.set(str(error))

    def watch_route_process(self,folder):
        if self.closed:return
        if self.route_process.poll() is None:
            self.root.after(1000,lambda:self.watch_route_process(folder));return
        from modular_agent.realtime.patrol import read_json
        summary=folder/'run/summary.json'
        try:reason=read_json(summary)['reason']
        except (OSError,ValueError,KeyError):reason='启动失败，查看 follow-preview.log'
        explanations={'stale_or_blocked_scene':'画面超时保护停止（已松键）',
            'free_scene_lost':'自由场景未确认，已停止',
            'localization_timeout':'连续无法定位，已停止',
            'camera_turn_not_observed':'镜头转动后未识别到响应，已停止',
            'route_traversed_collection_unverified':'已走完路线，未验证拾取',
            'window_unavailable_or_unfocused':'游戏失焦或不可用，已停止'}
        self.status.set(f'路线窗口已结束：{explanations.get(reason,reason)}；诊断目录：{folder}')


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',type=Path);parser.add_argument('--config',type=Path)
    args = parser.parse_args(argv)
    project = NavigationProject(args.project) if args.project else default_project(args.config)
    NavigationEditor(project).run()


if __name__=='__main__':main()
