"""Same-frame semantic + colour evidence for explicitly registered popups."""
TITLES={'达成奖励','获得奖励','奖励领取','领取完成','任务完成','演出结果'}
LABELS={'确定','继续','下一步','关闭'}
FORBIDDEN=('购买','充值','兑换','删除','确认成员','决定成员')

def annotate(report,image,origin):
 words=[''.join(t.get('text','').split()) for t in report.texts]
 if any(any(w in s for w in FORBIDDEN) for s in words):return
 title=next((s for s in words if s in TITLES),None)
 if not title:return
 for text in report.texts:
  label=''.join(text.get('text','').split())
  close=label in ('×','X','x')
  if label not in LABELS and not close:continue
  if text.get('confidence',0)<.9:continue
  if close:
   f=report.frame['bounds'];q=text['bounds']
   x=(q['x']+q['width']/2-f['x'])/f['width'];y=(q['y']+q['height']/2-f['y'])/f['height']
   if not (.60<=x<=.95 and .06<=y<=.35):continue
   label='关闭'
  shape=next((b for b in report.buttons if b.get('id') in text.get('button_ids',[]) and b.get('enabled') is not False),None)
  if shape is None:continue
  q=text['bounds'];x=q['x']-origin[0];y=q['y']-origin[1]
  p=image[max(0,y):y+q['height'],max(0,x):x+q['width']]
  if p.size==0:continue
  blue=(p[:,:,0]>220)&(p[:,:,1]>160)&(p[:,:,2]<100)
  white=(p.min(axis=2)>=230)&((p.max(axis=2).astype('int16')-p.min(axis=2))<25)
  if float(blue.mean())>.25 and float(white.mean())>.08:
   shape.update(label=label,bounds=q,enabled=True,semantic_confirmed=True,
                confidence=text['confidence'],source='registered_popup_text_and_colour')
   report.frame['confirmed_popup']=title
