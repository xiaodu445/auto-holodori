"""Local launcher for a manually-started round; no input from this UI."""
import json,os,subprocess,time,uuid
from pathlib import Path
import tkinter as tk
from tkinter import ttk,messagebox
from modular_agent.realtime.kitchen_policy import POLICY_FIELDS
from modular_agent.realtime.kitchen_match import Settings
ROOT=Path(__file__).resolve().parents[1]

class Control:
    def __init__(self,root):
        self.root=root;self.process=None;self.poll=None;self.log=None;self.session_path=None;self.replay_after_stop=False
        root.title('厨房三消 · 本局控制')
        profile=json.loads((ROOT/'data/kitchen/runtime-profile.json').read_text(encoding='utf-8'))
        ttk.Label(root,text='模型：'+profile['weights'],wraplength=730).pack(anchor='w',padx=12,pady=8)
        ttk.Label(root,text='先手动进入厨房棋盘，开始后5秒内切回游戏。').pack(anchor='w',padx=12)
        ttk.Label(root,text='当前策略：维护点击台账，优先补齐已有配对，再指定食材和探索取物。').pack(anchor='w',padx=12,pady=8)
        self.preferences_path=ROOT/'runtime/kitchen/control/preferences.json'
        try:self.preferences=json.loads(self.preferences_path.read_text(encoding='utf-8'))
        except (OSError,ValueError):self.preferences={}
        if not isinstance(self.preferences,dict):self.preferences={}
        self.policy_vars={name:tk.StringVar(value=str(self.preferences.get(name,default))) for name,_,default,*_ in POLICY_FIELDS}
        modes=ttk.Frame(root);modes.pack(fill='x',padx=12)
        self.mode=tk.StringVar(value=self.preferences.get('mode','live'))
        ttk.Radiobutton(modes,text='只预览，不点击',value='preview',variable=self.mode).pack(side='left')
        ttk.Radiobutton(modes,text='实际点击',value='live',variable=self.mode).pack(side='left')
        ttk.Label(modes,text='点击间隔 ms：').pack(side='left')
        self.interval=tk.StringVar(value=str(self.preferences.get('interval','40')));ttk.Entry(modes,textvariable=self.interval,width=6).pack(side='left')
        gap=ttk.Frame(root);gap.pack(fill='x',padx=12,pady=4)
        ttk.Label(gap,text='末次点击后等待 秒：').pack(side='left')
        self.batch_interval=tk.StringVar(value=str(self.preferences.get('batch_interval','0.5')));ttk.Entry(gap,textvariable=self.batch_interval,width=6).pack(side='left')
        ttk.Label(gap,text='最后一次点击后计时；等待结束即重新识别').pack(side='left')
        reserve_row=ttk.Frame(root);reserve_row.pack(fill='x',padx=12,pady=4)
        ttk.Label(reserve_row,text='预留空槽：').pack(side='left')
        preferred=self.preferences.get('reserve_slots',profile.get('reserve_slots',3))
        self.reserve_slots=tk.StringVar(value=str(preferred))
        ttk.Spinbox(reserve_row,from_=1,to=6,textvariable=self.reserve_slots,width=4).pack(side='left')
        ttk.Label(reserve_row,text='1～6格；补齐配对优先，完整三消按三件连续点击').pack(side='left')
        limit_row=ttk.Frame(root);limit_row.pack(fill='x',padx=12,pady=4)
        ttk.Label(limit_row,text='每轮最多点击数：').pack(side='left')
        self.max_batch_clicks=tk.StringVar(value=str(self.preferences.get('max_batch_clicks',6)))
        ttk.Spinbox(limit_row,from_=3,to=300,textvariable=self.max_batch_clicks,width=5).pack(side='left')
        ttk.Label(limit_row,text='3～300；按完整三消/补齐组合安排，点完等待后重新识别').pack(side='left')
        tail_row=ttk.Frame(root);tail_row.pack(fill='x',padx=12,pady=4)
        ttk.Label(tail_row,text='残局补检置信度：').pack(side='left')
        self.tail_confidence=tk.StringVar(value=str(self.preferences.get('tail_confidence',.12)))
        ttk.Entry(tail_row,textvariable=self.tail_confidence,width=6).pack(side='left')
        ttk.Label(tail_row,text='最低候选门槛；0关闭降门槛；高级参数可调正常值').pack(side='left')
        self.adaptive_confidence=tk.BooleanVar(value=self.preferences.get('adaptive_confidence',True))
        self.enhanced_tail=tk.BooleanVar(value=self.preferences.get('enhanced_tail',True))
        policy_row=ttk.Frame(root);policy_row.pack(fill='x',padx=12,pady=4)
        ttk.Checkbutton(policy_row,text='动态置信度',variable=self.adaptive_confidence).pack(side='left')
        ttk.Checkbutton(policy_row,text='强化残局（空槽优先）',variable=self.enhanced_tail).pack(side='left')
        ttk.Button(policy_row,text='高级策略参数…',command=self.policy_dialog).pack(side='left',padx=8)
        self.only_targets=tk.BooleanVar(value=self.preferences.get('only_targets',False))
        ttk.Checkbutton(root,text='只点击指定食材（含单件取物；未识别目标时不点）',variable=self.only_targets).pack(anchor='w',padx=12,pady=4)
        self.exploratory=tk.BooleanVar(value=self.preferences.get('exploratory',True))
        ttk.Checkbutton(root,text='保守取物（通常按预留值；残局可逐件清场，至少留1格）',variable=self.exploratory).pack(anchor='w',padx=12,pady=4)
        self.tray_vision=tk.BooleanVar(value=self.preferences.get('tray_vision',True))
        ttk.Checkbutton(root,text='槽位视觉反馈（轮末占用数减3，修正台账）',variable=self.tray_vision).pack(anchor='w',padx=12,pady=4)
        self.loop=tk.BooleanVar(value=self.preferences.get('loop',True))
        ttk.Checkbutton(root,text='自动循环（结算后继续游玩；无总时长限制）',variable=self.loop).pack(anchor='w',padx=12,pady=4)
        buttons=ttk.Frame(root);buttons.pack(fill='x',padx=12,pady=8)
        self.start_button=ttk.Button(buttons,text='开始本局',command=self.start);self.start_button.pack(side='left')
        self.stop_button=ttk.Button(buttons,text='停止并保存回放',command=self.stop,state='disabled');self.stop_button.pack(side='left')
        ttk.Button(buttons,text='打开最近回放',command=self.replay).pack(side='left')
        ttk.Button(buttons,text='打开录像目录',command=lambda:os.startfile(str(ROOT/'runtime/kitchen/sessions'))).pack(side='left')
        self.status=tk.StringVar(value='F12、失焦、窗口移动会停止。自动识别槽位与顶部图标；未知图标不当空槽。动画后自动继续。')
        ttk.Label(root,textvariable=self.status,wraplength=730).pack(anchor='w',padx=12,pady=8)
        root.protocol('WM_DELETE_WINDOW',self.close)
    def policy_dialog(self):
        dialog=tk.Toplevel(self.root);dialog.title('厨房高级策略参数（自动记住）')
        ttk.Label(dialog,text='空槽是硬门槛；权重仅在安全空槽足够时生效。修改后下一次开始本局生效。',wraplength=630).grid(row=0,column=0,columnspan=2,padx=12,pady=8)
        for row,(name,label,default,kind,low,high) in enumerate(POLICY_FIELDS,1):
            ttk.Label(dialog,text=f'{label}（{low}～{high}）').grid(row=row,column=0,sticky='w',padx=12,pady=3)
            ttk.Entry(dialog,textvariable=self.policy_vars[name],width=12).grid(row=row,column=1,padx=12,pady=3)
        ttk.Button(dialog,text='保存并关闭',command=lambda:(self.save_preferences(),dialog.destroy())).grid(row=len(POLICY_FIELDS)+1,column=0,columnspan=2,pady=10)
    def save_preferences(self):
        path=getattr(self,'preferences_path',ROOT/'runtime/kitchen/control/preferences.json')
        values=dict(getattr(self,'preferences',{}))
        for name in ('mode','interval','batch_interval','reserve_slots','max_batch_clicks','tail_confidence','loop','adaptive_confidence','enhanced_tail','only_targets','exploratory','tray_vision'):
            variable=getattr(self,name,None)
            if variable is not None:values[name]=variable.get()
        values.update({name:variable.get() for name,variable in getattr(self,'policy_vars',{}).items()})
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix('.tmp')
        temporary.write_text(json.dumps(values,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(path);self.preferences=values
    def start(self):
        if self.process:return
        targets=[]
        try:interval=float(self.interval.get());assert .1<=interval<=1000
        except (ValueError,AssertionError):messagebox.showerror('间隔','请输入0.1～1000毫秒。');return
        try:batch_interval=float(self.batch_interval.get());assert .05<=batch_interval<=60
        except (ValueError,AssertionError):messagebox.showerror('批次间隔','请输入0.05～60秒。');return
        try:
            reserve=int(self.reserve_slots.get()) if hasattr(self,'reserve_slots') else 3
            assert 1<=reserve<=6
        except (ValueError,AssertionError):messagebox.showerror('预留空槽','请输入1～6的整数。');return
        try:
            max_clicks=int(self.max_batch_clicks.get()) if hasattr(self,'max_batch_clicks') else 6
            assert 3<=max_clicks<=300
        except (ValueError,AssertionError):messagebox.showerror('每轮点击数','请输入3～300的整数。');return
        try:
            policy_values={name:kind(self.policy_vars[name].get()) if hasattr(self,'policy_vars') else default for name,_,default,kind,_,_ in POLICY_FIELDS}
            Settings(**policy_values)
        except (ValueError,TypeError) as error:messagebox.showerror('策略参数',str(error));return
        try:
            tail_confidence=float(self.tail_confidence.get()) if hasattr(self,'tail_confidence') else .12
            assert 0<=tail_confidence<=policy_values['confidence']
        except (ValueError,AssertionError):messagebox.showerror('残局补检','请输入0～正常置信度，0关闭。');return
        folder=ROOT/'runtime/kitchen/control';folder.mkdir(parents=True,exist_ok=True);name=time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]
        self.save_preferences()
        self.stop_path=folder/(name+'.stop');self.log_path=folder/(name+'.log')
        self.session_path=ROOT/'runtime/kitchen/sessions'/name
        args=[str(ROOT/'learning/jump_rope_yolo/.venv/Scripts/python.exe'),'-m','modular_agent.realtime.kitchen_play','--targets',','.join(targets),'--interval-ms',str(interval),'--batch-interval',str(batch_interval),'--reserve-slots',str(reserve),'--max-batch-clicks',str(max_clicks),'--tail-confidence',str(tail_confidence),'--stop-file',str(self.stop_path),'--output',str(self.session_path)]
        for name,value in policy_values.items():args.extend(['--'+name.replace('_','-'),str(value)])
        if hasattr(self,'adaptive_confidence') and not self.adaptive_confidence.get():args.append('--no-adaptive-confidence')
        if hasattr(self,'enhanced_tail') and not self.enhanced_tail.get():args.append('--no-enhanced-tail')
        if hasattr(self,'loop') and not self.loop.get():args.append('--no-loop')
        if not self.tray_vision.get():args.append('--no-tray-vision')
        if not self.exploratory.get():args.append('--no-exploration')
        if hasattr(self,'only_targets') and self.only_targets.get():args.append('--only-targets')
        if self.mode.get()=='live':args.append('--live')
        env={**os.environ,'PYTHONPATH':str(ROOT/'src'),'PYTHONIOENCODING':'utf-8'}
        log=self.log_path.open('w',encoding='utf-8')
        try:self.process=subprocess.Popen(args,cwd=str(ROOT),env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=0x08000000)
        except OSError as error:messagebox.showerror('启动失败',str(error));return
        finally:log.close()
        self.start_button.configure(state='disabled');self.stop_button.configure(state='normal')
        self.status.set('正在加载模型，随后倒计时5秒；请切回厨房窗口。');self.poll=self.root.after(500,self.check)
    def check(self):
        self.poll=None
        if not self.process:return
        try:
            lines=self.log_path.read_text(encoding='utf-8',errors='replace').splitlines()
            if lines:self.status.set('\n'.join(lines[-2:]))
        except OSError:pass
        if self.process.poll() is None:self.poll=self.root.after(500,self.check)
        else:
            self.process=None;self.start_button.configure(state='normal');self.stop_button.configure(state='disabled')
            if self.replay_after_stop:
                self.replay_after_stop=False;self.replay()
    def stop(self):
        if self.process:self.stop_path.write_text('stop',encoding='utf-8');self.status.set('已请求停止，正在保存本局回放。')
    def replay(self):
        if self.process and self.process.poll() is None:
            self.replay_after_stop=True;self.stop();self.status.set('先停止并保存本局，保存完成后自动打开回放。');return
        command=[str(ROOT/'.conda/pythonw.exe'),str(ROOT/'tools/kitchen_replay.py')]
        replay_path=self.session_path
        if replay_path and (replay_path/'loop-index.json').exists():
            try:replay_path=Path(json.loads((replay_path/'loop-index.json').read_text())['latest_session'])
            except (OSError,ValueError,KeyError):pass
        if replay_path and (replay_path/'manifest.json').exists():command.append(str(replay_path))
        subprocess.Popen(command,cwd=str(ROOT),creationflags=0x08000000)
    def close(self):
        self.save_preferences()
        self.stop()
        if self.poll:self.root.after_cancel(self.poll)
        self.root.destroy()

def main():
    root=tk.Tk();Control(root);root.mainloop()

if __name__=='__main__':main()
