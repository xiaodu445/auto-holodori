"""Passive kitchen video and mouse-edge recorder; never injects input."""
import argparse
import json
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
import cv2
from modular_agent.realtime.runtime import WindowCapture
from modular_agent.computer.windows import WindowsBackend


from modular_agent.realtime.record_jump_rope import offer_latest


def monitor_mouse(api,handle,stop,events,origin):
    import ctypes as C
    from ctypes import wintypes as W
    previous={}
    def bounds():
        rect=W.RECT();point=W.POINT(0,0)
        if not api.GetClientRect(handle,C.byref(rect)) or not api.ClientToScreen(handle,C.byref(point)):
            raise RuntimeError('window_bounds_failed')
        return point.x,point.y,rect.right,rect.bottom
    try:
        initial=bounds()
        while not stop.is_set():
            if api.GetForegroundWindow()!=handle:
                events.append(dict(t=time.perf_counter()-origin,type='focus_lost'));stop.set();break
            if api.GetAsyncKeyState(123)&0x8000:
                events.append(dict(t=time.perf_counter()-origin,type='manual_stop',key='f12'));stop.set();break
            current=bounds()
            if current!=initial:
                events.append(dict(t=time.perf_counter()-origin,type='window_moved_or_resized'));stop.set();break
            for name,key in [('left',1),('right',2)]:
                down=bool(api.GetAsyncKeyState(key)&0x8000)
                if previous.get(name)!=down:
                    point=W.POINT()
                    if not api.GetCursorPos(C.byref(point)):raise RuntimeError('cursor_position_failed')
                    x,y,w,h=current
                    if w<=0 or h<=0:raise RuntimeError('empty_window')
                    local=[point.x-x,point.y-y]
                    events.append(dict(t=time.perf_counter()-origin,
                        type='initial_state' if name not in previous else 'mouse_down' if down else 'mouse_up',
                        button=name,down=down,screen_xy=[point.x,point.y],client_xy=local,
                        client_uv=[local[0]/w,local[1]/h],inside_client=0<=local[0]<w and 0<=local[1]<h,
                        client_bounds=list(current)))
                    previous[name]=down
            stop.wait(.002)
    except Exception as error:
        events.append(dict(t=time.perf_counter()-origin,type='input_monitor_failed',error=str(error)));stop.set()


def record(handle,output,duration=300,fps=30,width=0,audio=None):
    if not 0<duration<=3600 or not 1<=fps<=120 or width<0:raise ValueError('invalid recording settings')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    capture=None
    origin=time.perf_counter();stop=threading.Event();events=[];errors=[]
    items=queue.Queue(maxsize=8);rows=[];dropped=0;captured_count=0
    writer=None;encoder=None;keyboard=None;reason='timeout'
    def encode():
        try:
            while True:
                item=items.get()
                if item is None:break
                image,row=item
                writer.write(image)
                row['encoded']=time.perf_counter()-origin
                row['video_index']=len(rows);rows.append(row)
        except Exception as error:errors.append(str(error));stop.set()
    try:
        capture=WindowCapture(handle)
        image,bounds=capture.grab([0,0,1,1])
        size=(min(width or image.shape[1],image.shape[1]),round(image.shape[0]*min(width or image.shape[1],image.shape[1])/image.shape[1]))
        size=tuple(max(2,n//2*2) for n in size)
        writer=cv2.VideoWriter(str(output/'screen.avi'),cv2.VideoWriter_fourcc(*'MJPG'),fps,size)
        if not writer.isOpened():raise RuntimeError('video_encoder_unavailable')
        if audio:audio.start(output,origin,stop)
        encoder=threading.Thread(target=encode,daemon=True);encoder.start()
        keyboard=threading.Thread(target=monitor_mouse,args=(capture.api,handle,stop,events,origin),daemon=True);keyboard.start()
        next_status=origin+3
        while time.perf_counter()-origin<duration and not stop.is_set():
            tick=time.perf_counter()
            image,current=capture.grab([0,0,1,1]);stamp=time.perf_counter()
            if current!=bounds:reason='window_moved_or_resized';break
            local=cv2.resize(image,size) if image.shape[1::-1]!=size else image
            dropped+=offer_latest(items,(local,dict(frame_id=captured_count,t=stamp-origin,capture_started=tick-origin,client_bounds=list(current))))
            captured_count+=1
            if audio and audio.errors:reason='audio_failed';stop.set()
            if stamp>=next_status:
                print(f'录制中：{captured_count/(stamp-origin):.1f} FPS；鼠标按下 {sum(e["type"]=="mouse_down" for e in events)} 次；编码丢帧 {dropped}；声音 {audio.blocks if audio else 0} 块',flush=True)
                next_status=stamp+3
            stop.wait(max(0,1/fps-(time.perf_counter()-tick)))
        if stop.is_set():reason='audio_failed' if audio and audio.errors else events[-1]['type'] if events else 'encoder_failed'
    except KeyboardInterrupt:reason='ctrl_c'
    except Exception as error:reason=str(error)
    finally:
        elapsed=time.perf_counter()-origin
        stop.set()
        if keyboard:keyboard.join(timeout=2)
        if capture:capture.close()
        if audio:
            try:audio.close()
            except Exception as error:audio.errors.append(str(error))
        if encoder:
            while encoder.is_alive():
                try:items.put(None,timeout=.1);break
                except queue.Full:continue
            encoder.join()
        if writer:writer.release()
        (output/'timestamps.json').write_text(json.dumps(rows,ensure_ascii=False),encoding='utf-8')
        (output/'inputs.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
        result=dict(reason=reason,frames_captured=captured_count,frames_encoded=len(rows),frames_dropped=dropped,
            elapsed_seconds=elapsed,actual_capture_fps=captured_count/max(elapsed,1e-9),encoder_errors=errors,
            clock='time.perf_counter; all t values relative to monotonic_origin',monotonic_origin=origin,
            input_method='GetAsyncKeyState sampled at target 2ms; mouse edges may be missed; foreground only',
            game='kitchen_match',video_size=size if writer else None,video_timing='constant FPS; use timestamps.json for actual capture times; MJPG is lossy',
            audio=audio.summary() if audio else dict(enabled=False),nominal_video_fps=fps,timestamp_file='timestamps.json',input_file='inputs.json',sends_input=False)
        (output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def main(argv=None):
    p=argparse.ArgumentParser(description='厨房游戏只读录制：画面及手动鼠标坐标，不发送输入')
    p.add_argument('--window-handle',type=int)
    p.add_argument('--window-title',default='hololive-dreams',help='窗口完整标题，不区分大小写')
    p.add_argument('--list-windows',action='store_true')
    p.add_argument('--duration',type=float,default=300)
    p.add_argument('--fps',type=int,default=30)
    p.add_argument('--width',type=int,default=0,help='0保留原尺寸；其他值只缩小（偶数对齐）')
    p.add_argument('--start-delay',type=float,default=5)
    p.add_argument('--output',type=Path)
    a=p.parse_args(argv)
    if not 0<a.duration<=3600 or not 1<=a.fps<=120 or a.width<0 or not 0<=a.start_delay<=30:p.error('invalid recording settings')
    backend=WindowsBackend()
    if a.list_windows:
        for w in backend.windows():print(f'{w["handle"]}: {w["title"]}')
        return 0
    if a.window_handle is None:
        windows=[w for w in backend.windows() if w['title'].casefold()==a.window_title.casefold()]
        if len(windows)!=1:p.error('请用 --list-windows 查看并指定 --window-handle')
        a.window_handle=windows[0]['handle']
    print(f'{a.start_delay:g}秒后开始，请手动切回游戏。F12 / Ctrl+C / 失焦 / 窗口移动缩放停止。',flush=True)
    time.sleep(a.start_delay);cv2.setNumThreads(1)
    output=a.output or Path('runtime/kitchen/recordings')/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    result=record(a.window_handle,output,a.duration,a.fps,a.width)
    print(f'录制结束：{result["reason"]}；保存 {result["frames_encoded"]} 帧。\n文件：{output.resolve()}',flush=True)
    return int(bool(result['encoder_errors']) or result['frames_encoded']==0 or result['reason'] not in ('timeout','ctrl_c','manual_stop','focus_lost','window_moved_or_resized'))


if __name__=='__main__':raise SystemExit(main())
