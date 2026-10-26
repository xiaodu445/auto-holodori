"""Bounded in-memory failure clips, triggered by a stable jump-counter stall."""
from collections import Counter, deque
from datetime import datetime
import copy
import json
from pathlib import Path
import queue
import threading
import time

import cv2
import numpy as np


class CounterStallDetector:
    def __init__(self, settings):
        self.stall = float(settings.get('stall_seconds', 2.0))
        self.stable = float(settings.get('counter_stable_seconds', .12))
        self.difference = float(settings.get('glyph_difference', .08))
        self.needed = int(settings.get('minimum_progress_changes', 2))
        if not 1.5 <= self.stall <= 2.0 or self.stable <= 0 or not 0 < self.difference < 1 or self.needed < 1:
            raise ValueError('Invalid failure-capture detection settings')
        self.reset()

    def reset(self):
        self.current = self.pending = None
        self.pending_reading = None
        self.pending_since = self.last_time = self.last_progress = None
        self.changes = 0
        self.latched = False
        self.reading = None

    def changed(self, a, b):
        if a is None or b is None or len(a) != len(b):
            return True
        return any(np.count_nonzero(x ^ y) / max(1, np.count_nonzero(x | y)) > self.difference for x, y in zip(a, b))

    def _commit(self, now, glyphs, reading):
        first = self.current is None
        both_numeric = reading is not None and self.reading is not None
        reset = both_numeric and reading < self.reading
        progressed = not first and (reading > self.reading if both_numeric else self.changed(glyphs, self.current))
        if first or reset or progressed:
            self.last_progress = now
        if reset:
            self.changes = 0
            self.latched = False
        elif progressed:
            self.changes = 1 if self.latched else self.changes + 1
            self.latched = False
        self.current = tuple(np.asarray(g, bool).copy() for g in glyphs)
        self.reading = reading

    def update(self, now, glyphs, reading=None):
        if self.last_time is not None and (now < self.last_time or now - self.last_time > .75):
            self.reset()
        self.last_time = now
        visible = 1 <= len(glyphs) <= 3
        trigger = None
        if visible:
            if reading is not None:
                # Stable numeric identity survives the counter's scale/glow animation.
                if self.pending_reading != reading or self.pending_since is None:
                    self.pending_reading = reading
                    self.pending_since = now
                self.pending = tuple(np.asarray(g, bool).copy() for g in glyphs)
                if now - self.pending_since >= self.stable:
                    self._commit(now, self.pending, reading)
            else:
                # Unknown numerals use visual change with a longer confirmation interval.
                if self.pending_reading is not None or self.changed(glyphs, self.pending):
                    self.pending = tuple(np.asarray(g, bool).copy() for g in glyphs)
                    self.pending_since = now
                    self.pending_reading = None
                if self.pending_since is not None and now - self.pending_since >= 2 * self.stable and self.changed(self.pending, self.current):
                    self._commit(now, self.pending, None)
        else:
            self.pending = None
            self.pending_since = None
            self.pending_reading = None
        elapsed = None if self.last_progress is None else max(0., now - self.last_progress)
        ready = self.changes >= self.needed
        if ready and not self.latched and elapsed >= self.stall:
            self.latched = True
            trigger = dict(reason='counter_stalled' if visible else 'counter_unreadable_after_progress', classification='suspected_death', detected_at=now, anchor_time=self.last_progress, stagnant_seconds=elapsed, readable_count=reading, last_readable_count=self.reading, confirmed_progress_changes=self.changes)
        return dict(state='suspected_death' if self.latched else 'tracking' if ready else 'waiting_for_counter_progress', counter_visible=visible, readable_count=reading, confirmed_progress_changes=self.changes, stagnant_seconds=elapsed, trigger=trigger)


class FailureRecorder:
    """Main loop never waits for JPEG encoding, video writing, or filesystem I/O."""
    def __init__(self, output, settings, metadata):
        self.output = Path(output)
        self.settings = copy.deepcopy(settings)
        self.metadata = copy.deepcopy(metadata)
        self.pre = float(settings.get('pre_seconds', 3.0))
        self.manual_seconds = float(settings.get('manual_seconds', 3.0))
        self.auto_detect = bool(settings.get('auto_detect', True))
        self.fps = float(settings.get('fps', 60.0))
        self.quality = int(settings.get('jpeg_quality', 90))
        self.max_bytes = int(float(settings.get('max_buffer_mb', 96)) * 1024 * 1024)
        if self.pre <= 0 or self.manual_seconds <= 0 or not 1 <= self.fps <= 60 or not 1 <= self.quality <= 100 or self.max_bytes <= 0:
            raise ValueError('Invalid failure-capture buffer settings')
        self.detector = CounterStallDetector(settings)
        self.horizon = max(self.pre, self.manual_seconds) + (self.detector.stall if self.auto_detect else 0) + 2
        self.events = deque()
        self.edges = deque()
        self.edge_lock = threading.Lock()
        self.jobs = queue.Queue(maxsize=2)
        self.saves = queue.Queue(maxsize=2)
        self.generation = 0
        self.next_submit = None
        self.last_time = None
        self.closed = False
        self.dropped = 0
        self.saved = []
        self.errors = []
        self.encoder = threading.Thread(target=self._encode, name='failure-clip-encode', daemon=True)
        self.writer = threading.Thread(target=self._write, name='failure-clip-write', daemon=True)
        self.writer.start()
        self.encoder.start()

    def error(self, message):
        if len(self.errors) < 20:
            self.errors.append(str(message))
        print('失败片段记录：' + str(message), flush=True)

    def record_input(self, edge):
        with self.edge_lock:
            self.edges.append(dict(edge))
            while self.edges and edge['time'] - self.edges[0]['time'] > self.horizon:
                self.edges.popleft()

    def reset(self):
        self.generation += 1
        self.detector.reset()
        self.events.clear()
        with self.edge_lock:
            self.edges.clear()
        self.next_submit = self.last_time = None

    def _offer(self, job):
        try:
            self.jobs.put_nowait(job)
        except queue.Full:
            try:
                removed = self.jobs.get_nowait()
                if removed is not None and removed.get('save'):
                    # Preserve explicit save requests; drop this new frame instead.
                    self.jobs.put_nowait(removed)
                    self.dropped += 1
                    return
                self.dropped += 1
            except queue.Empty:
                pass
            try:
                self.jobs.put_nowait(job)
            except queue.Full:
                self.dropped += 1

    def _save_info(self, trigger):
        start = trigger.get('start_time', trigger['anchor_time'] - self.pre)
        with self.edge_lock:
            edges = [dict(e) for e in self.edges if start <= e['time'] <= trigger['detected_at']]
        return dict(trigger=trigger, events=[copy.deepcopy(r) for r in self.events if start <= r['time'] <= trigger['detected_at']], inputs=edges)

    def observe(self, image, mask, row, glyphs, reading):
        now = row['time']
        if self.last_time is not None and (now < self.last_time or now - self.last_time > .75):
            self.reset()
        self.last_time = now
        if self.auto_detect:
            state = self.detector.update(now, glyphs, reading)
            trigger = state.pop('trigger')
        else:
            state = dict(state='manual_buffering',counter_visible=1<=len(glyphs)<=3,readable_count=reading)
            trigger = None
        row['failure_capture'] = state
        self.events.append(copy.deepcopy(row))
        while self.events and now - self.events[0]['time'] > self.horizon:
            self.events.popleft()
        save = self._save_info(trigger) if trigger else None
        if save or self.next_submit is None or now >= self.next_submit:
            self.next_submit = now + 1 / self.fps if self.next_submit is None else max(self.next_submit + 1 / self.fps, now + 1e-6)
            self._offer(dict(generation=self.generation, time=now, image=image.copy(), mask=mask.copy(), row=copy.deepcopy(row), save=save))
        return state

    def manual_save(self, reason='manual_F10'):
        if not self.events:
            return
        now = self.events[-1]['time']
        trigger = dict(reason=reason, classification='manual_review', detected_at=now, anchor_time=now,start_time=now-self.manual_seconds,requested_seconds=self.manual_seconds)
        self._offer(dict(generation=self.generation, time=now, save=self._save_info(trigger)))

    def _encode(self):
        ring = deque()
        size = 0
        generation = None
        while True:
            job = self.jobs.get()
            if job is None:
                self.saves.put(None)
                return
            try:
                if job['generation'] != generation:
                    generation = job['generation'];ring.clear();size = 0
                if 'image' in job:
                    ok, jpg = cv2.imencode('.jpg', job['image'], [cv2.IMWRITE_JPEG_QUALITY, self.quality])
                    mok, png = cv2.imencode('.png', np.uint8(job['mask']) * 255)
                    if not ok or not mok:
                        raise RuntimeError('frame_encoding_failed')
                    packet = dict(time=job['time'], jpg=jpg.tobytes(), mask=png.tobytes(), row=job['row'])
                    ring.append(packet);size += len(packet['jpg']) + len(packet['mask'])
                    while ring and (job['time'] - ring[0]['time'] > self.horizon or size > self.max_bytes):
                        removed = ring.popleft();size -= len(removed['jpg']) + len(removed['mask'])
                if job.get('save'):
                    start = job['save']['trigger'].get('start_time',job['save']['trigger']['anchor_time'] - self.pre)
                    packets = [p for p in ring if start <= p['time'] <= job['time']]
                    if packets:
                        try:
                            self.saves.put_nowait(dict(packets=packets, **job['save']))
                        except queue.Full:
                            self.error('保存队列繁忙，本次片段未保存；识别循环继续。')
            except Exception as exc:
                self.error(exc)

    def _write(self):
        while True:
            job = self.saves.get()
            if job is None:
                return
            try:
                self._save_case(job)
            except Exception as exc:
                self.error(exc)

    def _save_case(self, job):
        self.output.mkdir(parents=True, exist_ok=True)
        folder = self.output / ('failure-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
        (folder / 'frames').mkdir(parents=True)
        (folder / 'masks').mkdir()
        packets = job['packets']
        start = packets[0]['time']
        rows = []
        video = None
        video_error = None
        video_fps = (len(packets) - 1) / max(.001, packets[-1]['time'] - start) if len(packets) > 1 else self.fps
        try:
            for index, packet in enumerate(packets):
                name = f'{index:05d}'
                (folder / 'frames' / (name + '.jpg')).write_bytes(packet['jpg'])
                (folder / 'masks' / (name + '.png')).write_bytes(packet['mask'])
                row = dict(packet['row'], clip_time=packet['time'] - start, image=f'frames/{name}.jpg', mask=f'masks/{name}.png')
                binary = cv2.imdecode(np.frombuffer(packet['mask'], np.uint8), cv2.IMREAD_GRAYSCALE)
                overlay = np.zeros((*binary.shape, 4), np.uint8)
                overlay[:, :, :3] = (255, 230, 0)
                overlay[:, :, 3] = (binary > 0).astype(np.uint8) * 255
                cv2.imwrite(str(folder / 'masks' / (name + '-overlay.png')), overlay)
                row['mask_overlay'] = f'masks/{name}-overlay.png'
                rows.append(row)
                if video_error is None:
                    image = cv2.imdecode(np.frombuffer(packet['jpg'], np.uint8), cv2.IMREAD_COLOR)
                    if video is None:
                        video = cv2.VideoWriter(str(folder / 'screen.avi'), cv2.VideoWriter_fourcc(*'MJPG'), max(1., video_fps), image.shape[1::-1])
                        if not video.isOpened():
                            video_error = 'MJPG encoder unavailable; individual JPEG frames remain available'
                    if video_error is None:
                        video.write(image)
        finally:
            if video is not None:
                video.release()
        report = dict(schema=1, classification=job['trigger']['classification'], trigger=job['trigger'], frames=len(rows), duration_seconds=packets[-1]['time'] - start, covered_pre_seconds=max(0., job['trigger']['anchor_time'] - start), frame_queue_drops_total=self.dropped, requested=sum(r['requested'] for r in job['events']), sent=sum(r['sent'] for r in job['events']), video_nominal_fps=video_fps, video_error=video_error, frame_encoding='JPEG quality ' + str(self.quality), mask_encoding='lossless ROI PNG', timestamps='frame time and clip_time in frames.json; nominal AVI FPS is approximate', limitations=['Counter stall/disappearance is a heuristic, not a confirmed death or success label.', 'Counter-shape changes support digits missing from the numeric reference set.', 'Background capture may drop frames; all decision rows in the selected interval are retained.'], metadata=self.metadata, settings=self.settings)
        report['analysis']=summarize_events(job['events'],job['inputs'])
        for name, data in [('report.json', report), ('frames.json', rows), ('inputs.json', job['inputs']), ('config.json', self.metadata['config'])]:
            (folder / name).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        (folder / 'events.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in job['events']), encoding='utf-8')
        (folder / 'index.html').write_text(viewer_html(rows, report), encoding='utf-8')
        if report['classification']=='manual_review':report['limitations'][0]='Manually marked clip; no automatic death judgement.'
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        self.saved.append(str(folder))
        self._index()
        print(('手动片段已保存：' if report['classification']=='manual_review' else '疑似失败片段已保存：') + str(folder), flush=True)

    def _index(self):
        import html
        links = []
        for folder in sorted(self.output.glob('failure-*'), reverse=True):
            if not (folder / 'report.json').is_file():
                continue
            report = json.loads((folder / 'report.json').read_text(encoding='utf-8'))
            label = f"{folder.name} | {report['trigger']['reason']} | {report['duration_seconds']:.2f}秒 | {report['frames']}帧"
            links.append(f'<li><a href="{folder.name}/index.html">{html.escape(label)}</a></li>')
        (self.output / 'index.html').write_text('<meta charset="utf-8"><title>跳绳失败片段</title><h1>跳绳保存片段</h1><p>按保存时间排列，请逐帧复核。</p><ul>' + ''.join(links) + '</ul>', encoding='utf-8')

    def stats(self):
        return dict(saved=list(self.saved), frame_queue_drops=self.dropped, errors=list(self.errors))

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.jobs.put(None)
        self.encoder.join()
        self.writer.join()


def summarize_events(events, inputs):
    downs=[e['time'] for e in inputs if e['type']=='key_down']
    holds=[];pressed=None
    for edge in inputs:
        if edge['type']=='key_down':pressed=edge['time']
        elif edge['type']=='key_up' and pressed is not None:
            holds.append((edge['time']-pressed)*1000);pressed=None
    counts=[r['count_reading'] for r in events if r.get('count_reading') is not None]
    return dict(decision_status_counts=dict(Counter(r['decision']['status'] for r in events)),
        template_switches=sum(a['decision'].get('template')!=b['decision'].get('template') for a,b in zip(events,events[1:])),
        stale_frames=sum(not r.get('fresh',True) for r in events),
        high_support_lost_frames=sum(r['decision'].get('columns',0)>=30 and r['decision']['status']=='lost' for r in events),
        live_requested_not_sent=sum(bool(r.get('live')) and r['requested'] and not r['sent'] for r in events),
        recognized_count_range=[min(counts),max(counts)] if counts else None,
        input_key_downs=len(downs),input_key_ups=sum(e['type']=='key_up' for e in inputs),
        maximum_complete_key_hold_ms=max(holds) if holds else None,
        minimum_key_down_interval_seconds=min((b-a for a,b in zip(downs,downs[1:])),default=None),
        open_key_down_at_clip_end=pressed is not None,
        interpretation='Summary is evidence for review, not an automatic attribution of failure. Key edges can cross clip boundaries.')


def viewer_html(rows, report):
    data = json.dumps(rows, ensure_ascii=False).replace('<', '\\u003c')
    reason = report['trigger']['reason']
    note = 'F10手动保存，未进行自动死亡判定' if report.get('classification')=='manual_review' else '计数停滞不是已确认死亡'
    return '''<!doctype html><meta charset="utf-8"><title>跳绳失败片段复核</title>
<style>body{font:16px system-ui;background:#141820;color:#e7ebf2;margin:24px}button,input{margin:8px}main{display:flex;gap:20px;flex-wrap:wrap}canvas{max-width:100%;height:auto;background:#000}section{flex:2;min-width:480px}pre{flex:1;min-width:320px;max-height:78vh;overflow:auto;white-space:pre-wrap}a{color:#8dd8ff}</style>
<h1>疑似失败片段复核</h1><p>REASON。REVIEW_NOTE；视频与图像使用JPEG编码，掩膜为无损PNG。</p>
<button id="back">上一帧</button><button id="play">播放</button><button id="next">下一帧</button><label><input id="overlay" type="checkbox" checked>显示YOLO掩膜</label><input id="seek" type="range" min="0" value="0"><span id="time"></span>
<p><a href="screen.avi">视频</a> · <a href="report.json">摘要</a> · <a href="config.json">配置</a> · <a href="events.jsonl">完整决策</a> · <a href="inputs.json">按键边沿</a></p><div id="summary" style="padding:16px;background:#242c39;line-height:1.9"></div><canvas id="timeline" height="65" style="width:100%;cursor:pointer"></canvas><p>时间轴：绿=观测/跳跃窗口，黄=外推，红=失联；白线=发送跳跃。点击定位，左右键逐帧。</p><main><section><canvas id="view"></canvas><h3>YOLO 原始二值掩膜（白色为输出，局部ROI）</h3><img id="rawmask" style="width:100%;background:black;image-rendering:pixelated"></section><pre id="params"></pre></main>
<script>const rows=DATA,$=id=>document.getElementById(id);let i=0,playing=false,timer=null,version=0;const canvas=$('view'),ctx=canvas.getContext('2d');$('seek').max=rows.length-1;
function draw(){const token=++version,r=rows[i];$('seek').value=i;$('time').textContent=`${i+1}/${rows.length} · ${r.clip_time.toFixed(3)}秒 · 源帧${r.frame}`;$('params').textContent=JSON.stringify(r,null,2);summary(r);$('rawmask').src=r.mask;const im=new Image();im.onload=()=>{if(token!==version)return;canvas.width=im.width;canvas.height=im.height;ctx.drawImage(im,0,0);if(!$('overlay').checked)return;const mask=new Image();mask.onload=()=>{if(token!==version)return;ctx.drawImage(mask,r.roi[0],r.roi[1]);};mask.src=r.mask_overlay;};im.src=r.image;}
function summary(r){const d=r.decision,f=(v,k=1)=>v==null?'无':(v*k).toFixed(3);const lines=[`状态：${d.status} | 掩膜像素：${r.pixels} | 有效列：${d.columns}/37（要求MIN_COLUMNS）`,`距上次观测支持：${f(d.missing_seconds,1000)} ms（失联阈值MAX_PREDICT_MS ms） | 当前形状误差：${f(d.accepted_shape_error)}（阈值MAX_SHAPE_ERROR）`,`已接受模板：${d.template} | 相位：${f(d.phase)} | 周期：${f(d.period,1000)} ms`,`下一跳跃窗口 ETA：${f(d.eta,1000)} ms | 请求：${r.requested} | 发送：${r.sent} | 按键保持：${r.key_pulse_active}`,`候选模板：${d.candidate_template} | 相位：${f(d.candidate_phase)} | 误差：${f(d.candidate_shape_error)}`,`等待确认：${d.pending_template} | 等待时长：${f(d.pending_seconds,1000)} ms（要求80 ms）`];$('summary').replaceChildren();lines.forEach(t=>{const e=document.createElement('div');e.textContent=t;$('summary').append(e)});const c=$('timeline');c.width=Math.max(600,c.clientWidth);const g=c.getContext('2d'),w=c.width/rows.length;rows.forEach((a,k)=>{g.fillStyle=a.decision.status==='lost'?'#ed6470':a.decision.status==='predicting'?'#dfb74b':'#4bc38a';g.fillRect(k*w,0,Math.ceil(w),55);if(a.sent){g.fillStyle='white';g.fillRect(k*w,0,2,55)}});g.strokeStyle='#72d9ff';g.lineWidth=3;g.strokeRect(i*w,0,Math.max(3,w),60)}
$('timeline').onclick=e=>{stop();i=Math.max(0,Math.min(rows.length-1,Math.floor(e.offsetX/$('timeline').clientWidth*rows.length)));draw()};
function stop(){playing=false;clearTimeout(timer);$('play').textContent='播放'}function step(n){stop();i=Math.max(0,Math.min(rows.length-1,i+n));draw()}function tick(){if(!playing||i>=rows.length-1){stop();return}const delay=Math.max(1,1000*(rows[i+1].time-rows[i].time));timer=setTimeout(()=>{i++;draw();tick()},delay)}$('back').onclick=()=>step(-1);$('next').onclick=()=>step(1);$('overlay').onchange=draw;$('seek').oninput=()=>{stop();i=+$('seek').value;draw()};$('play').onclick=()=>{if(playing)stop();else{if(i===rows.length-1)i=0;playing=true;$('play').textContent='暂停';draw();tick()}};document.onkeydown=e=>{if(e.key==='ArrowLeft')step(-1);if(e.key==='ArrowRight')step(1)};draw();</script>'''.replace('REASON', reason).replace('REVIEW_NOTE',note).replace('DATA', data).replace('MIN_COLUMNS', str(report.get('metadata', {}).get('config', {}).get('minimum_columns', 13))).replace('MAX_PREDICT_MS', str(round(report.get('metadata', {}).get('config', {}).get('max_predict_seconds', .25) * 1000))).replace('MAX_SHAPE_ERROR', str(report.get('metadata', {}).get('config', {}).get('max_shape_error', .025)))
