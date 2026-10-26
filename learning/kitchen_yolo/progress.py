"""Read-only training progress window, independent of the training process."""
import argparse
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk


def main():
    p=argparse.ArgumentParser();p.add_argument('--status',type=Path);p.add_argument('--smoke',action='store_true');a=p.parse_args()
    if a.status is None:
        latest=json.loads((Path(__file__).parent/'latest-run.json').read_text(encoding='utf-8'))
        a.status=Path(latest['status_file'])
    root=tk.Tk();root.title('厨房 YOLO 训练进度');root.geometry('690x320')
    title=tk.StringVar(value='正在准备训练…');ttk.Label(root,textvariable=title,font=('Microsoft YaHei UI',15)).pack(pady=15)
    total=ttk.Progressbar(root,length=620,maximum=100);total.pack(pady=8)
    detail=tk.StringVar();ttk.Label(root,textvariable=detail).pack(pady=5)
    metrics=tk.StringVar();ttk.Label(root,textvariable=metrics,wraplength=650,justify='left').pack(pady=12)
    directory=tk.StringVar();ttk.Label(root,textvariable=directory,wraplength=650).pack(pady=8)
    ttk.Label(root,text='关闭此窗口不会停止训练；训练日志和权重仍会保存。').pack(pady=5)
    phases={'preparing':'准备数据/模型','training':'训练中','validating':'验证中','completed':'训练完成','failed':'训练失败'}
    def poll():
        try:
            state=json.loads(a.status.read_text(encoding='utf-8'))
            epoch=state.get('epoch',0);epochs=state.get('epochs',150)
            title.set(f'{state.get("label","")} {phases.get(state.get("phase"),state.get("phase","准备中"))}  {epoch}/{epochs} 轮')
            total['value']=state.get('percent',0)
            elapsed=state.get('elapsed_seconds',0);eta=state.get('eta_seconds')
            detail.set(f'进度 {state.get("percent",0):.1f}%   已用 {elapsed/60:.1f} 分钟'+(f'   预计剩余 {eta/60:.1f} 分钟' if eta is not None else ''))
            values=state.get('metrics',{})
            lines=[f'{k}: {v:.4f}' for k,v in values.items() if isinstance(v,(int,float)) and ('mAP' in k or 'precision' in k or 'recall' in k)]
            losses=state.get('losses',{})
            text='  '.join(f'{k}: {v:.4f}' for k,v in losses.items())+'\n'+'  '.join(lines)
            if state.get('error'):text=state['error']
            metrics.set(text);directory.set(state.get('run_dir',''))
        except (OSError,ValueError):pass
        root.after(700,poll)
    poll()
    if a.smoke:root.after(200,root.destroy)
    root.mainloop()


if __name__=='__main__':main()
