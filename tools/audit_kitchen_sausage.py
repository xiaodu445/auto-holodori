"""Generate read-only candidate sheets from historical video; candidates need review."""
import sys,json,cv2,numpy as np
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from modular_agent.realtime.kitchen_ui import HudReader,TRAY_RECTS,crop_rect,descriptor
out=ROOT/'runtime/kitchen/tray-audit-sausage-20261024';out.mkdir(parents=True,exist_ok=True)
reader=HudReader(ROOT/'data/kitchen/ui-icons');catalog=json.loads((ROOT/'data/kitchen/manual-classes.json').read_text(encoding='utf-8'))['classes'];keys=[x['id'] for x in catalog];best={k:[] for k in keys};allrows=[]
folders=list((ROOT/'runtime/kitchen/recordings').glob('*'))+list((ROOT/'runtime/kitchen/sessions').glob('*'))
for folder in folders:
 video=folder/'screen.avi'
 if not video.exists():continue
 cap=cv2.VideoCapture(str(video));count=int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
 for frame in np.linspace(0,max(0,count-1),min(65,count),dtype=int):
  cap.set(cv2.CAP_PROP_POS_FRAMES,int(frame));ok,image=cap.read()
  if not ok:continue
  for slot,rect in enumerate(TRAY_RECTS):
   patch=crop_rect(image,rect);feature=descriptor(patch)
   if feature is None:continue
   key='IANGCHANG';score=max(float(f@feature) for f,label in zip(reader.features,reader.labels) if label==key);margin=0
   if key not in best:continue
   row=dict(source=str(folder.relative_to(ROOT)),frame=int(frame),slot=slot,key=key,score=score,margin=margin)
   candidates=best[key]
   if any(r['source']==row['source'] and abs(r['frame']-row['frame'])<80 for r,_ in candidates):continue
   candidates.append((row,patch));candidates.sort(key=lambda a:-a[0]['score']);del candidates[20:]
 cap.release()
 print(folder.name,flush=True)
rows=[];sheet=np.full((len(keys)*90,2200,3),245,np.uint8)
for i,key in enumerate(keys):
 cv2.putText(sheet,key,(4,i*90+20),cv2.FONT_HERSHEY_SIMPLEX,.4,(0,0,0),1)
 for j,(row,patch) in enumerate(best[key]):
  n=len(rows);row['candidate']=n;rows.append(row);cv2.imwrite(str(out/f'candidate-{n}.png'),patch)
  sheet[i*90+22:i*90+87,150+j*100:245+j*100]=cv2.resize(patch,(95,65))
  cv2.putText(sheet,f"{n}: {row['score']:.2f}",(150+j*100,i*90+15),cv2.FONT_HERSHEY_SIMPLEX,.35,(0,0,0),1)
cv2.imwrite(str(out/'candidates.png'),sheet);(out/'candidates.json').write_text(json.dumps(rows,indent=2),encoding='utf-8')
