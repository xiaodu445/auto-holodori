"""Record/replay rhythm diagnostics. This tool NEVER injects keyboard input."""
from __future__ import annotations
import argparse,hashlib,html,importlib.util,json,math,queue,shutil,sys,threading,time
from datetime import datetime
from pathlib import Path
import cv2
import numpy as np

ROOT=Path(__file__).resolve().parents[1]


def load_model():
    spec=importlib.util.spec_from_file_location('rhythm_review_model',ROOT/'domains/hololive_dreams/models/rhythm_game.py')
    module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    return module


def record(output,duration=20,fps=120):
    from modular_agent.realtime.rhythm_capture import create_capture
    from modular_agent.computer.windows import WindowsBackend
    from modular_agent.realtime.record_jump_rope import offer_latest
    backend=WindowsBackend();windows=[w for w in backend.windows() if w['title'].lower()=='hololive-dreams']
    if len(windows)!=1:raise ValueError('Open hololive-Dreams first')
    handle=windows[0]['handle']
    print('只录制，不发送按键。切回游戏播放AUTO或已有自动按键程序；等待前台最多45秒。歌曲结束后F12停止并分析。失焦也会结束。',flush=True)
    deadline=time.perf_counter()+45
    while backend.api.GetForegroundWindow()!=handle:
        if backend.emergency_pressed() or time.perf_counter()>deadline:raise RuntimeError('waiting_for_game_cancelled')
        time.sleep(.05)
    output.mkdir(parents=True,exist_ok=False)
    if shutil.disk_usage(output).free<2*1024**3:raise OSError('录制至少需要2GB空闲；全曲建议10GB以上')
    capture=create_capture(handle);writer=None;worker=None;items=queue.Queue(8);errors=[];rows=[];edges=[]
    origin=time.perf_counter();dropped=0;previous_keys=set();stop=threading.Event();reason='duration'
    def encode():
        try:
            while True:
                item=items.get()
                if item is None:break
                image,row=item;writer.write(image);row['video_index']=len(rows);rows.append(row)
        except Exception as error:errors.append(str(error));stop.set()
    try:
        initial=capture.bounds();next_status=origin+3
        while time.perf_counter()-origin<duration and not stop.is_set():
            tick=time.perf_counter();image,bounds=capture.grab((0,0,1,1))
            if bounds!=initial:reason='window_changed';break
            down={key for key in 'sdfjkl' if backend.api.GetAsyncKeyState(ord(key.upper()))&0x8000}
            for key in sorted(down^previous_keys):edges.append(dict(t=time.perf_counter()-origin,key=key,down=key in down))
            previous_keys=down
            if image is None:time.sleep(.001);continue
            stamp=getattr(capture,'last_timestamp',None) or time.perf_counter()
            if writer is None:
                width=min(960,image.shape[1]);size=(width//2*2,round(image.shape[0]*width/image.shape[1])//2*2)
                writer=cv2.VideoWriter(str(output/'screen.avi'),cv2.VideoWriter_fourcc(*'MJPG'),fps,size)
                if not writer.isOpened():raise RuntimeError('encoder_unavailable')
                worker=threading.Thread(target=encode,daemon=True);worker.start()
            local=cv2.resize(image,size)
            dropped+=offer_latest(items,(local,dict(t=stamp-origin,client_bounds=list(bounds))))
            if stamp>=next_status:
                print(f'录制 {stamp-origin:.1f}s，已编码 {len(rows)} 帧，丢弃 {dropped} 帧',flush=True);next_status=stamp+3
                if shutil.disk_usage(output).free<1024**3:reason='low_disk_space';break
            stop.wait(max(0,1/fps-(time.perf_counter()-tick)))
    except KeyboardInterrupt:reason='manual_stop'
    except Exception as error:reason=str(error)
    finally:
        stop.set()
        if worker:
            while worker.is_alive():
                try:items.put(None,timeout=.1);break
                except queue.Full:continue
            worker.join()
        if writer:writer.release()
        capture.close()
        (output/'timestamps.json').write_text(json.dumps(rows),encoding='utf-8')
        (output/'inputs.json').write_text(json.dumps(edges),encoding='utf-8')
        (output/'summary.json').write_text(json.dumps(dict(reason=reason,dropped=dropped,frames=len(rows),errors=errors,sends_input=False,
            monotonic_origin=origin,requested_duration=duration,
            input_sample='S D F J K L high bits sampled once per capture loop; AUTO does not generate OS key edges',capture=capture.stats),indent=2),encoding='utf-8')
    if errors or not rows:raise RuntimeError('No usable recording: '+reason+' '+str(errors))
    return output/'screen.avi'


def clip_edges(edges,start,end):
    """Carry held keys across page boundaries, explicitly marked as such."""
    before={}
    for e in edges:
        if e['time']<start:before[e['key']]=e
    result=[dict(e,time=start,segment_boundary=True) for e in before.values() if e['down']]
    result.extend(e for e in edges if start<=e['time']<=end)
    down={}
    for e in result:down[e['key']]=e
    result.extend(dict(e,time=end,down=False,segment_boundary=True) for e in list(down.values()) if e['down'])
    return result


def write_review(data,output,segment_seconds=0):
    template=Path(__file__).with_name('rhythm_review.html').read_text(encoding='utf-8')
    live=data.get('mode')=='live'
    if live:
        template=template.replace('离线模拟','当次运行记录').replace('离线分析','当次耗时').replace('当前状态 · 模拟','当前状态 · 实际运行')
    def page(payload,path):
        embedded=json.dumps(payload,ensure_ascii=False,separators=(',',':')).replace('</','<\\/')
        path.write_text(template.replace('/*REVIEW_DATA*/',embedded),encoding='utf-8')
    if not segment_seconds:
        page(data,output/'index.html');return
    # Separate local pages avoid loading all frames into the browser at once.
    parts=[];group=[];begin=data['frames'][0]['time']
    for f in data['frames']:
        if group and f['time']-begin>=segment_seconds:
            parts.append(group);group=[];begin=f['time']
        group.append(f)
    if group:parts.append(group)
    links=[]
    for number,frames in enumerate(parts):
        name=f'part-{number+1:04d}.html';start=frames[0]['time'];end=frames[-1]['time']
        issues={}
        for f in frames:
            for flag in f['flags']:issues[flag]=issues.get(flag,0)+1
        payload=dict(data,frames=frames,issues=issues,
            input_edges=clip_edges(data['input_edges'],start,end),recorded_input_edges=clip_edges(data['recorded_input_edges'],start,end))
        page(payload,output/name)
        content=(output/name).read_text(encoding='utf-8')
        nav='<nav style="padding:12px"><a href="index.html">全曲总览</a>'
        if number:nav+=f' · <a href="part-{number:04d}.html">上一段</a>'
        if number+1<len(parts):nav+=f' · <a href="part-{number+2:04d}.html">下一段</a>'
        (output/name).write_text(content.replace('<body>','<body>'+nav+'</nav>',1),encoding='utf-8')
        actions=sum('arrival' in e for f in frames for e in f['events'])
        links.append(f'<tr><td><a href="{name}">{start:.1f}–{end:.1f} 秒</a></td><td>{len(frames)}</td><td>{actions}</td><td>{html.escape(" / ".join(issues)) or "无"}</td></tr>')
    overview='<!doctype html><meta charset="utf-8"><title>整首歌 · 分析总览</title><style>body{background:#10141c;color:#e7edf5;font:16px system-ui;margin:30px}a{color:#60d6ef}td,th{text-align:left;padding:12px;border-bottom:1px solid #303b4c}table{width:100%}</style>'
    overview+=f'<h1>整首歌 · 分析总览</h1><p>{data["frames"][0]["time"]:.2f}–{data["frames"][-1]["time"]:.2f} 秒 · {len(data["frames"])} 帧 · {len(parts)} 段</p>'
    overview+=('<p>当次实际运行：同一批截图、全程决策、按键API调用成功/失败及起止时间。API成功不证明游戏收到或Perfect。疑点仅供导航，最后截图之后的释放记录见analysis.json/input_attempts。</p>' if live else '<p>离线重算，不是实际执行决策日志，也不自动识别游戏Perfect。疑点为导航提示。录制系统按键按截图循环采样，不能代表精确发送时间。每段支持逐帧、预测轨迹和反馈导出。</p>')
    overview+=f'<p>源录像：{html.escape(data["source"])}</p><table><thead><tr><th>打开片段</th><th>帧数</th><th>模拟触发</th><th>疑点类型</th></tr></thead><tbody>'+''.join(links)+'</tbody></table>'
    if live:overview=overview.replace('模拟触发','当次决策触发')
    (output/'index.html').write_text(overview,encoding='utf-8')


def analyze(video,output,*,timestamps=None,title_bar=0,start=0,duration=60,segment_seconds=0):
    m=load_model();config=m.load_config(ROOT);vision=m.RhythmVision(config);controller=m.RhythmController(config)
    capture=cv2.VideoCapture(str(video));fps=capture.get(cv2.CAP_PROP_FPS)
    if not capture.isOpened() or not math.isfinite(fps) or fps<=0:raise ValueError('unreadable video / FPS')
    stamps=json.loads(timestamps.read_text(encoding='utf-8')) if timestamps else None
    if stamps is not None and (not stamps or any(b['t']<=a['t'] for a,b in zip(stamps,stamps[1:]))):raise ValueError('nonmonotonic timestamps')
    output.mkdir(parents=True,exist_ok=False);images=output/'frames';images.mkdir()
    rows=[];index=0;previous=None;down=set();all_events=[];issues={};last_ids=set();track_seen={};reason='video_end'
    origin=stamps[0]['t'] if stamps else 0.
    def pump(t,paths=None,notes=None):
        nonlocal down
        d=controller.decide(notes,t,paths or ()) if notes is not None else controller.poll(t)
        edges=[dict(time=t,key=key,down=key in d['keys'],simulated=True) for key in sorted(down^d['keys'])]
        down=set(d['keys']);return d,edges
    try:
        while True:
            ok,image=capture.read()
            if not ok:break
            source=index;index+=1
            if stamps is not None:
                if source>=len(stamps):raise ValueError('video exceeds timestamp count')
                t=stamps[source]['t']-origin
            else:t=source/fps
            # Process pre-roll too, so seeking start does not invent a cold tracker.
            if duration is not None and t>start+duration:reason='duration_limit';break
            frame_events=[]
            if previous is not None:
                steps=0;cursor=previous+.001
                while cursor<t and steps<500:
                    d,edges=pump(cursor);all_events.extend(edges);frame_events.extend(d['events']);cursor+=.001;steps+=1
            if title_bar>=image.shape[0]:raise ValueError('title-bar crop removes image')
            image=image[title_bar:]
            width=min(960,image.shape[1]);image=cv2.resize(image,(width,round(image.shape[0]*width/image.shape[1])))
            begin=time.perf_counter();notes=vision.detect(image,t);d,edges=pump(t,vision.hold_paths,notes);all_events.extend(edges)
            frame_events.extend(d['events']);algorithm_ms=(time.perf_counter()-begin)*1000
            tracks=[];flags=[];ids=set()
            for track in controller.tracks:
                ident=track['id'];ids.add(ident);age=t-track['last']
                if ident not in track_seen:
                    track_seen[ident]=t
                    if track['y']>.65:flags.append('靠近判定线才建轨迹')
                if .04<age<.23 and not track['fired']:
                    flags.append('保护区沿用已确认预测' if track.get('locked') else '短暂丢失，依赖预测')
                if track.get('prediction_source')=='rejected_jump':flags.append('已拒绝时间预测突跳')
                if track.get('prediction_source')=='rejected_observation':flags.append('已过滤位置异常观测（疑似特效）')
                if track['arrival'] is None and track['y']>.5:flags.append('中段没有有效速度')
                tracks.append(dict(id=ident,lane=track['lane'],color=track['color'],kind=track['kind'],x=track['x'],y=track['y'],
                    locked=track.get('locked',False),prediction_source=track.get('prediction_source'),lock_until=track.get('lock_until'),
                    velocity=track.get('velocity'),eta_ms=None if track['arrival'] is None else (track['arrival']-t)*1000,
                    projected_y=controller.motion.predict(track,t),phase_rate=track.get('phase_rate'),
                    arrival=track['arrival'],age_ms=age*1000,fired=track['fired'],ignored_reason=track.get('ignored_reason')))
            if last_ids-ids:flags.append('轨迹过期')
            if any(e.get('lateness_ms',0)>10 for e in frame_events):flags.append('目标时间延迟超过10ms')
            if any(e.get('type')=='hold_release' for e in frame_events):flags.append('长按释放')
            last_ids=ids;previous=t
            if t<start:continue
            frame=len(rows);path=f'frames/{frame:06d}.jpg'
            if not cv2.imwrite(str(output/path),image,[cv2.IMWRITE_JPEG_QUALITY,82]):raise OSError('frame export failed')
            for flag in set(flags):issues[flag]=issues.get(flag,0)+1
            rows.append(dict(frame=frame,source_frame=source,time=t,image=path,notes=[n.__dict__ for n in notes],tracks=tracks,
                keys=sorted(down),events=frame_events,holds=d['holds'],flags=sorted(set(flags)),bpm=d['bpm'],grid=d.get('grid'),analysis_ms=algorithm_ms))
            if frame%300==0:print(f'分析 {t:.2f}s / {frame} 帧',flush=True)
        if stamps is not None and reason=='video_end' and index!=len(stamps):raise ValueError('timestamp count exceeds video')
    finally:capture.release()
    if not rows:raise ValueError('no frames in selected range')
    # Close simulated keys at analysis boundary, explicitly labelled synthetic.
    all_events.extend(dict(time=rows[-1]['time'],key=k,down=False,simulated=True,boundary_release=True) for k in sorted(down))
    digest=hashlib.sha256()
    with video.open('rb') as source:
        for chunk in iter(lambda:source.read(1024*1024),b''):digest.update(chunk)
    recorded_edges=[]
    input_path=video.parent/'inputs.json'
    if stamps and input_path.exists():
        recorded_edges=[dict(time=e['t']-origin,key=e['key'],down=e['down'],simulated=False) for e in json.loads(input_path.read_text(encoding='utf-8')) if e.get('key') in config['keys'] and 'down' in e and start<=e['t']-origin<=rows[-1]['time']]
    data=dict(schema=1,source=str(video.resolve()),sha256=digest.hexdigest(),config=config,frames=rows,recorded_input_edges=recorded_edges,
        input_edges=[e for e in all_events if e['time']>=start],issues=issues,reason=reason,
        limits='按键为离线模拟，不等于实际发送或游戏判定。疑点为启发式，AUTO画面不是完整谱面真值。',
        clock='recorded monotonic timestamps' if stamps else 'frame index / nominal FPS; variable-frame-rate timing not calibrated')
    (output/'analysis.json').write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    write_review(data,output,segment_seconds)
    print('分析页：'+str((output/'index.html').resolve()),flush=True)
    return data


def main():
    p=argparse.ArgumentParser();p.add_argument('video',nargs='?');p.add_argument('--record',action='store_true')
    p.add_argument('--duration',type=float);p.add_argument('--start',type=float,default=0)
    p.add_argument('--full-song',action='store_true',help='record up to 10 minutes / analyze to video end; export 30s pages')
    p.add_argument('--title-bar',type=int,default=0);p.add_argument('--timestamps');p.add_argument('--output')
    a=p.parse_args()
    if a.duration is not None and (not math.isfinite(a.duration) or not 1<=a.duration<=1800):p.error('duration must be 1..1800 seconds')
    if not math.isfinite(a.start) or a.start<0 or a.title_bar<0:p.error('invalid range')
    duration=a.duration if a.duration is not None else (None if a.full_song else 20)
    cv2.setNumThreads(1)
    session=datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    output=Path(a.output).resolve() if a.output else ROOT/'runtime/rhythm/reviews'/session
    if output.exists():p.error('output already exists; choose a new directory')
    if a.record:
        if a.video:p.error('choose record or video')
        video=record(ROOT/'runtime/rhythm/recordings'/session,duration if duration is not None else 600)
    elif a.video:video=Path(a.video).resolve()
    else:p.error('drag a video onto analyze_rhythm_video.cmd, or use record_rhythm_review.cmd')
    stamps=Path(a.timestamps) if a.timestamps else video.parent/'timestamps.json'
    data=analyze(video,output,timestamps=stamps if stamps.exists() else None,title_bar=a.title_bar,start=a.start,duration=duration,segment_seconds=30 if a.full_song else 0)
    (ROOT/'runtime/rhythm/latest-review.txt').write_text(str(output/'index.html'),encoding='utf-8')
    print(f'导出 {len(data["frames"])} 帧；疑点 {data["issues"]}；未发送输入。',flush=True)

if __name__=='__main__':main()
