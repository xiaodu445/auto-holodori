"""Per-round replay: reuse the bounded latest-frame encoder queue pattern."""
import json,queue,threading,time
from pathlib import Path
import cv2
from modular_agent.realtime.frame_queue import offer_latest

class SessionRecorder:
    def __init__(self,output,fps=30):
        self.output=Path(output);self.output.mkdir(parents=True,exist_ok=False)
        self.fps=fps;self.queue=queue.Queue(8);self.thread=None;self.writer=None
        self.rows=[];self.events=[];self.errors=[];self.dropped=0;self.closed=False;self.lock=threading.Lock()
        self.stream=(self.output/'events.jsonl').open('w',encoding='utf-8')
    def event(self,kind,**data):
        with self.lock:
            if self.closed:return
            row=dict(type=kind,**data);self.stream.write(json.dumps(row,ensure_ascii=False)+'\n');self.stream.flush();self.events.append(row)
    def frame(self,image,frame_id,t,bounds=()):
        if self.closed:raise RuntimeError('recorder closed')
        if self.errors:raise RuntimeError('replay_encoder_failed: '+self.errors[0])
        if self.writer is None:
            h,w=image.shape[:2];self.size=(w,h)
            self.writer=cv2.VideoWriter(str(self.output/'screen.avi'),cv2.VideoWriter_fourcc(*'MJPG'),self.fps,self.size)
            if not self.writer.isOpened():raise RuntimeError('replay_encoder_unavailable')
            self.thread=threading.Thread(target=self.encode,daemon=True);self.thread.start()
        if image.shape[1::-1]!=self.size:raise RuntimeError('recording_size_changed')
        self.dropped+=offer_latest(self.queue,(image.copy(),dict(frame_id=frame_id,t=t,client_bounds=list(bounds))))
    def encode(self):
        try:
            while True:
                entry=self.queue.get()
                if entry is None:break
                image,row=entry;self.writer.write(image);row['video_index']=len(self.rows);self.rows.append(row)
        except Exception as error:self.errors.append(str(error))
    def close(self,**summary):
        if self.closed:return
        self.closed=True
        if self.thread:
            deadline=time.monotonic()+10
            while self.thread.is_alive() and time.monotonic()<deadline:
                try:self.queue.put(None,timeout=.05);break
                except queue.Full:pass
            self.thread.join(timeout=max(0,deadline-time.monotonic()))
            if self.thread.is_alive():self.errors.append('encoder_shutdown_timeout')
        if self.writer and not(self.thread and self.thread.is_alive()):self.writer.release()
        self.stream.close()
        (self.output/'timestamps.json').write_text(json.dumps(self.rows),encoding='utf-8')
        summary.update(game='kitchen_match',frames_encoded=len(self.rows),frames_dropped=self.dropped,encoder_errors=self.errors,video_timing='MJPG constant FPS; replay uses actual timestamps.json',verified=False)
        (self.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        (self.output/'manifest.json').write_text(json.dumps(dict(video='screen.avi',timestamps='timestamps.json',events='events.jsonl',summary='summary.json',replay_only=True)),encoding='utf-8')


class LoopSessionRecorder:
    """Rotate only when a fresh next-round page is observed; keep each replay independent."""
    def __init__(self,output,fps=30):
        self.initial=Path(output);self.fps=fps;self.lock=threading.RLock();self.index=1
        self.current=SessionRecorder(output,fps);self.sessions=[str(self.current.output.resolve())];self.start_event=None
    @property
    def output(self):return self.current.output
    def event(self,kind,**data):
        with self.lock:
            if kind=='session_start':self.start_event=dict(data)
            self.current.event(kind,**data)
    def frame(self,*args,**kwargs):
        with self.lock:self.current.frame(*args,**kwargs)
    def write_index(self):
        (self.initial/'loop-index.json').write_text(json.dumps(dict(sessions=self.sessions,latest_session=self.sessions[-1],rounds=len(self.sessions)),indent=2),encoding='utf-8')
    def rotate(self,t):
        with self.lock:
            self.current.event('next_round_observed',t=t,verified=False)
            self.current.close(reason='next_round_observed',sends_input=(self.start_event or {}).get('live',False),outcome='unknown')
            self.index+=1;folder=self.initial.with_name(self.initial.name+f'-round{self.index:03d}')
            self.current=SessionRecorder(folder,self.fps);self.sessions.append(str(folder.resolve()))
            data=dict(self.start_event or {});data.update(t=t,loop_round=self.index)
            self.current.event('session_start',**data);self.write_index()
    def close(self,**summary):
        with self.lock:
            self.current.close(**summary);self.write_index()
