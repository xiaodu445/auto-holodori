"""Explicit opt-in live play + same-frame diagnostics; no second capturer."""
from __future__ import annotations
import argparse,bisect,hashlib,json,math,queue,shutil,threading,time
from datetime import datetime
from pathlib import Path
import cv2
import rhythm_review as review

ROOT=Path(__file__).resolve().parents[1]


class LiveDiagnostics:
    def __init__(self,output,*,origin=None,fps=120):
        self.output=Path(output);self.output.mkdir(parents=True,exist_ok=False)
        if shutil.disk_usage(self.output).free<2*1024**3:raise OSError('至少需要2GB空闲，全曲建议10GB以上')
        (self.output/'frames').mkdir()
        self.origin=time.perf_counter() if origin is None else origin
        self.fps=fps;self.items=queue.Queue(64);self.error=None;self.rows=[];self.edges=[];self.stamps=[];self.closed=False;self.enabled=True
        self.thread=threading.Thread(target=self.worker,name='rhythm-live-diagnostics',daemon=True);self.thread.start()

    def check(self):
        if self.error:raise RuntimeError('diagnostic_recording_failed: '+self.error)

    def put(self,item):
        # Called from input thread: never block or throw after a successful
        # key_down. Main/timer checks error and releases owned keys on exit.
        if self.error or self.closed:return
        try:self.items.put_nowait(item)
        except queue.Full:self.error='bounded recording queue full; stopped rather than silently dropping diagnostics'

    def input_edge(self,event):
        if getattr(self,'enabled',True):self.put(('input',dict(event)))

    def frame(self,image,stamp,bounds,notes,tracks,decision,keys,timing):
        if not getattr(self,'enabled',True):return
        self.check()
        payload=dict(time=stamp-self.origin,notes=[dict(n.__dict__) for n in notes],tracks=tracks,keys=keys,
            events=[dict(e) for e in decision['events']],holds=[dict(h) for h in decision['holds']],
            grid=decision.get('grid'),music_clock=decision.get('music_clock'),mechanism=decision.get('mechanism'),bpm=decision['bpm'],inhibited=decision.get('inhibited'),timing_ms=timing,
            client_bounds=list(bounds))
        # JSON snapshot detaches mutable controller state before releasing it
        # to the asynchronous encoder. Only opt-in diagnostics pay this cost.
        payload=json.loads(json.dumps(payload))
        self.put(('frame',(image.copy(),payload)))
        self.check()

    def relative_event(self,event):
        e=dict(event)
        for key in ('time','arrival','target','grid_arrival','middle_arrival','begin','resume','anchor','until'):
            if isinstance(e.get(key),(float,int)):e[key]-=self.origin
        return e

    def worker(self):
        writer=None
        try:
            with (self.output/'live-decisions.jsonl').open('w',encoding='utf-8') as journal:
                while True:
                    item=self.items.get()
                    if item is None:break
                    kind,payload=item
                    if kind=='input':
                        event=self.relative_event(payload);event['simulated']=False
                        self.edges.append(event);journal.write(json.dumps(dict(type='input',**event),ensure_ascii=False)+'\n');journal.flush()
                        continue
                    image,row=payload
                    if writer is None:
                        size=(image.shape[1],image.shape[0])
                        writer=cv2.VideoWriter(str(self.output/'screen.avi'),cv2.VideoWriter_fourcc(*'MJPG'),self.fps,size)
                        if not writer.isOpened():raise RuntimeError('video encoder unavailable')
                    index=len(self.rows);path=f'frames/{index:06d}.jpg'
                    if not cv2.imwrite(str(self.output/path),image,[cv2.IMWRITE_JPEG_QUALITY,82]):raise OSError('frame export failed')
                    writer.write(image)
                    row.update(frame=index,source_frame=index,image=path,analysis_ms=sum(row['timing_ms'].values()))
                    row['events']=[self.relative_event(e) for e in row['events']]
                    for track in row['tracks']:
                        for key in ('arrival','lock_until'):
                            if track.get(key) is not None:track[key]-=self.origin
                    if row.get('grid') and row['grid'].get('phase') is not None:row['grid']['phase']-=self.origin
                    if row.get('music_clock'):
                        clock=row['music_clock']
                        if clock.get('epoch') is not None:clock['epoch']-=self.origin
                        for candidate in clock.get('candidates',[]):candidate['next_bar']-=self.origin
                    if row.get('mechanism'):
                        plan=row['mechanism']
                        for key in ('anchor','until'):
                            if plan.get(key) is not None:plan[key]-=self.origin
                        for slot in plan.get('slots',[]):slot['arrival']-=self.origin
                    for hold in row['holds']:
                        for key in ('start','last'):
                            if hold.get(key) is not None:hold[key]-=self.origin
                    flags=[]
                    if row['inhibited']:flags.append('输入被禁止：'+row['inhibited'])
                    if any(t.get('prediction_source')=='rejected_observation' for t in row['tracks']):flags.append('位置观测被拒绝')
                    if any(t.get('prediction_source')=='rejected_jump' for t in row['tracks']):flags.append('预测突跳被拒绝')
                    if any(e.get('lateness_ms',0)>10 for e in row['events']):flags.append('决策晚于预测目标10ms')
                    row['flags']=flags
                    self.rows.append(row);self.stamps.append(dict(t=row['time'],video_index=index,client_bounds=row['client_bounds']))
                    journal.write(json.dumps(dict(type='frame',**row),ensure_ascii=False)+'\n')
                    if index%120==0:
                        journal.flush()
                        if shutil.disk_usage(self.output).free<1024**3:raise OSError('low disk space')
        except Exception as error:self.error=str(error)
        finally:
            if writer:writer.release()

    def finish(self,config,result):
        if self.closed:raise RuntimeError('diagnostics already closed')
        # run() has already stopped/joined its timer and released game keys.
        self.closed=True
        while self.thread.is_alive():
            try:self.items.put(None,timeout=.1);break
            except queue.Full:continue
        self.thread.join()
        (self.output/'timestamps.json').write_text(json.dumps(self.stamps),encoding='utf-8')
        edges=sorted(self.edges,key=lambda e:e['time'])
        (self.output/'inputs.json').write_text(json.dumps([dict(t=e['time'],key=e['key'],down=e['down']) for e in edges if e['success'] and not e.get('cleanup_confirmation')]),encoding='utf-8')
        summary=dict(reason=result.get('reason'),live=True,frames=len(self.rows),recording_error=self.error,
            monotonic_origin=self.origin,clock='same-process perf_counter',sends_input=True,
            evidence='API success confirms delivery attempt, not game judgement',result={k:v for k,v in result.items() if k!='rows'})
        (self.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False),encoding='utf-8')
        if not self.rows:raise RuntimeError('没有可用录制帧；'+str(self.error or result.get('reason')))
        # Timer events after the last capture are preserved, not discarded.
        self.rows[-1]['events'].extend(self.relative_event(e) for e in result.get('scheduled_events_pending_log',[]))
        frame_times=[row['time'] for row in self.rows]
        for edge in edges:
            index=max(0,min(len(self.rows)-1,bisect.bisect_right(frame_times,edge['time'])-1))
            self.rows[index]['events'].append(dict(type='input_call',**edge))
        for row in self.rows:row['events'].sort(key=lambda e:e.get('time',row['time']))
        failures=[e for e in edges if not e['success']]
        if failures:self.rows[-1]['flags'].append('存在发送失败；查看input_attempts')
        if self.error:self.rows[-1]['flags'].append('录制不完整：'+self.error)
        if result.get('cleanup_error'):self.rows[-1]['flags'].append('松键清理失败：'+result['cleanup_error'])
        issues={}
        for row in self.rows:
            for flag in row['flags']:issues[flag]=issues.get(flag,0)+1
        digest=hashlib.sha256()
        with (self.output/'screen.avi').open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
        data=dict(schema=2,mode='live',source=str((self.output/'screen.avi').resolve()),sha256=digest.hexdigest(),
            config=config,frames=self.rows,input_edges=[],recorded_input_edges=[e for e in edges if e['success'] and not e.get('cleanup_confirmation')],
            input_attempts=edges,issues=issues,reason=result.get('reason'),clock='same-process monotonic; input begin/end bracket API call',
            limits='当次实际决策及按键API调用记录，不是离线重算；成功不等于游戏收到或Perfect。末帧后的释放见input_attempts。')
        (self.output/'analysis.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        review.write_review(data,self.output,30)
        return self.output/'index.html'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',action='store_true',required=True,help='explicit permission to send game keys')
    p.add_argument('--duration',type=float,default=0,help='0 = unlimited; otherwise 1..1800 seconds');p.add_argument('--preview',action='store_true')
    p.add_argument('--fps',type=float,help='target processing FPS, 30..240')
    p.add_argument('--analysis-width',type=int,help='recognition image width, 480..1600')
    p.add_argument('--bpm',type=float);p.add_argument('--offset-ms',type=float);p.add_argument('--output')
    p.add_argument('--input-mode',choices=['normal','all-held'],default='all-held')
    p.add_argument('--release-scope',choices=['target','all'],default=None)
    p.add_argument('--global-flow',choices=['off','shadow','active'],default=None,
        help='experimental shared scroll speed; off preserves stable prediction, shadow logs only')
    p.add_argument('--measure-clock',choices=['off','shadow'],default=None,help='shadow pulse/bar clock; never sends extra keys')
    p.add_argument('--mechanism-mode',choices=['off','shadow','active'],default=None,
        help='experimental 3-sixteenth cadence continuation for observed wide blue runs')
    tuning={'release_lead_ms':(0,300),'dense_gap_ms':(0,300),
            'dense_recovery_ms':(25,500),'dense_tap_ms':(1,50),'grid_snap_ms':(0,25),
            'min_down_ms':(1,50),'release_gap_ms':(1,50),'key_lookahead_ms':(0,300),
            'slide_guard_ms':(0,500)}
    for name,(low,high) in tuning.items():
        p.add_argument('--'+name.replace('_','-'),type=float,help=f'{low}..{high} ms; omit to use configuration')
    p.add_argument('--record',dest='record',action='store_true',default=True,help='record video and full diagnostics')
    p.add_argument('--no-record',dest='record',action='store_false',help='play only; no video/frames/full diagnostic export')
    a=p.parse_args()
    if a.fps is not None and (not math.isfinite(a.fps) or not 30<=a.fps<=240):p.error('fps must be 30..240')
    if a.analysis_width is not None and not 480<=a.analysis_width<=1600:p.error('analysis-width must be 480..1600')
    for name,(low,high) in tuning.items():
        value=getattr(a,name)
        if value is not None and (not math.isfinite(value) or not low<=value<=high):
            p.error(f'{name} must be {low}..{high} ms')
    if not math.isfinite(a.duration) or (a.duration!=0 and not 1<=a.duration<=1800):p.error('duration must be 0 (unlimited) or 1..1800')
    if a.bpm is not None and (not math.isfinite(a.bpm) or not 40<=a.bpm<=400):p.error('BPM must be 40..400')
    if a.offset_ms is not None and (not math.isfinite(a.offset_ms) or abs(a.offset_ms)>100):p.error('offset must be -100..100 ms')
    from modular_agent.computer.windows import WindowsBackend
    backend=WindowsBackend();windows=[w for w in backend.windows() if w['title'].lower()=='hololive-dreams']
    if len(windows)!=1:p.error('Open exactly one hololive-Dreams window first')
    handle=windows[0]['handle'];print(('自动按键+录制。' if a.record else '自动按键；录制关闭。')+'关闭游戏AUTO。切回游戏，等待前台最多45秒；F12/失焦停止。',flush=True)
    deadline=time.perf_counter()+45
    while backend.api.GetForegroundWindow()!=handle:
        if backend.emergency_pressed() or time.perf_counter()>deadline:raise RuntimeError('waiting_for_game_cancelled')
        time.sleep(.05)
    overrides=dict(timeout=a.duration)
    if a.global_flow is not None:overrides['global_flow']=a.global_flow
    if a.measure_clock is not None:overrides['measure_clock']=a.measure_clock
    if a.mechanism_mode is not None:overrides['mechanism_mode']=a.mechanism_mode
    if a.fps is not None:overrides['fps']=a.fps
    if a.analysis_width is not None:overrides['analysis_width']=a.analysis_width
    for name in tuning:
        if getattr(a,name) is not None:overrides[name]=getattr(a,name)
    if a.input_mode is not None:overrides['input_mode']=a.input_mode
    if a.release_scope is not None:overrides['release_scope']=a.release_scope
    if a.bpm is not None:overrides['bpm']=a.bpm
    if a.offset_ms is not None:overrides['input_offset_ms']=a.offset_ms
    m=review.load_model()
    if not a.record:
        result=m.run(ROOT,handle,live=True,preview=a.preview,overrides=overrides,diagnostics=None,progress=lambda s:print(s,flush=True))
        print(json.dumps({k:v for k,v in result.items() if k!='rows'},ensure_ascii=False,indent=2),flush=True)
        return
    output=Path(a.output).resolve() if a.output else ROOT/'runtime/rhythm/live-reviews'/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    sink=LiveDiagnostics(output);sink.enabled=False;result=dict(reason='startup_failure')
    paused=True;quit_requested=False
    key_state={119:False,121:False,123:False} # F8/F10/F12
    def hotkeys():
        nonlocal paused,quit_requested
        while not quit_requested:
            for vk in key_state:
                down=bool(backend.api.GetAsyncKeyState(vk)&0x8000)
                if down and not key_state[vk]:
                    if vk==119:paused=not paused;print('F8 '+('暂停' if paused else '开始'),flush=True)
                    elif vk==121:sink.enabled=not sink.enabled;print('F10 '+('录制开始' if sink.enabled else '录制停止'),flush=True)
                    else:quit_requested=True
                key_state[vk]=down
            time.sleep(.02)
    hotkey_thread=threading.Thread(target=hotkeys,name='rhythm-hotkeys',daemon=True);hotkey_thread.start()
    try:
        result=m.run(ROOT,handle,live=True,preview=a.preview,overrides=overrides,diagnostics=sink,pause=lambda:paused,should_yield=lambda:quit_requested,progress=lambda s:print(s,flush=True))
    finally:
        config=m.load_config(ROOT);config.update(overrides);config=result.get('settings',config)
        quit_requested=True;hotkey_thread.join(timeout=1);page=sink.finish(config,result)
        (ROOT/'runtime/rhythm/latest-review.txt').write_text(str(page),encoding='utf-8')
        print('实际运行分析：'+str(page),flush=True)
    if sink.error:raise RuntimeError('录制不完整，已保存现有证据：'+sink.error)

if __name__=='__main__':main()
