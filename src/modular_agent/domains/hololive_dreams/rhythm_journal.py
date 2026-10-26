"""Rhythm-only compact logs and narrowly scoped, age-based retention."""
import json,re,time,threading,shutil,stat,os
from collections import deque
from pathlib import Path
from .daily_journal import DailyJournal

def compact_result(result):
    return {k:v for k,v in result.items() if k not in ('rows','settings','scheduled_events_pending_log')}

class RhythmJournal(DailyJournal):
    max_bytes=4*1024*1024
    def __init__(self,root,**kwargs):
        super().__init__(root,**kwargs)
        self._lock=threading.RLock();self._last_heartbeat=-float('inf');self._last_ready=None;self._songs=deque()
    def __call__(self,event,**payload):
        with self._lock:
            if event=='rhythm_diagnostic':
                now=time.monotonic();ready=payload.get('gate_ready')
                if now-self._last_heartbeat<30 and ready==self._last_ready:return
                self._last_heartbeat=now;self._last_ready=ready
            current=self.directory/'events.jsonl'
            if current.exists() and current.stat().st_size>=self.max_bytes:
                old=self.directory/'events.2.jsonl';old.unlink(missing_ok=True)
                previous=self.directory/'events.1.jsonl'
                if previous.exists():previous.replace(old)
                current.replace(previous)
            super().__call__(event,**payload)
    def song_directory(self,name):
        path=self.directory/name
        if path.parent.resolve()!=self.directory.resolve() or not re.fullmatch(r'song-diagnostic-\d+-\d+',name):raise ValueError('invalid diagnostic directory')
        path.mkdir();self._songs.append(path)
        if len(self._songs)>3:
            old=self._songs.popleft()
            if old.resolve().parent!=self.directory.resolve() or old.is_symlink() or old.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:return path
            for image in [*old.glob('gate-*.jpg'),old/'stopped-frame.jpg']:
                if image.is_file() and not image.is_symlink() and image.resolve().parent==old.resolve():image.unlink()
        return path

def _safe_files(folder):
    def reparse(p):return bool(p.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
    if folder.is_symlink() or reparse(folder):raise ValueError('linked log directory')
    files=[]
    def fail(error):raise error
    for parent,dirs,names in os.walk(folder,followlinks=False,onerror=fail):
        for name in dirs+names:
            path=Path(parent)/name
            if path.is_symlink() or reparse(path):raise ValueError('linked child')
        files.extend(Path(parent)/name for name in names)
    return files

def cleanup_old_rhythm_logs(root,*,now=None,days=7,keep=3):
    """Call only after acquiring the rhythm session lock. Never touch other tasks."""
    root=Path(root).resolve();now=time.time() if now is None else now
    report={'removed':0,'bytes_removed':0,'errors':[]}
    if not root.is_dir():return report
    candidates=[]
    for folder in root.iterdir():
        if not re.fullmatch(r'\d{8}-\d{6}-[a-f0-9]{8}',folder.name):continue
        try:
            if not folder.is_dir() or folder.is_symlink() or folder.resolve().parent!=root:continue
            # Do not follow junctions, including an events.jsonl link.
            files=_safe_files(folder)
            first=folder/'events.jsonl'
            if not first.is_file():continue
            with first.open(encoding='utf-8-sig') as stream:line=stream.readline(131072)
            # Rotated new-format logs carry an explicit rhythm marker.
            marker=folder/'rhythm-log-policy.json'
            rhythm=json.loads(line).get('event')=='rhythm_settings'
            if not rhythm and marker.is_file():rhythm=json.loads(marker.read_text(encoding='utf-8')).get('kind')=='hololive-rhythm'
            if not rhythm:continue
            latest=max([folder.stat().st_mtime]+[p.stat().st_mtime for p in files])
            candidates.append((latest,folder,files))
        except (OSError,ValueError):continue
    candidates.sort(key=lambda row:row[0],reverse=True)
    for latest,folder,files in candidates[keep:]:
        if latest>=now-days*86400:continue
        try:
            if folder.resolve().parent!=root:continue
            checked=_safe_files(folder)
            if max([folder.stat().st_mtime]+[p.stat().st_mtime for p in checked])>=now-days*86400:continue
            size=sum(p.stat().st_size for p in checked)
            shutil.rmtree(folder)
            report['removed']+=1;report['bytes_removed']+=size
        except (OSError,ValueError) as error:
            if len(report['errors'])<5:report['errors'].append(str(error))
    return report
