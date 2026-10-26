"""Read-only game recording with timestamped Space edges; never injects input."""
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


def read_space(api):
    return bool(api.GetAsyncKeyState(32) & 0x8000)


def monitor_space(api,handle,stop,events,origin):
    previous=None
    while not stop.is_set():
        tick=time.perf_counter()
        focused=api.GetForegroundWindow()==handle
        if not focused:
            events.append(dict(t=tick-origin,type='focus_lost'))
            stop.set();break
        down=read_space(api)
        if down!=previous:
            events.append(dict(t=tick-origin,type='initial_state' if previous is None else 'key_down' if down else 'key_up',key='space',down=down,focused=True))
            previous=down
        if api.GetAsyncKeyState(123)&0x8000:
            events.append(dict(t=tick-origin,type='manual_stop',key='f12'));stop.set();break
        stop.wait(.001)


def offer_latest(items,item):
    """Bounded encoder queue: discard oldest unencoded image on overflow."""
    try:items.put_nowait(item);return 0
    except queue.Full:
        try:items.get_nowait()
        except queue.Empty:pass
        items.put_nowait(item);return 1


def record(handle,output,duration=120,fps=60,width=1280,audio=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    capture=WindowCapture(handle)
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
        image,bounds=capture.grab([0,0,1,1])
        size=(min(width,image.shape[1]),round(image.shape[0]*min(width,image.shape[1])/image.shape[1]))
        size=tuple(max(2,n//2*2) for n in size)
        writer=cv2.VideoWriter(str(output/'screen.avi'),cv2.VideoWriter_fourcc(*'MJPG'),fps,size)
        if not writer.isOpened():raise RuntimeError('video_encoder_unavailable')
        if audio:audio.start(output,origin,stop)
        encoder=threading.Thread(target=encode,daemon=True);encoder.start()
        keyboard=threading.Thread(target=monitor_space,args=(capture.api,handle,stop,events,origin),daemon=True);keyboard.start()
        next_status=origin+3
        while time.perf_counter()-origin<duration and not stop.is_set():
            tick=time.perf_counter()
            image,current=capture.grab([0,0,1,1]);stamp=time.perf_counter()
            if current[2:]!=bounds[2:]:reason='window_resized';break
            local=cv2.resize(image,size) if image.shape[1::-1]!=size else image
            dropped+=offer_latest(items,(local,dict(frame_id=captured_count,t=stamp-origin,capture_started=tick-origin,client_bounds=list(current))))
            captured_count+=1
            if audio and audio.errors:reason='audio_failed';stop.set()
            if stamp>=next_status:
                print(f'录制中：{captured_count/(stamp-origin):.1f} FPS；空格按下 {sum(e["type"]=="key_down" for e in events)} 次；编码丢帧 {dropped}；声音 {audio.blocks if audio else 0} 块',flush=True)
                next_status=stamp+3
            stop.wait(max(0,1/fps-(time.perf_counter()-tick)))
        if stop.is_set():reason='audio_failed' if audio and audio.errors else events[-1]['type'] if events else 'encoder_failed'
    except KeyboardInterrupt:reason='ctrl_c'
    except Exception as error:reason=str(error)
    finally:
        elapsed=time.perf_counter()-origin
        stop.set()
        if keyboard:keyboard.join(timeout=2)
        capture.close()
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
            input_method='GetAsyncKeyState high bit sampled at target 1ms; only Space and F12, game foreground only',
            audio=audio.summary() if audio else dict(enabled=False),nominal_video_fps=fps,timestamp_file='timestamps.json',input_file='inputs.json',sends_input=False)
        (output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


def main():
    p=argparse.ArgumentParser(description='Record game frames and manual Space, no injected input')
    p.add_argument('--window-handle',type=int);p.add_argument('--duration',type=float,default=120)
    p.add_argument('--fps',type=int,default=60);p.add_argument('--width',type=int,default=1280)
    p.add_argument('--audio',action=argparse.BooleanOptionalAction,default=False,help='record output-device loopback, not microphone')
    p.add_argument('--audio-device',type=int,help='explicit loopback device index')
    p.add_argument('--list-audio-devices',action='store_true')
    p.add_argument('--start-delay',type=float,default=3);a=p.parse_args()
    if not 1<=a.duration<=600 or not 1<=a.fps<=120 or not 320<=a.width<=1920 or not 0<=a.start_delay<=30:p.error('invalid recording settings')
    if a.list_audio_devices:
        import pyaudiowpatch as pa
        with pa.PyAudio() as host:
            for d in host.get_loopback_device_info_generator():print(f'{d["index"]}: {d["name"]}')
        return 0
    audio=None
    if a.audio:
        from modular_agent.realtime.loopback_audio import LoopbackAudio
        try:audio=LoopbackAudio(a.audio_device)
        except Exception as error:p.error(f'声音采集不可用，未开始录制：{error}')
    backend=WindowsBackend()
    if a.window_handle is None:
        windows=[w for w in backend.windows() if w['title'].lower()=='hololive-dreams']
        if len(windows)!=1:
            if audio:audio.close()
            p.error('specify --window-handle')
        a.window_handle=windows[0]['handle']
    print(f'录制画面、手动空格及{"扬声器声音" if a.audio else "无音频"}，不发送输入。{a.start_delay:g}秒后切回游戏。F12 / Ctrl+C / 切走游戏停止。',flush=True)
    time.sleep(a.start_delay);backend.focus(a.window_handle);cv2.setNumThreads(1)
    output=Path('runtime/jump-rope/recordings')/datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    result=record(a.window_handle,output,a.duration,a.fps,a.width,audio=audio)
    print(f'录制结束：{result["reason"]}；保存 {result["frames_encoded"]} 帧。\n文件：{output.resolve()}',flush=True)
    if audio and result['audio']['peak_pcm16']==0:print('注意：声音为静音或未收到样本，请确认游戏正在使用所选输出设备。',flush=True)
    if audio:print(f'音频：{result["audio"]["sample_frames"]} 样本帧；峰值 {result["audio"]["peak_pcm16"]}；错误 {result["audio"]["errors"]}',flush=True)
    return 1 if result['audio'].get('errors') or (audio and result['audio']['sample_frames']==0) or result['encoder_errors'] or result['frames_encoded']==0 else 0

if __name__=='__main__':raise SystemExit(main())
