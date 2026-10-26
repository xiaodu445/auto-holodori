"""Collect user review notes and a separate raw-frame annotation album. No auto labels."""
import json,cv2,sys
from pathlib import Path
from collections import Counter
from modular_agent.realtime.kitchen_labels import LabelStore,atomic_json
ROOT=Path(__file__).resolve().parents[1]
VISUAL=('未检测','没检测','没检出','漏','误判','识别成','检测错','检测出错','识别错','不识别','不检测','认错')

def collect():
    grouped={};ignored=[];raw=0
    for path in sorted((ROOT/'runtime/kitchen/sessions').glob('*/review-issues.json')):
        for issue in json.loads(path.read_text(encoding='utf-8')):
            raw+=1
            if issue.get('review_status')=='dismissed_by_user':ignored.append(issue['id']);continue
            key=(path.parent.name,issue['frame_index'])
            case=grouped.setdefault(key,dict(session=key[0],frame=key[1],time=issue['time'],notes=[],issue_ids=[],image=str((path.parent/issue['screenshot']).resolve())))
            if issue['note'] not in case['notes']:case['notes'].append(issue['note'])
            case['issue_ids'].append(issue['id'])
    cases=sorted(grouped.values(),key=lambda c:(c['session'],c['frame']))
    for case in cases:
        note='；'.join(case['notes']);case['training_candidate']=any(token in note for token in VISUAL)
        case['category']='识别/补训练' if case['training_candidate'] else '时序' if any(token in note for token in ('截图','路径','开始检测','开始推理')) else '台账/策略'
    return dict(raw_notes=raw,ignored=ignored,unique_cases=len(cases),training_frames=sum(c['training_candidate'] for c in cases),cases=cases)

def make_album(report,name):
    sources=[c for c in report['cases'] if c['training_candidate']]
    recording=ROOT/'runtime/kitchen/recordings'/name;workspace=ROOT/'runtime/kitchen/manual-labeling'/name
    if recording.exists():raise ValueError('不覆盖已有相册：'+str(recording))
    recording.mkdir(parents=True);(workspace/'frames').mkdir(parents=True,exist_ok=True)
    image=cv2.imread(sources[0]['image']);h,w=image.shape[:2]
    writer=cv2.VideoWriter(str(recording/'screen.avi'),cv2.VideoWriter_fourcc(*'MJPG'),1,(w,h));assert writer.isOpened()
    stamps=[]
    try:
        for index,case in enumerate(sources):
            image=cv2.imread(case['image'])
            if image is None or image.shape[:2]!=(h,w):raise ValueError('源图片尺寸/读取失败：'+case['image'])
            writer.write(image);cv2.imwrite(str(workspace/'frames'/f'frame-{index:06d}.png'),image)
            stamps.append(dict(video_index=index,frame_id=index,t=float(index),source_session=case['session'],source_frame=case['frame'],source_time=case['time']))
            case['album_index']=index
    finally:writer.release()
    atomic_json(recording/'timestamps.json',stamps);atomic_json(recording/'summary.json',dict(mode='review_album',frames=len(sources),sources=sources))
    store=LabelStore(recording,workspace)
    for index in range(len(sources)):store.frame(index,w,h)
    store.save()
    atomic_json(workspace/'selection.json',dict(schema_version=1,recording_id=name,timestamps_sha256=store.data['timestamps_sha256'],selected_by='deduplicated_user_review_notes',frames=[dict(video_index=i,t=float(i),reason='；'.join(c['notes'])) for i,c in enumerate(sources)]))
    atomic_json(workspace/'source-index.json',sources)
    launcher=ROOT/'kitchen_review_label.cmd'
    launcher.write_text('@echo off\nsetlocal\ncd /d "%~dp0"\nset "PYTHONPATH=%~dp0src"\nset "PYTHONIOENCODING=utf-8"\nchcp 65001 >nul\n"%~dp0.conda\\python.exe" tools\\kitchen_point_label.py --recording "runtime/kitchen/recordings/'+name+'" --labels-dir "runtime/kitchen/manual-labeling/'+name+'" --classes "data/kitchen/manual-classes.json" --box-mode\npause\n',encoding='utf-8')
    launcher.write_text(launcher.read_text(encoding='utf-8').replace('\\\\','\\'),encoding='utf-8')
    return recording,workspace

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    report=collect();name=sys.argv[1] if len(sys.argv)>1 else 'review-errors-20261024-merged'
    recording,workspace=make_album(report,name)
    report.update(album=str(recording),labels=str(workspace))
    folder=ROOT/'runtime/kitchen/review-summary';folder.mkdir(exist_ok=True)
    atomic_json(folder/'cases-20261024.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='cases'},ensure_ascii=False,indent=2))
