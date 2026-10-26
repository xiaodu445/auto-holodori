"""Qualitative review on an unused recording. No inferred accuracy from box counts."""
import os,json,cv2
from pathlib import Path
import numpy as np
from PIL import Image,ImageDraw,ImageFont
ROOT=Path(__file__).resolve().parents[2]
os.environ.setdefault('YOLO_CONFIG_DIR',str(ROOT/'learning/kitchen_points/ultralytics-config'))
from ultralytics import YOLO

run=ROOT/'learning/kitchen_yolo/runs/diagnostic-updates-20261022'
recording=ROOT/'runtime/kitchen/recordings/20261021-212757-320577'
snapshot=json.loads((ROOT/'learning/kitchen_yolo/datasets/5d82c7890e09/label-snapshot.json').read_text(encoding='utf-8'))
names={c['id']:c['name'] for c in snapshot['classes']['classes']}
font=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',14)
header=ImageFont.truetype('C:/Windows/Fonts/msyh.ttc',17)
model=YOLO(str(run/'weights/best.pt'));out=run/'independent-recording-review';out.mkdir(exist_ok=True)
cap=cv2.VideoCapture(str(recording/'screen.avi'));stamps=json.loads((recording/'timestamps.json').read_text(encoding='utf-8'));report=[];tiles=[]
for index in [350,523,850,1200]:
 cap.set(cv2.CAP_PROP_POS_FRAMES,index);ok,image=cap.read();assert ok
 h,w=image.shape[:2];l,t,r,b=snapshot['roi'];x0,y0,x1,y1=round(l*w),round(t*h),round(r*w),round(b*h)
 crop=image[y0:y1,x0:x1].copy()
 result=model.predict(crop,imgsz=640,rect=False,conf=.25,device=0,verbose=False)[0]
 rows=[]
 for j,box in enumerate(result.boxes):
  key=model.names[int(box.cls.item())];a,b,c,d=box.xyxy[0].cpu().tolist();kp=result.keypoints.data[j,0].cpu().tolist()
  rows.append(dict(class_id=key,name=names.get(key,key),score=float(box.conf.item()),bbox=[a+x0,b+y0,c+x0,d+y0],click=[kp[0]+x0,kp[1]+y0],point_score=kp[2]))
 def panel(threshold):
  annotated=Image.fromarray(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB));draw=ImageDraw.Draw(annotated)
  for row in rows:
   if row['score']<threshold:continue
   a,b,c,d=row['bbox'];a-=x0;c-=x0;b-=y0;d-=y0
   draw.rectangle((a,b,c,d),outline=(255,195,0),width=2)
   px,py=row['click'];px-=x0;py-=y0
   draw.line((px-6,py,px+6,py),fill=(255,0,0),width=2);draw.line((px,py-6,px,py+6),fill=(255,0,0),width=2)
   draw.text((max(0,a),max(0,b-18)),f'{row["name"]} {row["score"]:.2f}',font=font,fill=(255,240,70),stroke_width=2,stroke_fill=(0,0,0))
  return annotated
 left=Image.fromarray(cv2.cvtColor(crop,cv2.COLOR_BGR2RGB));right=panel(.25)
 pair=Image.new('RGB',(left.width*2,left.height+35),(25,25,25));pair.paste(left,(0,35));pair.paste(right,(left.width,35))
 draw=ImageDraw.Draw(pair);draw.text((10,7),f'未参与训练的录像 | 第{index}帧 | {stamps[index]["t"]:.1f}秒',font=header,fill='white')
 draw.text((left.width+10,7),f'预测阈值0.25 | {len(rows)}个候选 | 红十字为点击点',font=header,fill='white')
 pair.save(out/f'frame-{index:06d}.jpg');panel(.5).save(out/f'frame-{index:06d}-conf050.jpg')
 tiles.append(pair.resize((1200,round(pair.height*1200/pair.width))))
 report.append(dict(recording=recording.name,frame=index,t=stamps[index]['t'],scope='unused recording, qualitative only; no human ground truth',candidates=rows))
cap.release();canvas=Image.new('RGB',(1200,sum(im.height for im in tiles)));y=0
for im in tiles:canvas.paste(im,(0,y));y+=im.height
canvas.save(out/'overview.jpg');(out/'predictions.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps([dict(frame=r['frame'],candidates=len(r['candidates']),high_confidence=sum(c['score']>=.5 for c in r['candidates'])) for r in report],indent=2))
