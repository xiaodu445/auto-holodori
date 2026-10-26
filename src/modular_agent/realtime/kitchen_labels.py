"""Point labels tied to immutable video timestamps. No game input."""
import copy
import hashlib
import json
from pathlib import Path
import uuid


def atomic_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
        temporary.replace(path)
    finally:
        if temporary.exists():temporary.unlink()


class LabelStore:
    def __init__(self,recording,labels_dir=None):
        self.recording=Path(recording)
        raw=(self.recording/'timestamps.json').read_bytes()
        self.stamps=json.loads(raw)
        self.labels_dir=Path(labels_dir) if labels_dir is not None else self.recording/'point-labels'
        self.path=self.labels_dir/'annotations.json'
        aliases_path=self.labels_dir/'class-aliases.json'
        self.aliases=json.loads(aliases_path.read_text(encoding='utf-8')) if aliases_path.exists() else {}
        digest=hashlib.sha256(raw).hexdigest()
        self.data=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else dict(
            schema_version=1,timestamps_sha256=digest,recording_id=self.recording.name,
            coordinate_system='full_video_pixels',roi=[.20,.21,.78,.79],frames={})
        if self.data['timestamps_sha256']!=digest:raise ValueError('标签与录像时间戳不匹配')
        supplement=self.path.with_name('assistant-annotations.json')
        if supplement.exists():
            extra=json.loads(supplement.read_text(encoding='utf-8'))
            if extra['timestamps_sha256']!=digest:raise ValueError('补充标签与录像不匹配')
            for key,value in extra['frames'].items():
                self.data['frames'].setdefault(key,value)
        self.normalize_classes(self.data)
        self.baseline=copy.deepcopy(self.data)


    def normalize_classes(self,data):
        for frame in data.get('frames',{}).values():
            for point in frame.get('points',[]):
                point['class_id']=self.aliases.get(point['class_id'],point['class_id'])

    def frame(self,index,width,height):
        if not 0<=index<len(self.stamps):raise ValueError('invalid frame index')
        value=self.data['frames'].setdefault(str(index),dict(video_index=index,t=self.stamps[index]['t'],
            width=width,height=height,complete=False,points=[],ignore_regions=[]))
        if (value['width'],value['height'])!=(width,height):raise ValueError('frame size mismatch')
        return value

    def add_point(self,frame,class_id,x,y):
        if not class_id or not 0<=x<frame['width'] or not 0<=y<frame['height']:raise ValueError('invalid point')
        point=dict(instance_id=uuid.uuid4().hex[:12],class_id=self.aliases.get(class_id,class_id),x=int(x),y=int(y))
        frame['points'].append(point);frame['complete']=False
        return point

    def set_bbox(self,frame,instance_id,box):
        x0,y0,x1,y1=map(int,box)
        if not 0<=x0<x1<=frame['width'] or not 0<=y0<y1<=frame['height']:
            raise ValueError('实例框超出画面或为空')
        point=next((p for p in frame['points'] if p['instance_id']==instance_id),None)
        if point is None:raise ValueError('找不到选中的实例')
        if not x0<=point['x']<x1 or not y0<=point['y']<y1:
            raise ValueError('实例框必须包含对应点击点')
        point['bbox']=[x0,y0,x1,y1]
        point['bbox_source']='user_drawn_visible_extent'

    def add_ignore(self,frame,box):
        x0,y0,x1,y1=box
        if not 0<=x0<x1<=frame['width'] or not 0<=y0<y1<=frame['height']:raise ValueError('invalid ignore region')
        frame['ignore_regions'].append(list(map(int,box)));frame['complete']=False

    def save(self):
        self.normalize_classes(self.data)
        # Merge only locally changed frames, retaining unrelated external edits.
        merged=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else copy.deepcopy(self.data)
        self.normalize_classes(merged)
        if merged['timestamps_sha256']!=self.data['timestamps_sha256']:raise ValueError('录像在保存前发生变化')
        for key,value in self.data['frames'].items():
            if key not in merged['frames'] or value!=self.baseline['frames'].get(key):
                remote=merged['frames'].get(key)
                base=self.baseline['frames'].get(key)
                if remote is not None and base is not None and remote!=base and remote!=value:
                    conflict=self.path.with_name('conflict-'+uuid.uuid4().hex+'.json')
                    atomic_json(conflict,self.data)
                    raise RuntimeError('同一帧被其他窗口修改；本地副本已保存至 '+str(conflict))
                merged['frames'][key]=copy.deepcopy(value)
        if self.data['roi']!=self.baseline['roi']:merged['roi']=self.data['roi']
        atomic_json(self.path,merged)
        self.baseline=copy.deepcopy(self.data)


    def export(self,classes):
        import cv2
        output=self.labels_dir/'dataset'
        output.mkdir(parents=True,exist_ok=True)
        cap=cv2.VideoCapture(str(self.recording/'screen.avi'));rows=[]
        try:
            for frame in self.data['frames'].values():
                if not frame['complete']:continue
                if any(p['class_id'] not in classes for p in frame['points']):raise ValueError('unknown class in labels')
                i=frame['video_index'];cap.set(cv2.CAP_PROP_POS_FRAMES,i);ok,image=cap.read()
                if not ok:raise RuntimeError(f'cannot decode frame {i}')
                if image.shape[1::-1]!=(frame['width'],frame['height']):raise ValueError('export size mismatch')
                name=f'frame-{i:06d}.png'
                if not cv2.imwrite(str(output/name),image):raise RuntimeError('image export failed')
                rows.append(dict(image=name,recording_id=self.recording.name,**frame))
            atomic_json(output/'manifest.json',dict(schema_version=1,classes=classes,
                coordinate_system='full_video_pixels',roi=self.data['roi'],frames=rows,
                split_policy='split by independent recording; no random adjacent-frame split',
                note='PNG decoded from lossy MJPG; points are manually assigned, not verified game hitboxes'))
        finally:cap.release()
        return output,len(rows)
