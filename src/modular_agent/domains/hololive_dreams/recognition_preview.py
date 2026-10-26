"""Live recognition view: existing frames only, latest-only nonactivating window."""
import time

def render_recognition(image,observation,decision,config,fps):
    import cv2,numpy as np
    canvas=image.copy();h,w=canvas.shape[:2]
    for note in observation.get('notes',[]):
        x,y=note['center'];bw,bh=note['width'],note['height']
        cv2.rectangle(canvas,(round((x-bw/2)*w),round((y-bh/2)*h)),
            (round((x+bw/2)*w),round((y+bh/2)*h)),(0,255,255),2)
    if decision.get('gate_ready'):
        y=round(config.get('hit_line_y',.806)*h);cv2.line(canvas,(0,y),(w-1,y),(0,200,255),1)
    panel=np.zeros((125,w,3),np.uint8)
    lines=[f"state={decision.get('gate_state')} HUD={decision.get('hud')} gate={decision.get('gate_ready')}",
        f"captured={decision.get('captured_frames',0)} empty={decision.get('empty_frames',0)} processed={decision.get('processed_frames',0)}",
        f"notes={len(observation.get('notes',[]))} keys={','.join(decision.get('keys',[])) or '-'} edges={decision.get('input_edges',0)} failures={decision.get('failed_input_edges',0)}",
        'blocked='+str(decision.get('inhibited') or '-')+' | F12 stops; keep game foreground',
        'yellow boxes=recognized notes | source=existing capture; view <=10Hz']
    for i,line in enumerate(lines):cv2.putText(panel,line,(8,20+i*23),cv2.FONT_HERSHEY_SIMPLEX,.45,(235,235,235),1)
    return np.concatenate((canvas,panel),axis=0)

class RecognitionPreview:
    def __init__(self,config,*,factory=None,clock=time.monotonic):
        if factory is None:
            from modular_agent.realtime.jump_rope_preview import Preview
            factory=Preview
        self.display=factory(config,renderer=render_recognition,title='Hololive - Live recognition (F12 stops)')
        self.clock=clock;self.last=-float('inf');self.error=None
    def publish(self,image,bounds,snapshot,notes=()):
        if self.error or self.display.stop.is_set():return
        now=self.clock()
        if now-self.last<.1:return
        self.last=now
        try:
            entries=[dict(n) if isinstance(n,dict) else dict(n.__dict__) for n in notes]
            self.display.publish(image,{'notes':entries},dict(snapshot),bounds,0.)
        except Exception as error:self.error=str(error)
    def close(self):self.display.close()
