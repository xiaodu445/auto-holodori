"""Incremental self-contained review backup; never deletes source recordings."""
import json,shutil,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DEST=ROOT/'data/kitchen/review-archive'
def archive():
    DEST.mkdir(parents=True,exist_ok=True);missing=[];notes=[]
    for path in sorted((ROOT/'runtime/kitchen/sessions').glob('*/review-issues.json')):
        source=path.parent
        rows=json.loads(path.read_text(encoding='utf-8'))
        events=[json.loads(line) for line in (source/'events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()] if (source/'events.jsonl').exists() else []
        for issue in rows:
            target=DEST/source.name/str(issue['id']);target.mkdir(parents=True,exist_ok=True)
            (target/'issue.json').write_text(json.dumps(issue,ensure_ascii=False,indent=2),encoding='utf-8')
            screenshot=source/issue.get('screenshot','missing.png')
            if screenshot.is_file():shutil.copy2(screenshot,target/'frame.png')
            elif not (target/'frame.png').exists():missing.append(str(screenshot))
            t=issue.get('time',0)
            context=[event for event in events if abs(event.get('t',0)-t)<=2]
            (target/'events-context.json').write_text(json.dumps(context,ensure_ascii=False,indent=2),encoding='utf-8')
            stamps=source/'timestamps.json'
            if stamps.exists():
                entries=json.loads(stamps.read_text(encoding='utf-8'))
                row=next((r for r in entries if r.get('video_index')==issue.get('frame_index')),None)
                (target/'source-frame.json').write_text(json.dumps(row,ensure_ascii=False,indent=2),encoding='utf-8')
    summary=ROOT/'runtime/kitchen/review-summary'
    if summary.exists():shutil.copytree(summary,DEST/'previous-summaries',dirs_exist_ok=True)
    for path in sorted(DEST.glob('*/*/issue.json')):
        issue=json.loads(path.read_text(encoding='utf-8'));notes.append(dict(session=path.parents[1].name,id=issue['id'],time=issue.get('time'),kind=issue.get('kind'),note=issue.get('note'),folder=str(path.parent.relative_to(DEST)),has_image=(path.parent/'frame.png').exists()))
    report=dict(archived_notes=len(notes),missing_images=missing,notes=notes)
    (DEST/'index.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    text=['# 厨房批注独立归档','', '该目录独立于sessions和recordings；删除录像前请保留此目录。每条批注包含原始批注/诊断、截图、前后2秒事件和来源帧信息。历史汇总保存在previous-summaries，不代表其全部旧截图仍可恢复。','']
    for row in notes:text.append(f"- {row['session']} / {row['time']:.3f}秒：{row['note']}（{row['folder']}）")
    (DEST/'README.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    return report
if __name__=='__main__':
    report=archive();print(json.dumps(dict(archived_notes=report['archived_notes'],missing_images=report['missing_images'],destination=str(DEST)),ensure_ascii=True))
