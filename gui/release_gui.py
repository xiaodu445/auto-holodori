"""Minimal release GUI; worker owns all game input and cooperative cleanup."""
import os,sys,json,subprocess,threading,queue,uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('HOLOLIVE_DATA_DIR',str(Path(os.environ.get('LOCALAPPDATA',ROOT))/'HololiveRhythm')))
os.environ['HOLOLIVE_DATA_DIR']=str(DATA)
sys.path.insert(0,str(ROOT/'src'))

class App:
    def __init__(self,root):
        self.root=root;self.process=None;self.events=queue.Queue();self.closing=False
        root.title('hololive Dreams · 多人自动打歌');root.geometry('660x550')
        from modular_agent.domains.hololive_dreams.rhythm_profile import load_profile
        profile,_=load_profile(ROOT,'mechanism')
        defaults={'rounds':'3','offset':str(profile['input_offset_ms']),'grid-snap':str(profile['grid_snap_ms']),'window-width':'0','window-height':'0'}
        try:defaults.update(json.loads((DATA/'settings.json').read_text(encoding='utf-8')))
        except (OSError,ValueError):pass
        self.show_recognition=tk.BooleanVar(value=bool(defaults.pop('recognition_preview',True)))
        self.values={k:tk.StringVar(value=str(v)) for k,v in defaults.items()}
        frame=ttk.Frame(root,padding=16);frame.pack(fill='both',expand=True)
        ttk.Label(frame,text='多人演出自动循环',font=('Microsoft YaHei UI',17)).pack(anchor='w')
        ttk.Label(frame,text='按局数运行，无总时长上限；F12 停止。达标后停在续玩选择页。').pack(anchor='w',pady=8)
        fields=ttk.Frame(frame);fields.pack(fill='x')
        self.entries=[]
        for row,(key,label) in enumerate([('rounds','目标局数（1–1000）'),('offset','输入延迟补偿（ms，-500–500）'),('grid-snap','节拍吸附（ms，0–25）'),('window-width','游戏外框宽度（0 = 保持当前）'),('window-height','游戏外框高度（0 = 保持当前）')]):
            ttk.Label(fields,text=label).grid(row=row,column=0,sticky='w',pady=4)
            entry=ttk.Entry(fields,textvariable=self.values[key],width=16);entry.grid(row=row,column=1,padx=16);self.entries.append(entry)
        ttk.Label(frame,text='窗口大小需同时填写；建议保持当前已调好的大小。\n沿用六键长按、首音符重按及当前参数；不更改游戏 AUTO/难度。').pack(anchor='w',pady=8)
        buttons=ttk.Frame(frame);buttons.pack(fill='x')
        self.preview_toggle=ttk.Checkbutton(frame,text='显示实时识别窗口（开始前设置，不抢游戏焦点）',variable=self.show_recognition)
        self.preview_toggle.pack(anchor='w',pady=4)
        self.start=ttk.Button(buttons,text='开始循环',command=self.run);self.start.pack(side='left')
        self.stop=ttk.Button(buttons,text='停止并松开按键',command=self.cancel,state='disabled');self.stop.pack(side='left',padx=8)
        ttk.Button(buttons,text='打开日志',command=lambda:os.startfile(str(DATA))).pack(side='right')
        self.status=tk.StringVar(value='就绪（尚未操作游戏）');ttk.Label(frame,textvariable=self.status).pack(anchor='w',pady=8)
        self.diagnostic=tk.StringVar(value='诊断：等待启动（仅记录游戏窗口，最多4张门控截图/曲）')
        ttk.Label(frame,textvariable=self.diagnostic,wraplength=620).pack(anchor='w')
        self.log=tk.Text(frame,height=10,wrap='word');self.log.pack(fill='both',expand=True)
        import ctypes
        self.hotkey_api=ctypes.WinDLL('user32',use_last_error=True)
        self.hotkey_api.GetAsyncKeyState.argtypes=[ctypes.c_int];self.hotkey_api.GetAsyncKeyState.restype=ctypes.c_short
        self.hotkey_api.GetForegroundWindow.restype=ctypes.c_void_p
        self.hotkey_api.GetWindowTextW.argtypes=[ctypes.c_void_p,ctypes.c_wchar_p,ctypes.c_int]
        self.f8_down=bool(self.hotkey_api.GetAsyncKeyState(119)&0x8000)
        root.protocol('WM_DELETE_WINDOW',self.close);root.after(100,self.poll)

    def run(self,single_song=False):
        if self.process:return
        try:
            values={k:v.get().strip() for k,v in self.values.items()}
            rounds=int(values['rounds']);offset=float(values['offset']);snap=float(values['grid-snap']);w=int(values['window-width']);h=int(values['window-height'])
            if not (1<=rounds<=1000 and -500<=offset<=500 and 0<=snap<=25):raise ValueError('局数或延迟/吸附超出范围')
            if (w,h)!=(0,0) and not (640<=w<=7680 and 400<=h<=4320):raise ValueError('窗口需同时填宽高：640–7680 × 400–4320，或均为0')
            DATA.mkdir(parents=True,exist_ok=True)
            (DATA/'settings.json').write_text(json.dumps({**values,'recognition_preview':self.show_recognition.get()},ensure_ascii=False,indent=2),encoding='utf-8')
            self.stop_file=DATA/('stop-'+uuid.uuid4().hex)
            args=[sys.executable,'-X','utf8',str(ROOT/'tools/run_multi_live.py'),'--live','--stop-file',str(self.stop_file)]
            for k,v in values.items():args.extend(['--'+k,v])
            if single_song:args.extend(['--single-song','--rounds','1'])
            if self.show_recognition.get():args.append('--recognition-preview')
            self.process=subprocess.Popen(args,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW)
        except Exception as error:messagebox.showerror('无法启动',str(error));return
        self.start.configure(state='disabled');self.stop.configure(state='normal')
        self.preview_toggle.configure(state='disabled')
        for entry in self.entries:entry.configure(state='disabled')
        self.status.set('运行中；切走游戏会安全停止')
        process=self.process
        def read():
            for line in process.stdout:self.events.put(line)
            self.events.put(('exit',process.wait()))
        threading.Thread(target=read,daemon=True).start()

    def cancel(self):
        if self.process:
            self.stop_file.touch();self.status.set('正在停止，等待引擎松键和退出…');self.stop.configure(state='disabled')

    def close(self):
        if self.process:self.closing=True;self.cancel()
        else:self.root.destroy()

    def _game_foreground(self):
        import ctypes
        text=ctypes.create_unicode_buffer(256)
        self.hotkey_api.GetWindowTextW(self.hotkey_api.GetForegroundWindow(),text,len(text))
        return text.value.lower()=='hololive-dreams'

    def poll_hotkey(self):
        down=bool(self.hotkey_api.GetAsyncKeyState(119)&0x8000)
        if down and not self.f8_down and not self.process and not self.closing and self._game_foreground():self.run(single_song=True)
        self.f8_down=down

    def poll(self):
        self.poll_hotkey()
        while not self.events.empty():
            item=self.events.get()
            if isinstance(item,tuple):
                self.process=None;self.stop_file.unlink(missing_ok=True)
                self.status.set('已完成' if item[1]==0 else '已停止或遇到异常；请查看日志')
                self.start.configure(state='normal');self.stop.configure(state='disabled')
                self.preview_toggle.configure(state='normal')
                for entry in self.entries:entry.configure(state='normal')
                if self.closing:self.root.destroy();return
            else:
                if item.startswith('诊断：'):self.diagnostic.set(item.strip())
                self.log.insert('end',item);self.log.see('end')
                if int(self.log.index('end-1c').split('.')[0])>600:self.log.delete('1.0','150.0')
        self.root.after(100,self.poll)

if __name__=='__main__':
    root=tk.Tk();app=App(root)
    if '--self-test' in sys.argv:
        root.withdraw();root.update();root.destroy();print('GUI_SELF_TEST_OK')
    else:root.mainloop()
