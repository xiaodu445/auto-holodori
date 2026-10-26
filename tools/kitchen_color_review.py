"""Local color calibration and offline candidate export, no game input."""
import argparse
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import cv2
import numpy as np
from modular_agent.realtime.kitchen_color import detect,overlay,average_hsv


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--recording',type=Path)
    p.add_argument('--profile',type=Path,default=Path('runtime/kitchen/color-profile.json'))
    p.add_argument('--export',action='store_true')
    a=p.parse_args()
    if a.recording is None:
        dirs=sorted(Path('runtime/kitchen/recordings').glob('*/summary.json'))
        if not dirs:p.error('没有录像，请指定 --recording')
        a.recording=dirs[-1].parent
    stamps=json.loads((a.recording/'timestamps.json').read_text(encoding='utf-8'))
    if not stamps:p.error('录像没有帧')
    profile=json.loads(a.profile.read_text(encoding='utf-8')) if a.profile.exists() else dict(
        schema_version=1,roi=[.225,.19,.78,.80],classes={})
    profile.setdefault('average_kernel',5)
    cap=cv2.VideoCapture(str(a.recording/'screen.avi'))
    def frame(index):
        cap.set(cv2.CAP_PROP_POS_FRAMES,index);ok,img=cap.read()
        if not ok:raise RuntimeError(f'无法读取帧 {index}')
        return img
    if a.export:
        out=a.recording/'color-review';out.mkdir(exist_ok=True)
        report=[]
        try:
            for index in np.linspace(0,len(stamps)-1,24,dtype=int):
                image=frame(int(index));items,stats=detect(image,profile)
                cv2.imwrite(str(out/f'{index:06d}.jpg'),overlay(image,items,profile['roi']))
                report.append(dict(frame=int(index),t=stamps[index]['t'],candidates=items,stats=stats))
            (out/'candidates.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            (out/'profile.json').write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
            print(out.resolve())
        finally:cap.release()
        return
    root=tk.Tk();root.title('厨房颜色校准 — 离线录像，不发送游戏输入')
    row=ttk.Frame(root);row.pack(fill='x')
    ttk.Label(row,text='类别（建议英文ID）').pack(side='left')
    name=tk.StringVar(value=next(iter(profile['classes']),'chili'))
    entry=ttk.Combobox(row,textvariable=name,values=list(profile['classes']),width=22);entry.pack(side='left')
    status=tk.StringVar();ttk.Label(root,textvariable=status).pack(fill='x')
    canvas=tk.Canvas(root,width=1000,height=563);canvas.pack()
    state={};history=[]
    def show(value=None):
        index=int(float(slider.get()));image=frame(index)
        state['image']=image
        items,stats=detect(image,profile)
        annotated=overlay(image,items,profile['roi'])
        scale=min(1000/image.shape[1],600/image.shape[0]);state['scale']=scale
        small=cv2.resize(annotated,(round(image.shape[1]*scale),round(image.shape[0]*scale)))
        rgb=cv2.cvtColor(small,cv2.COLOR_BGR2RGB)
        photo=tk.PhotoImage(data=b'P6\n%d %d\n255\n'%(rgb.shape[1],rgb.shape[0])+rgb.tobytes(),format='PPM')
        canvas.configure(width=rgb.shape[1],height=rgb.shape[0]);canvas.delete('all')
        canvas.create_image(0,0,anchor='nw',image=photo);state['photo']=photo
        status.set(f'帧 {index} | {stamps[index]["t"]:.2f}s | {len(items)}个候选 | {stats["elapsed_ms"]:.1f}ms | 拖框平均采色，单击取邻域均值；同类可采多个颜色；候选不等于独立实例')
    slider=tk.Scale(root,from_=0,to=len(stamps)-1,orient='horizontal',length=1000)
    slider.set(min(range(len(stamps)),key=lambda i:abs(stamps[i]['t']-35)))
    slider.pack(fill='x');slider.bind('<ButtonRelease-1>',show)
    def begin_sample(event):
        state['drag_start']=(event.x,event.y)
        state['rectangle']=canvas.create_rectangle(event.x,event.y,event.x,event.y,outline='#00ffff',width=2)
    def drag_sample(event):
        if 'drag_start' in state:
            x,y=state['drag_start'];canvas.coords(state['rectangle'],x,y,event.x,event.y)
    def sample(event):
        start=state.pop('drag_start',None)
        if start is None:return
        canvas.delete(state.pop('rectangle',None))
        key=name.get().strip()
        if not key:return
        image=state['image'];scale=state['scale']
        h,w=image.shape[:2];l,t,r,b=profile['roi']
        sx,sy=start;ex,ey=event.x,event.y
        if abs(ex-sx)<4 and abs(ey-sy)<4:
            x,y=int(ex/scale),int(ey/scale);half=profile['average_kernel']//2
            x0,x1=x-half,x+half+1;y0,y1=y-half,y+half+1
        else:
            x0,x1=int(min(sx,ex)/scale),int(max(sx,ex)/scale)+1
            y0,y1=int(min(sy,ey)/scale),int(max(sy,ey)/scale)+1
        x0,x1=max(round(l*w),x0),min(round(r*w),x1)
        y0,y1=max(round(t*h),y0),min(round(b*h),y1)
        if x1<=x0 or y1<=y0:return
        center=average_hsv(image[y0:y1,x0:x1]).round(2).tolist()
        rule=profile['classes'].setdefault(key,dict(samples=[],tolerance=[6,55,65],min_area=20,min_radius=2))
        rule['samples'].append(center);history.append(key)
        entry.configure(values=list(profile['classes']));show()
        status.set(f'已加入 {key}：{x1-x0}×{y1-y0} 区域均值 HSV={center}；搜索使用 {profile["average_kernel"]}×{profile["average_kernel"]} 均值窗口')
    canvas.bind('<ButtonPress-1>',begin_sample)
    canvas.bind('<B1-Motion>',drag_sample)
    canvas.bind('<ButtonRelease-1>',sample)
    def save():
        a.profile.parent.mkdir(parents=True,exist_ok=True)
        a.profile.write_text(json.dumps(profile,ensure_ascii=False,indent=2),encoding='utf-8')
        status.set(f'已保存：{a.profile.resolve()}')
    def undo():
        if history:
            key=history.pop();profile['classes'][key]['samples'].pop()
            if not profile['classes'][key]['samples']:del profile['classes'][key]
            show()
    controls=ttk.Frame(root);controls.pack(fill='x')
    ttk.Button(controls,text='刷新当前帧',command=show).pack(side='left')
    ttk.Button(controls,text='撤销最近采色',command=undo).pack(side='left')
    ttk.Button(controls,text='保存颜色配置',command=save).pack(side='left')
    ttk.Label(controls,text='关闭前请保存。配置可编辑ROI、HSV容差、最小面积和半径。').pack(side='left')
    try:show();root.mainloop()
    finally:cap.release()


if __name__=='__main__':main()
