"""Read-only per-round video, detections, planned/actual click timeline."""
import argparse,bisect,json,time,uuid
from collections import Counter
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
import cv2

ROOT=Path(__file__).resolve().parents[1]
from modular_agent.realtime.kitchen_diagnostics import snapshot
from modular_agent.realtime.kitchen_labels import atomic_json

CLASS_NAMES={c['id']:c['name'] for c in json.loads((ROOT/'data/kitchen/manual-classes.json').read_text(encoding='utf-8'))['classes']}

def tray_text(values):
    counts=Counter(c for c in values if c)
    return '、'.join(f"{CLASS_NAMES.get(c,'未知物品' if c=='?' else c)}×{n}" for c,n in counts.items()) or '空'

def event_lines(event):
    prefix=f"{event.get('t',0):.3f}秒 "
    kind=event['type']
    labels={'loop_menu_sent':'循环菜单点击已发送','loop_menu_preview':'循环菜单预览','loop_menu_retry_exhausted':'该页重试已达上限，继续观察','next_round_observed':'观察到下一局，切换回放','result_continue_sent':'点击做好啦页面继续','result_continue_preview':'预览：做好啦页面继续','order_continue_sent':'点击Order页下方继续，等待棋盘','order_continue_preview':'预览：Order页点击继续','order_targets':'从Order页读取指定食材','tray_visual_evidence':'更新槽位占用证据','tray_correction':'槽位结果已校正台账','group_cooldown':'本组三消已发送，等待后再点下一组','group_capacity_blocked':'实际槽位不足，停止旧队列并重新规划','session_start':'本局开始','scene_paused':'画面变化，暂停点击','scene_resumed':'画面恢复，继续观察','batch_planned':'生成本轮点击计划','batch_dispatched':'本轮点击发送完毕','batch_cooldown':'等待动画结束','batch_interval_elapsed':'等待结束，重新识别','tray_ledger':'更新暂存台账','tray_ledger_reset':'新菜谱，清空暂存台账','partial_batch_unconfirmed':'本轮点击提前中断（未确认实际结果）','preview_plan':'预览点击计划'}
    if kind=='click_sent':
        cls=event['item']['class_id']
        lines=[prefix+'点击了：'+CLASS_NAMES.get(cls,cls)]
    else:lines=[prefix+labels.get(kind,kind)]
    if event.get('logical_tray') is not None:
        lines.append('    点击后台账剩：' + tray_text(event['logical_tray']) if kind=='click_sent' else '    台账剩：'+tray_text(event['logical_tray']))
    if kind=='order_targets':lines.append('    指定食材：'+'、'.join(CLASS_NAMES.get(c,c) for c in event.get('targets',[])))
    if kind=='batch_dispatched':lines[0]+=f"（已发送{event.get('sent',0)}/计划{event.get('planned',event.get('sent',0))}次）"
    return lines


def latest_session(sessions):
    candidates=[]
    for manifest in Path(sessions).glob('*/manifest.json'):
        try:
            summary=json.loads((manifest.parent/'summary.json').read_text(encoding='utf-8'))
            stamps=json.loads((manifest.parent/'timestamps.json').read_text(encoding='utf-8'))
            if not stamps or not (manifest.parent/'screen.avi').is_file():continue
            candidates.append((summary.get('mode') in ('live','preview'),manifest.stat().st_mtime,str(manifest.parent)))
        except (OSError,ValueError):continue
    return Path(max(candidates)[2]) if candidates else None


def load_session(folder):
    folder=Path(folder);stamps=json.loads((folder/'timestamps.json').read_text(encoding='utf-8'))
    events=[json.loads(line) for line in (folder/'events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    times=[row['t'] for row in stamps]
    if not times or any(a>b for a,b in zip(times,times[1:])):raise ValueError('回放帧为空或时间戳不递增')
    detections=sorted((e for e in events if e['type']=='detection'),key=lambda e:e.get('t',e['observation']['finished']))
    return stamps,events,detections

class Replay:
    def __init__(self,root,folder):
        self.root=root;self.cap=None;self.after=None;self.playing=False;self.index=0
        root.title('厨房决策诊断回放 · 只读，不发送输入')
        top=ttk.Frame(root);top.pack(fill='x')
        ttk.Button(top,text='选择回放目录',command=self.choose).pack(side='left')
        ttk.Button(top,text='播放 / 暂停',command=self.toggle).pack(side='left')
        ttk.Button(top,text='前一帧',command=lambda:self.step(-1)).pack(side='left')
        ttk.Button(top,text='后一帧',command=lambda:self.step(1)).pack(side='left')
        self.speed=tk.StringVar(value='1');ttk.Combobox(top,textvariable=self.speed,values=['0.25','0.5','1','2'],width=6,state='readonly').pack(side='left')
        ttk.Label(top,text='倍速 | 黄色框：检测；红十字：模型点击点；蓝圈：计划；绿圈：实际发送').pack(side='left')
        body=ttk.Frame(root);body.pack(fill='both',expand=True)
        self.canvas=tk.Canvas(body,width=1100,height=620,highlightthickness=0);self.canvas.pack(side='left')
        tabs=ttk.Notebook(body);tabs.pack(side='left',fill='both',expand=True)
        detail=ttk.Frame(tabs);timeline=ttk.Frame(tabs);feedback=ttk.Frame(tabs)
        tabs.add(detail,text='状态与决策');tabs.add(timeline,text='点击日志');tabs.add(feedback,text='问题标记')
        self.detail=tk.Text(detail,width=57,height=34,wrap='word');self.detail.pack(side='left',fill='both',expand=True)
        detail_scroll=ttk.Scrollbar(detail,command=self.detail.yview);detail_scroll.pack(side='right',fill='y');self.detail.configure(yscrollcommand=detail_scroll.set)
        self.log=tk.Listbox(timeline,width=57,height=34);self.log.pack(fill='both',expand=True)
        ttk.Label(feedback,text='停在出问题的画面，填写期望行为后保存。').pack(anchor='w')
        self.issue_kind=tk.StringVar(value='应该点击但没点')
        ttk.Combobox(feedback,textvariable=self.issue_kind,state='readonly',values=['应该点击但没点','点击了不该点的物品','点击已发送但没有取走','台账与实际槽位不一致','过场误判或恢复过慢','识别漏检或类别错误','其他']).pack(fill='x')
        self.note=tk.Text(feedback,width=55,height=8,wrap='word');self.note.pack(fill='x')
        ttk.Button(feedback,text='保存当前帧问题＋截图',command=self.save_issue).pack(fill='x')
        self.issue_list=tk.Listbox(feedback,width=55,height=13);self.issue_list.pack(fill='both',expand=True)
        self.issue_list.bind('<<ListboxSelect>>',self.goto_issue)
        self.issue_status=tk.StringVar();ttk.Label(feedback,textvariable=self.issue_status,wraplength=420).pack(fill='x')
        self.tray_canvas=tk.Canvas(feedback,width=450,height=75,highlightthickness=0);self.tray_canvas.pack(fill='x')
        navigation=ttk.Frame(root);navigation.pack(fill='x')
        ttk.Button(navigation,text='上一决策',command=lambda:self.seek_decision(-1)).pack(side='left')
        ttk.Button(navigation,text='下一决策',command=lambda:self.seek_decision(1)).pack(side='left')
        ttk.Button(navigation,text='前1秒',command=lambda:self.seek_time(self.times[self.index]-1)).pack(side='left')
        ttk.Button(navigation,text='后1秒',command=lambda:self.seek_time(self.times[self.index]+1)).pack(side='left')
        ttk.Label(navigation,text='右侧可查看未点击原因，并保存问题帧；诊断不会发送输入。').pack(side='left')
        self.slider=tk.Scale(root,orient='horizontal',length=1100);self.slider.pack(fill='x');self.slider.bind('<ButtonRelease-1>',lambda event:self.slide(self.slider.get()))
        self.status=tk.StringVar();ttk.Label(root,textvariable=self.status).pack(fill='x')
        self.internal=False;self.open(folder);root.protocol('WM_DELETE_WINDOW',self.close)
    def choose(self):
        folder=filedialog.askdirectory(initialdir=str(ROOT/'runtime/kitchen/sessions'))
        if folder:
            try:self.open(folder)
            except Exception as error:messagebox.showerror('回放',str(error))
    def open(self,folder):
        stamps,events,detections=load_session(folder)
        capture=cv2.VideoCapture(str(Path(folder)/'screen.avi'))
        if not capture.isOpened():capture.release();raise ValueError('视频无法读取')
        self.pause()
        if self.cap:self.cap.release()
        self.folder=Path(folder);self.stamps=stamps;self.events=events;self.detections=detections;self.cap=capture
        self.issues_path=self.folder/'review-issues.json'
        self.issues=json.loads(self.issues_path.read_text(encoding='utf-8')) if self.issues_path.exists() else []
        self.refresh_issues()
        self.times=[s['t'] for s in stamps];self.detection_times=[e.get('t',e['observation']['finished']) for e in detections]
        self.internal=True;self.slider.configure(to=len(stamps)-1);self.slider.set(0);self.internal=False;self.draw(0)
    def slide(self,value):
        if self.internal:return
        self.pause();self.draw(int(float(value)))
    def pause(self):
        self.playing=False
        if self.after:self.root.after_cancel(self.after);self.after=None
    def step(self,delta):self.pause();self.draw(self.index+delta)
    def toggle(self):
        if self.playing:self.pause();return
        self.playing=True;self.started=time.perf_counter();self.start_time=self.times[self.index];self.tick()
    def tick(self):
        elapsed=(time.perf_counter()-self.started)*float(self.speed.get())
        index=min(len(self.times)-1,bisect.bisect_right(self.times,self.start_time+elapsed)-1)
        if index!=self.index:self.draw(index)
        if index>=len(self.times)-1:self.pause();return
        self.after=self.root.after(15,self.tick)
    def draw(self,index):
        index=max(0,min(index,len(self.stamps)-1));self.cap.set(cv2.CAP_PROP_POS_FRAMES,index);ok,image=self.cap.read()
        if not ok:raise ValueError('回放视频帧缺失')
        self.index=index;self.current_image=image.copy();t=self.times[index];h,w=image.shape[:2];scale=min(940/w,550/h)
        small=cv2.resize(image,(round(w*scale),round(h*scale)));rgb=cv2.cvtColor(small,cv2.COLOR_BGR2RGB)
        self.photo=tk.PhotoImage(data=b'P6\n%d %d\n255\n'%(rgb.shape[1],rgb.shape[0])+rgb.tobytes(),format='PPM')
        c=self.canvas;c.delete('all');c.configure(width=small.shape[1],height=small.shape[0]);c.create_image(0,0,anchor='nw',image=self.photo)
        di=bisect.bisect_right(self.detection_times,t)-1;age=None
        if di>=0:
            observation=self.detections[di]['observation'];age=t-observation['captured']
            for p in observation['items']:
                c.create_rectangle(*[v*scale for v in p['bbox']],outline='#ffe600')
                x,y=p['x']*scale,p['y']*scale;c.create_line(x-5,y,x+5,y,fill='red' if p.get('point_source','keypoint')=='keypoint' else '#ff9500',width=2);c.create_line(x,y-5,x,y+5,fill='red' if p.get('point_source','keypoint')=='keypoint' else '#ff9500',width=2)
                c.create_text(x+5,y-5,text=f'{CLASS_NAMES.get(p["class_id"],p["class_id"])} {p["score"]:.2f}',fill='#ffe600',anchor='sw')
        if di>=0:
            hud=self.detections[di]['observation'];c.create_text(8,8,anchor='nw',fill='#00ff80',text='画面识别槽位：'+tray_text(hud.get('tray',[]))+' | 指定食材：'+ '、'.join(CLASS_NAMES.get(v,v) for v in hud.get('targets',[])))
        visible=[e for e in self.events if e.get('t',0)<=t and e['type'] not in ('detection','decision')];self.log.delete(0,'end')
        for e in visible[-24:]:
            for line in event_lines(e):self.log.insert('end',line)
            if t-e.get('t',0)<=.25:
                points=[e['item']] if e['type']=='click_sent' else e.get('items',[]) if e['type'] in ('preview_plan','batch_planned') else []
                for p in points:
                    x,y=p['x']*scale,p['y']*scale;c.create_oval(x-9,y-9,x+9,y+9,outline='#00ff60' if e['type']=='click_sent' else '#00bfff',width=3)
        self.internal=True;self.slider.set(index);self.internal=False
        self.render_diagnostics(t,image)
        self.status.set(f'{self.folder.name} | 帧 {index+1}/{len(self.stamps)} | 实际采集时间 {t:.3f}s | 检测画面年龄 {age if age is not None else "无"} | 台账按已发送点击推算，不代表实际消除成功')
    def seek_time(self,t):
        self.pause();self.draw(max(0,min(len(self.times)-1,bisect.bisect_left(self.times,t))))
    def seek_decision(self,direction):
        times=sorted(set(e.get('t',0) for e in self.events if e['type'] in ('decision','batch_planned','tray_ledger','scene_paused')))
        now=self.times[self.index]
        candidates=[t for t in times if t>now+.001] if direction>0 else [t for t in times if t<now-.001]
        if candidates:self.seek_time(candidates[0] if direction>0 else candidates[-1])
    def refresh_issues(self):
        self.issue_list.delete(0,'end')
        for issue in self.issues:self.issue_list.insert('end',f"帧{issue['frame_index']+1} | {issue['time']:.2f}秒 | {issue['kind']}")
    def goto_issue(self,event=None):
        selected=self.issue_list.curselection()
        if selected:
            issue=self.issues[selected[0]];self.pause();self.draw(issue['frame_index'])
            self.note.delete('1.0','end');self.note.insert('1.0',issue['note']);self.issue_kind.set(issue['kind'])
    def save_issue(self):
        self.pause();ident=uuid.uuid4().hex[:10];folder=self.folder/'review';folder.mkdir(exist_ok=True)
        name=f'frame-{self.index:06d}-{ident}.png'
        if not cv2.imwrite(str(folder/name),self.current_image):messagebox.showerror('保存失败','无法保存截图');return
        issue=dict(id=ident,session=self.folder.name,frame_index=self.index,time=self.times[self.index],kind=self.issue_kind.get(),note=self.note.get('1.0','end').strip(),screenshot='review/'+name,diagnosis=self.current_diagnosis)
        self.issues.append(issue);atomic_json(self.issues_path,self.issues);self.refresh_issues()
        self.issue_status.set('已保存：'+str(self.issues_path));self.status.set('问题帧已保存，告诉我录像名称和标记序号即可。')
    def render_diagnostics(self,t,image):
        state=snapshot(self.events,t);self.current_diagnosis=state
        settings=state['settings'];logical=state['logical_tray'];ob=state['observation'];last=state['last_click']
        lines=[f"录像：{self.folder.name}",f"当前：帧{self.index+1}，{t:.3f}秒",'台账是点击投影；槽位视觉也可能错误。','', '当前台账：'+('尚未记录' if logical is None else tray_text(logical))]
        reading=state['slot_reading'];correction=state['slot_correction']
        lines+=['','最近槽位实测（独立于点击推算）：']
        if reading:
            packet=reading['evidence'];captured=packet['captured']
            lines.append(f"采集{captured:.3f}秒；距当前{t-captured:.3f}秒；来源帧{packet.get('frame_id','未知')}")
            lines.append('实测七格：'+' | '.join(f"{i+1}:{CLASS_NAMES.get(row['value'],row['value']) if row['value'] not in ('','?') else '空' if row['value']=='' else '占用（未分类）' if row.get('classified') is False else '未知'}" for i,row in enumerate(packet.get('slots',[]))))
            lines.append(f"实测占用：{packet.get('occupied_count','未知')}/7；N−3前缀："+tray_text(packet.get('prefix',[])))
        else:lines.append('尚无独立槽位读取记录（旧录像可能未记录）。')
        if correction:
            rule='全槽替换' if correction.get('rule')=='full_slots' else 'N−3前缀替换'
            lines.append(f"最近台账校正：{correction['t']:.3f}秒；{rule}")
            lines.append('校正前：'+tray_text(correction.get('before',[])))
            lines.append('校正后：'+tray_text(correction.get('logical_tray',[])))
        else:lines.append('尚无改变台账的槽位校正记录。')
        if logical is not None:
            occupied=sum(bool(c) for c in logical);reserve=settings.get('reserve_slots',3)
            lines.append(f'占用{occupied}/7，空位{7-occupied}，预留{reserve}，可探索余量{max(0,7-occupied-reserve)}')
        if last:
            lines.append(f"最后点击：{CLASS_NAMES.get(last['item']['class_id'],last['item']['class_id'])}，{last['t']:.3f}秒")
            lines.append(f"距上次点击{t-last['t']:.3f}秒；冷却剩余{max(0,last['t']+settings.get('batch_interval',.5)-t):.3f}秒")
        page=state['page_event']
        if page:lines.append('最近页面事件：'+('暂停' if page['type']=='scene_paused' else '恢复')+f"（{page['t']:.3f}秒，可能已过时）")
        if ob:
            lines+=['','检测来源帧：'+str(ob['frame_id'])+f"；采集{ob['captured']:.3f}秒，完成{ob['finished']:.3f}秒",f"推理耗时{(ob['finished']-ob['captured'])*1000:.1f}ms；当前画面年龄{t-ob['captured']:.3f}秒",'槽位视觉（该检测帧）：'+tray_text(ob.get('tray',[])),'决策所用台账：'+tray_text(state['decision_tray'] or []),'指定类别：'+'、'.join(CLASS_NAMES.get(c,c) for c in state.get('targets',[])),f"置信度门槛：{settings.get('confidence','未知')}",'',state['source']]
            dynamic=state.get('confidence_policy')
            if dynamic:
                lines.append(f"当轮动态门槛：{dynamic['threshold']:.3f}（正常{dynamic.get('base',0):.3f}）")
                lines.append(f"输入：空槽{dynamic.get('free','未知')}、可见{dynamic.get('visible','未知')}、候选{dynamic.get('candidates','未知')}、上轮点击{dynamic.get('last_clicks','未知')}")
                lines.append('调整原因：'+dynamic.get('reason','未知'))
            info=ob.get('ui_details') or {}
            if not dynamic and 'tail_confidence' in info:
                normal=settings.get('confidence',.25);high=sum(p['score']>=normal for p in ob['items'])
                active=settings.get('exploratory',True) and high<=2 and 0<len(ob['items'])<=6
                lines.append(f"残局补检：{'启用低门槛' if active and info['tail_confidence']<normal else '保持正常门槛'}；候选门槛{info['tail_confidence']}；后端{info.get('inference_backend','未知')}")
            counts=Counter(p['class_id'] for p in ob['items'])
            lines.append('检测数量：'+'、'.join(CLASS_NAMES.get(c,c)+'×'+str(n) for c,n in counts.items()))
            recorded=[e for e in self.events if e.get('t',0)<=t and e.get('frame_id')==ob['frame_id']]
            actual_plan=next((e for e in reversed(recorded) if e['type']=='batch_planned'),None)
            delivered=[e for e in recorded if e['type']=='click_sent']
            lines.append(f"该检测帧记录：计划{len(actual_plan['items']) if actual_plan else 0}次，已发送{len(delivered)}次（不等于取走）")
            for row in state['trace']:
                name=CLASS_NAMES.get(row['class_id'],row['class_id'])
                lines.append(f"{'✓ 选中' if row['selected'] else '· 未选'} {name} {row['score']:.2f} [{row['instance_id']}]：{row['reason']}")
        else:lines.append('尚无完成的模型检测。')
        lines+=['','模型：'+str(state['model']),'注意：识别、规划选中、实际发送、游戏取走是四件不同的事。']
        self.detail.configure(state='normal');self.detail.delete('1.0','end');self.detail.insert('1.0','\n'.join(lines));self.detail.configure(state='disabled')
        h,w=image.shape[:2];crop=image[round(h*.86):round(h*.99),round(w*.20):round(w*.81)]
        strip=cv2.resize(crop,(450,65));rgb=cv2.cvtColor(strip,cv2.COLOR_BGR2RGB)
        self.tray_photo=tk.PhotoImage(data=b'P6\n450 65\n255\n'+rgb.tobytes(),format='PPM')
        self.tray_canvas.delete('all');self.tray_canvas.create_image(0,10,anchor='nw',image=self.tray_photo)
        self.tray_canvas.create_text(2,0,anchor='nw',text='当前录像里的实际槽位（请人工核对）')

    def close(self):
        self.pause()
        if self.cap:self.cap.release()
        self.root.destroy()

def main():
    p=argparse.ArgumentParser();p.add_argument('folder',nargs='?',type=Path);a=p.parse_args()
    if not a.folder:
        latest=latest_session(ROOT/'runtime/kitchen/sessions')
        if latest:a.folder=latest
        else:
            chooser=tk.Tk();chooser.withdraw();value=filedialog.askdirectory(title='选择包含 manifest.json 的本局回放目录');chooser.destroy()
            if not value:return
            a.folder=Path(value)
    root=tk.Tk()
    try:Replay(root,a.folder)
    except Exception as error:
        root.withdraw();messagebox.showerror('回放无法打开',str(error)+'\n目录：'+str(a.folder));root.destroy();return
    root.mainloop()

if __name__=='__main__':main()
