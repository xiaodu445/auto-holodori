"""Bounded observational diagnostics; never performs input or extra capture."""
import time,threading
from pathlib import Path

class SongDiagnostics:
    def __init__(self,*,emit=lambda *a,**k:None,progress=lambda _:None,directory=None,clock=time.monotonic,preview=None):
        self.emit=emit;self.progress=progress;self.directory=Path(directory) if directory else None
        self.clock=clock;self.started=clock();self.last=-float('inf');self.gate=None
        self.processed=0;self.edges=0;self.failed_edges=0;self.notes=0;self.keys=[];self.inhibited=None
        self.saved=0;self.next_image=0.;self.errors=[];self.lock=threading.RLock()
        self.preview=preview
        self.last_image=None
    def safe(self,callback,*args,**kwargs):
        try:return callback(*args,**kwargs)
        except Exception as error:
            if len(self.errors)<5:self.errors.append(str(error))
    def input_edge(self,event):
        self.edges+=1
        if not event.get('success'):self.failed_edges+=1
        if self.edges<=12 or (not event.get('success') and self.failed_edges<=12):self.safe(self.emit,'rhythm_input_edge',**event)
    def frame(self,image,stamp,bounds,notes,tracks,decision,keys,*args):
        self.last_image=image
        self.processed+=1;self.notes=len(notes);self.keys=list(keys);self.inhibited=decision.get('inhibited')
        if self.preview:self.safe(self.preview.publish,image,bounds,self.snapshot(),notes)
    def snapshot(self):
        gate=self.gate
        return dict(elapsed=round(self.clock()-self.started,1),processed_frames=self.processed,
            input_edges=self.edges,failed_input_edges=self.failed_edges,notes=self.notes,keys=self.keys,
            inhibited=self.inhibited,gate_ready=gate.ready if gate else None,
            captured_frames=getattr(gate,'diag_frames',0),empty_frames=getattr(gate,'diag_empty',0),
            gate_state=getattr(gate,'diag_state','initializing'),hud=getattr(gate,'diag_hud',None),
            hud_stable=getattr(gate,'stable',0),capture_stats=dict(gate.stats) if gate else {},diagnostic_errors=list(self.errors))
    def check(self):
        now=self.clock()
        if now-self.last<2:return
        with self.lock:
            if now-self.last<2:return
            self.last=now;data=self.snapshot()
            self.safe(self.emit,'rhythm_diagnostic',**data)
            text=('诊断：采集帧={captured_frames} 空帧={empty_frames} 门控={gate_ready} '
                  '页面={gate_state} HUD={hud} 连续={hud_stable} 处理帧={processed_frames} '
                  '输入边沿={input_edges} 失败={failed_input_edges}').format(**data)
            self.safe(self.progress,text)
    def image(self,image):
        self.last_image=image
        now=self.clock()-self.started
        if self.directory is None or self.saved>=4 or now<self.next_image:return
        self.saved+=1;self.next_image=now+10
        def save():
            import cv2
            self.directory.mkdir(parents=True,exist_ok=True)
            path=self.directory/f'gate-{self.saved:02d}.jpg'
            small=cv2.resize(image,(min(640,image.shape[1]),max(1,round(image.shape[0]*min(640,image.shape[1])/image.shape[1]))))
            ok,encoded=cv2.imencode('.jpg',small,[cv2.IMWRITE_JPEG_QUALITY,70])
            if not ok:raise RuntimeError('diagnostic PNG encoding failed')
            encoded.tofile(path)
            self.emit('rhythm_gate_image',path=str(path),state=self.gate.diag_state,hud=self.gate.diag_hud)
        self.safe(save)
    def finish(self,result):
        from .rhythm_journal import compact_result
        data={**self.snapshot(),'result':compact_result(result)}
        if self.directory and self.last_image is not None and result.get('stop_reason')!='settlement_observed':
            def save_failure():
                import cv2
                self.directory.mkdir(parents=True,exist_ok=True)
                path=self.directory/'stopped-frame.jpg'
                image=self.last_image;width=min(960,image.shape[1])
                image=cv2.resize(image,(width,max(1,round(image.shape[0]*width/image.shape[1]))))
                cv2.imencode('.jpg',image,[cv2.IMWRITE_JPEG_QUALITY,80])[1].tofile(path)
            self.safe(save_failure)
        self.safe(self.emit,'rhythm_diagnostic_summary',**data)
        if self.directory:
            def save():
                import json
                self.directory.mkdir(parents=True,exist_ok=True)
                (self.directory/'summary.json').write_text(json.dumps(data,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
            self.safe(save)
