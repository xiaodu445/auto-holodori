"""Per-map workflow launcher. Capture remains in the existing guarded modules."""
from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import ttk,filedialog,simpledialog,messagebox
import uuid

from modular_agent.realtime.patrol import ROOT,DATA,read_json,latest_repaired_config
from modular_agent.domains.hololive_dreams.patrol_vision import MinimapSpec
from modular_agent.domains.hololive_dreams.navigation_annotations import NavigationProject,digest,atomic_json


WORKSPACES = ROOT/'runtime/patrol/map-projects'


def valid_reference(path,manual=False):
    try:
        path = Path(path).resolve();config = read_json(path)
        if not (path.parent/config['reference']).is_file():return False
        return not manual or (path.parent/'alignment.json').is_file()
    except (OSError,ValueError,KeyError,TypeError):return False


class MapWorkspace:
    def __init__(self,path):
        self.path = Path(path).resolve();self.data = read_json(self.path)
        if self.data.get('version')!=1:raise ValueError('不支持的地图项目版本')
        self.root = self.path.parent

    @classmethod
    def create(cls,name,*,reference=None,root=WORKSPACES):
        if not name.strip():raise ValueError('地图名称不能为空')
        if reference and not valid_reference(reference):raise ValueError('参考配置或地图文件不完整')
        folder = Path(root)/uuid.uuid4().hex[:12];folder.mkdir(parents=True,exist_ok=False)
        source = read_json(reference) if reference else read_json(DATA/'config.json')
        spec = source.get('minimap',{})
        MinimapSpec(**spec)
        atomic_json(folder/'capture-config.json',dict(minimap=spec))
        data = dict(version=1,id=folder.name,name=name.strip(),recordings=[],manual_config=None,
                    reference_config=str(Path(reference).resolve()) if reference else None,annotation_project=None)
        if reference:
            candidate = Path(reference)
            if valid_reference(candidate,manual=True):data['manual_config'] = str(candidate.resolve())
            else:
                metadata = candidate.parent/'mapping.json'
                if metadata.is_file():
                    origin = read_json(metadata).get('source_config')
                    if origin and valid_reference(origin,manual=True):data['manual_config'] = str(Path(origin).resolve())
        atomic_json(folder/'map-project.json',data)
        return cls(folder/'map-project.json')

    def save(self):atomic_json(self.path,self.data)

    def new_recording(self,mode,output=None):
        output = Path(output) if output else self.root/'recordings'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        self.data['recordings'].append(dict(path=str(output),mode=mode));self.save()
        return output

    def import_recording(self,folder):
        folder = Path(folder).resolve()
        if not (folder/'frames.jsonl').is_file() or not (folder/'tiles').is_dir():raise ValueError('请选择包含frames.jsonl和tiles的录制目录')
        if not any(Path(r['path'])==folder for r in self.data['recordings']):
            self.data['recordings'].append(dict(path=str(folder),mode='imported'));self.save()

    def manual_reference(self):
        explicit = self.data.get('manual_config')
        if explicit and valid_reference(explicit,manual=True):return Path(explicit)
        candidates = [p for p in (self.root/'alignment').rglob('patrol-config.json') if valid_reference(p,manual=True)]
        return max(candidates,key=lambda p:p.stat().st_mtime) if candidates else None

    def reference(self):
        explicit = self.data.get('reference_config')
        if explicit and valid_reference(explicit):return Path(explicit)
        for row in reversed(self.data['recordings']):
            config = Path(row['path'])/'patrol-config.json'
            if row['mode']=='repair' and valid_reference(config):return config
        return self.manual_reference()

    def capture_args(self,output,*,duration=1200,fps=4,resume=None,repair=False):
        if not 0<duration<=7200 or not 0<fps<=20:raise ValueError('采集时长或帧率超出范围')
        args = ['-m','modular_agent.realtime.minimap_scan','--config',str(self.root/'capture-config.json'),
                '--output',str(output),'--duration',str(duration),'--fps',str(fps),'--start-delay','8',
                '--stop-file',str(Path(output)/'STOP')]
        if repair:
            reference = self.manual_reference()
            if not reference:raise ValueError('请先拼图导出，或绑定这张地图的手工底图配置')
            args += ['--reference-config',str(reference),'--repair-map']
        else:
            args += ['--clean-overlays']
            if resume:
                if not (Path(resume)/'state.npz').is_file():raise ValueError('选中记录没有可续扫状态')
                args += ['--resume',str(resume)]
        return args

    def annotation(self):
        reference = self.reference()
        if reference is None:raise ValueError('请先选择本地图的参考配置')
        signature = digest(reference.parent/read_json(reference)['reference'])
        explicit = self.data.get('annotation_project')
        if explicit:
            project = NavigationProject(explicit)
            if project.data['map']['sha256']==signature:return project
        for candidate in (self.root/'navigation').glob('*/project.json'):
            project = NavigationProject(candidate)
            if project.data['map']['sha256']==signature:return project
        project = NavigationProject.create(reference,self.root/'navigation'/uuid.uuid4().hex[:12])
        self.data['annotation_project'] = str(project.path);self.save()
        return project


class MapWorkbench:
    def __init__(self,*,visible=True,root=WORKSPACES):
        self.folder = Path(root);self.folder.mkdir(parents=True,exist_ok=True)
        self.root = tk.Tk();self.root.title('多地图建图工作台')
        if not visible:self.root.withdraw()
        self.root.geometry('940x700');self.root.columnconfigure(1,weight=1);self.root.rowconfigure(1,weight=1)
        self.workspace = None;self.children = [];self.profiles = [];self.rows = []
        self.status = tk.StringVar(value='每张地图单独管理。新建地图后，先手动走动采集。')
        self.duration = tk.IntVar(value=1200);self.fps = tk.IntVar(value=4)
        top = ttk.Frame(self.root,padding=8);top.grid(row=0,column=0,columnspan=2,sticky='ew')
        for text,command in [('新建地图',self.new_map),('导入已有地图',self.import_map),('重命名',self.rename),('刷新',self.refresh)]:
            ttk.Button(top,text=text,command=command).pack(side='left',padx=3)
        self.maps = tk.Listbox(self.root,width=25,exportselection=False)
        self.maps.grid(row=1,column=0,sticky='nsew',padx=8);self.maps.bind('<<ListboxSelect>>',self.select)
        panel = ttk.Frame(self.root,padding=8);panel.grid(row=1,column=1,sticky='nsew')
        panel.columnconfigure(0,weight=1);panel.rowconfigure(4,weight=1)
        capture = ttk.LabelFrame(panel,text='1 · 录像采集（你手动走动，8秒后开始）',padding=8)
        capture.grid(row=0,column=0,sticky='ew',pady=4)
        row = ttk.Frame(capture);row.pack(fill='x')
        ttk.Label(row,text='秒数').pack(side='left');ttk.Spinbox(row,from_=30,to=7200,textvariable=self.duration,width=7).pack(side='left')
        ttk.Label(row,text='采集 FPS').pack(side='left',padx=5);ttk.Spinbox(row,from_=1,to=20,textvariable=self.fps,width=4).pack(side='left')
        ttk.Button(row,text='小地图布局配置',command=self.set_layout).pack(side='left',padx=8)
        row = ttk.Frame(capture);row.pack(fill='x',pady=5)
        for text,command in [('新采集',lambda:self.capture()),('续扫选中记录',lambda:self.capture(resume=True)),('停止本工具采集',self.stop_capture)]:
            ttk.Button(row,text=text,command=command).pack(side='left',padx=2)
        records = ttk.LabelFrame(panel,text='2 · 选择录像 / 手工拼图',padding=8);records.grid(row=1,column=0,sticky='ew',pady=4)
        self.record_combo = ttk.Combobox(records,state='readonly',width=60);self.record_combo.pack(fill='x')
        row = ttk.Frame(records);row.pack(fill='x',pady=5)
        for text,command in [('导入录像目录',self.import_recording),('打开手工拼图/掩膜',self.align),('绑定手工底图',self.bind_manual)]:
            ttk.Button(row,text=text,command=command).pack(side='left',padx=2)
        use = ttk.LabelFrame(panel,text='3 · 修复 / 追踪 / 宝藏路线',padding=8);use.grid(row=2,column=0,sticky='ew',pady=4)
        row = ttk.Frame(use);row.pack(fill='x')
        for text,command in [('修复补图',lambda:self.capture(repair=True)),('选择参考图配置',self.bind_reference),('位置追踪',self.track)]:
            ttk.Button(row,text=text,command=command).pack(side='left',padx=2)
        row = ttk.Frame(use);row.pack(fill='x',pady=5)
        ttk.Button(row,text='宝藏/路线标注',command=self.annotate).pack(side='left',padx=2)
        ttk.Button(row,text='绑定已有标注项目',command=self.bind_annotations).pack(side='left',padx=2)
        ttk.Button(row,text='项目目录',command=self.open_folder).pack(side='left',padx=2)
        ttk.Button(use,text='使用选中记录的地图作为参考',command=self.adopt_recording).pack(fill='x')
        self.info = tk.Text(panel,height=12,width=75,wrap='word',state='disabled');self.info.grid(row=4,column=0,sticky='nsew',pady=5)
        ttk.Label(self.root,textvariable=self.status,padding=8,wraplength=910).grid(row=2,column=0,columnspan=2,sticky='ew')
        self.refresh();self.root.after(1000,self.poll)

    def guarded(self,fn):
        try:
            if self.workspace is None:raise ValueError('请先选择或新建地图')
            return fn()
        except (OSError,ValueError,KeyError,tk.TclError) as error:self.status.set(str(error));return None

    def refresh(self):
        current = self.workspace.path if self.workspace else None
        self.profiles = []
        for path in sorted(self.folder.glob('*/map-project.json')):
            try:self.profiles.append(MapWorkspace(path))
            except (OSError,ValueError):continue
        self.maps.delete(0,tk.END)
        for i,profile in enumerate(self.profiles):
            self.maps.insert(tk.END,profile.data['name'])
            if profile.path==current:self.maps.selection_set(i);self.workspace = profile
        self.update_info()

    def select(self,event=None):
        if self.maps.curselection():self.workspace = self.profiles[self.maps.curselection()[0]];self.update_info()

    def update_info(self):
        if self.workspace is None:return
        self.rows = self.workspace.data['recordings']
        self.record_combo['values'] = [f"{Path(r['path']).name} · {r['mode']}" for r in self.rows]
        if self.rows:self.record_combo.current(len(self.rows)-1)
        text = f"地图：{self.workspace.data['name']}\n项目：{self.workspace.root}\n\n手工底图：{self.workspace.manual_reference() or '尚未绑定/导出'}\n\n参考图：{self.workspace.reference() or '尚未选择'}\n\n采集目录分别保存，原图不覆盖。新图初扫已启用光锥/随机标记排除，长距离漂移仍建议手工检查后修复。\n本工作台仅启动被动采集/预览和离线编辑，不启用WASD自动探索。"
        self.info.configure(state='normal');self.info.delete('1.0',tk.END);self.info.insert(tk.END,text);self.info.configure(state='disabled')

    def new_map(self):
        name = simpledialog.askstring('新地图','地图名称',parent=self.root)
        if name:
            try:self.workspace = MapWorkspace.create(name,root=self.folder);self.refresh()
            except (OSError,ValueError) as error:self.status.set(str(error))

    def import_map(self):
        try:initial = latest_repaired_config().parent
        except ValueError:initial = ROOT/'runtime/patrol/maps'
        source = filedialog.askopenfilename(parent=self.root,title='选择已有地图 patrol-config.json',initialdir=str(initial),initialfile='patrol-config.json',filetypes=[('JSON','*.json')])
        if source:
            name = simpledialog.askstring('导入地图','地图名称',initialvalue='已有地图',parent=self.root)
            if name:
                try:self.workspace = MapWorkspace.create(name,reference=source,root=self.folder);self.refresh()
                except (OSError,ValueError) as error:self.status.set(str(error))

    def rename(self):
        if self.workspace:
            name = simpledialog.askstring('地图名称','名称',initialvalue=self.workspace.data['name'],parent=self.root)
            if name:self.workspace.data['name'] = name.strip();self.workspace.save();self.refresh()

    def selected_recording(self):
        index = self.record_combo.current()
        if index<0:raise ValueError('请先采集或导入录像')
        recording = Path(self.rows[index]['path'])
        if not (recording/'frames.jsonl').is_file():raise ValueError('选中记录尚未完成或未开始采集')
        return recording

    def launch(self,args,*,capture_output=None):
        if any(child['process'].poll() is None and child['capture'] for child in self.children):
            raise ValueError('请先停止本工作台正在进行的采集，再切换任务')
        env = os.environ.copy();env['PYTHONPATH'] = str(ROOT/'src');env['PYTHONIOENCODING'] = 'utf-8'
        logs = self.workspace.root/'logs';logs.mkdir(exist_ok=True)
        log_path = logs/(datetime.now().strftime('%Y%m%d-%H%M%S-%f')+'.log')
        with log_path.open('w',encoding='utf-8') as log:
            process = subprocess.Popen([sys.executable,*args],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        self.children.append(dict(process=process,capture=capture_output,log=log_path,reported=False))
        self.status.set(f'已启动；采集/追踪请8秒内切回游戏。日志：{log_path}')

    def capture(self,resume=False,repair=False):
        def action():
            if any(child['process'].poll() is None and child['capture'] for child in self.children):raise ValueError('请先停止正在进行的采集')
            previous = self.selected_recording() if resume else None
            output = self.workspace.root/'recordings'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
            args = self.workspace.capture_args(output,duration=self.duration.get(),fps=self.fps.get(),resume=previous,repair=repair)
            self.workspace.new_recording('repair' if repair else 'scan',output)
            self.launch(args,capture_output=output);self.update_info()
        self.guarded(action)

    def stop_capture(self):
        for child in self.children:
            if child['capture'] and child['process'].poll() is None:
                folder = Path(child['capture']);folder.mkdir(parents=True,exist_ok=True);(folder/'STOP').write_text('stop',encoding='utf-8')
        self.status.set('已发停止文件，等待采集器保存并退出。F12也可停止。')

    def poll(self):
        for child in self.children:
            code = child['process'].poll()
            if code is not None and not child['reported']:
                child['reported'] = True;self.status.set(f'任务已退出，返回码 {code}；日志：{child["log"]}');self.update_info()
        self.root.after(1000,self.poll)

    def import_recording(self):
        folder = filedialog.askdirectory(parent=self.root,title='选择录像目录')
        if folder:self.guarded(lambda:(self.workspace.import_recording(folder),self.update_info()))

    def align(self):
        def action():
            recording = self.selected_recording();folder = self.workspace.root/'alignment'/recording.name;folder.mkdir(parents=True,exist_ok=True)
            self.launch([str(ROOT/'tools/minimap_align.py'),str(recording),'--from-zero','--project',str(folder/'alignment-project.json')])
        self.guarded(action)

    def bind_manual(self):
        path = filedialog.askopenfilename(parent=self.root,title='选择手工导出的 patrol-config.json',initialdir=str(self.workspace.root/'alignment') if self.workspace else str(ROOT/'runtime/patrol/alignments'),filetypes=[('JSON','*.json')])
        if path:
            def action():
                if not valid_reference(path,manual=True):raise ValueError('该目录需要包含手工导出的alignment.json和地图')
                self.workspace.data['manual_config'] = str(Path(path).resolve());self.workspace.save();self.update_info()
            self.guarded(action)

    def bind_reference(self):
        path = filedialog.askopenfilename(parent=self.root,title='选择本地图参考配置',initialdir=str(self.workspace.root) if self.workspace else str(ROOT/'runtime/patrol/maps'),filetypes=[('JSON','*.json')])
        if path:
            def action():
                if not valid_reference(path):raise ValueError('配置或参考图不完整')
                self.workspace.data['reference_config'] = str(Path(path).resolve());self.workspace.save();self.update_info()
            self.guarded(action)

    def adopt_recording(self):
        def action():
            config = self.selected_recording()/'patrol-config.json'
            if not valid_reference(config):raise ValueError('选中记录尚未导出地图配置')
            self.workspace.data['reference_config'] = str(config);self.workspace.save();self.update_info()
        self.guarded(action)

    def set_layout(self):
        path = filedialog.askopenfilename(parent=self.root,title='复用小地图布局配置（仅minimap字段）',filetypes=[('JSON','*.json')])
        if path:
            def action():
                spec = read_json(path)['minimap'];MinimapSpec(**spec)
                atomic_json(self.workspace.root/'capture-config.json',dict(minimap=spec));self.status.set('已复制小地图布局，地图坐标未导入。')
            self.guarded(action)

    def track(self):
        def action():
            reference = self.workspace.reference()
            if not reference:raise ValueError('请先绑定参考图配置')
            self.launch(['-m','modular_agent.realtime.patrol','preview','--fast-track','--config',str(reference),'--fps','10','--start-delay','8'])
        self.guarded(action)

    def annotate(self):
        self.guarded(lambda:self.launch(['-m','modular_agent.realtime.navigation_editor','--project',str(self.workspace.annotation().path)]))

    def bind_annotations(self):
        path = filedialog.askopenfilename(parent=self.root,title='选择已有宝藏/路线标注 project.json',initialdir=str(ROOT/'runtime/patrol/navigation'),filetypes=[('JSON','*.json')])
        if path:
            def action():
                project = NavigationProject(path);reference = self.workspace.reference()
                if not reference or digest(reference.parent/read_json(reference)['reference'])!=project.data['map']['sha256']:
                    raise ValueError('标注项目底图指纹与当前参考图不同')
                self.workspace.data['annotation_project'] = str(project.path);self.workspace.save();self.status.set('已绑定现有标注，原文件保留。')
            self.guarded(action)

    def open_folder(self):
        if self.workspace:os.startfile(self.workspace.root)


def main():MapWorkbench().root.mainloop()


if __name__=='__main__':main()
