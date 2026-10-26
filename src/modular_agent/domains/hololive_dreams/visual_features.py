"""Stable UI anchors in normalized layout zones; independent of actor and dialogue text."""
from functools import lru_cache
from pathlib import Path
import cv2
import numpy as np
import json

# Reference coordinates include the 38px title bar. Only small, stable glyphs.
SPECS=[
 ('achievement_rank','0fa79e05-fa45-4357-9fbd-0aec03562164',(603,83,752,108),(.40,.07,.80,.18)),
 ('achievement_title','8aa2acca-3e60-4c4d-9117-2bfada427150',(99,86,157,116),(0,.06,.20,.20)),
 ('achievement_claim_text','0fa79e05-fa45-4357-9fbd-0aec03562164',(1070,665,1178,692),(.72,.80,.97,.96)),
 ('notification_title','347c7a2a-03dd-4724-9d90-5f9a5c020577',(44,80,145,111),(0,.04,.22,.20)),
 ('option_mouse','7be9e448-7b6f-4a25-8a4f-fc705a07467d',(768,391,794,423),(.55,.35,.75,.72)),
 ('option_e','7be9e448-7b6f-4a25-8a4f-fc705a07467d',(798,392,825,421),(.55,.35,.75,.72)),
 ('reward_title','176ca6d9-7836-4e3e-867b-85ad052919de',(565,100,720,155),(.25,.04,.75,.28)),
 ('rank_title','e1575559-6b3b-4a78-b537-f4db47e786f6',(711,154,1130,224),(.40,.08,.98,.35)),
 ('hud_activity','9453cc6a-f96b-4d2e-9403-25b833c8a875',(728,111,764,132),(.52,.05,.92,.22)),
 ('hud_game','9453cc6a-f96b-4d2e-9403-25b833c8a875',(802,111,837,132),(.52,.05,.92,.22)),
 ('hud_stage','9453cc6a-f96b-4d2e-9403-25b833c8a875',(874,111,909,132),(.52,.05,.92,.22)),
 ('hud_task','9453cc6a-f96b-4d2e-9403-25b833c8a875',(945,111,982,132),(.52,.05,.92,.22)),
 ('hud_achievement','9453cc6a-f96b-4d2e-9403-25b833c8a875',(1017,111,1054,132),(.52,.05,.92,.22)),
 ('dialogue_e','ab709d1b-1754-4fcc-9222-766a22aa604a',(968,704,995,731),(.65,.83,.97,1.0)),
 ('dialogue_next','ab709d1b-1754-4fcc-9222-766a22aa604a',(1011,728,1036,745),(.65,.86,.97,1.0)),
 ('map_pin','8e6f38a1-d645-4bb5-8941-cd90ac89b6d6',(37,56,87,118),(.01,.04,.11,.20)),
 ('map_label','8e6f38a1-d645-4bb5-8941-cd90ac89b6d6',(105,57,149,78),(.06,.04,.18,.14)),
]
@lru_cache(maxsize=4)
def references(root):
 folder=Path(root)/'domains/hololive_dreams/data/ui_features'
 result=[]
 manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
 for item in manifest['features']:
  mode=item['mode']
  patch=cv2.imdecode(np.fromfile(str(folder/item.get('foreground',item['image'])),np.uint8),0)
  mask=cv2.imdecode(np.fromfile(str(folder/item['mask']),np.uint8),0) if mode=='foreground' else None
  result.append((item['name'],patch,item['zone'],mask))
 return result

def foreground(image):
 hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
 return np.uint8(((hsv[:,:,1]<85)&(hsv[:,:,2]>185))|((hsv[:,:,0]>=14)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>75)&(hsv[:,:,2]>175)))*255

def extract(image,origin,root):
 if image.ndim!=3 or image.shape[1]<500 or image.shape[0]<300: return {}
 scale=1264/image.shape[1]
 normalized=cv2.resize(image,None,fx=scale,fy=scale)
 gray=cv2.cvtColor(normalized,cv2.COLOR_BGR2GRAY)
 binary=foreground(normalized)
 h,w=gray.shape;anchors={};scores={}
 for name,patch,zone,mask in references(str(root)):
  x,y,r,b=map(int,(zone[0]*w,zone[1]*h,zone[2]*w,zone[3]*h))
  roi=(binary if mask is not None else gray)[y:b,x:r];best=(-1,None)
  # Wide RANK UP glyphs lose correlation with a 1-3% scale mismatch.
  # Keep the strict acceptance threshold; search the missing intermediate scales.
  factors=(.94,.95,.96,.97,.98,.99,1.0,1.01,1.02,1.03,1.04,1.05,1.06) if name=='rank_title' else (.94,1.0,1.06)
  for factor in factors:
   p=cv2.resize(patch,None,fx=factor,fy=factor)
   ph,pw=p.shape
   if roi.shape[0]<ph or roi.shape[1]<pw: continue
   if mask is not None:
    m=cv2.resize(mask,(pw,ph),interpolation=cv2.INTER_NEAREST)
    response=1-cv2.matchTemplate(roi,p,cv2.TM_SQDIFF_NORMED,mask=m)
    response=np.nan_to_num(response,nan=-1,posinf=-1,neginf=-1)
   else: response=cv2.matchTemplate(roi,p,cv2.TM_CCOEFF_NORMED)
   _,score,_,point=cv2.minMaxLoc(response)
   if score>best[0]: best=(score,(point[0]+x,point[1]+y,pw,ph))
  scores[name]=round(best[0],3)
  threshold=.82 if mask is not None else (.80 if name=='dialogue_next' else (.63 if name.startswith('hud_') else .67))
  if best[0]>=threshold:
   bx,by,bw,bh=best[1]
   anchors[name]={'score':round(best[0],3),'bounds':dict(x=origin[0]+round(bx/scale),y=origin[1]+round(by/scale),width=round(bw/scale),height=round(bh/scale))}
 # Triangle alone is too generic; require separate E, both in the bottom band.
 dialogue=bool('dialogue_e' in anchors and 'dialogue_next' in anchors)
 options=bool(scores.get('option_mouse',0)>.85 and scores.get('option_e',0)>.85)
 gift_prompt=False
 if 'gift_label' in anchors and 'option_e' in anchors:
  gb=anchors['gift_label']['bounds'];eb=anchors['option_e']['bounds']
  gift_prompt=bool(scores['option_e']>.80 and gb['x']>eb['x'] and abs(gb['y']-eb['y'])<22/scale)
 wheel_prompt=False
 if 'scratch_label' in anchors and 'option_e' in anchors:
  sb=anchors['scratch_label']['bounds'];eb=anchors['option_e']['bounds']
  wheel_prompt=bool(scores['option_e']>.80 and sb['x']>eb['x'] and abs(sb['y']-eb['y'])<22/scale)
 hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
 central=hsv[int(image.shape[0]*.30):int(image.shape[0]*.70)]
 cyan_fraction=float(np.mean((central[:,:,0]>=75)&(central[:,:,0]<=100)&(central[:,:,1]>=60)&(central[:,:,2]>=140)))
 hud=[anchors[n]['bounds'] for n in anchors if n.startswith('hud_')]
 aligned_hud=len(hud) if hud and max(a['y'] for a in hud)-min(a['y'] for a in hud)<12/scale else 0
 icons=[anchors[n]['bounds'] for n in anchors if n.startswith('icon_')]
 # Outlier peaks must not invalidate the other independent HUD anchors.
 icon_count=max((sum(abs(a['y']-b['y'])<=18/scale for b in icons) for a in icons),default=0)
 world_support=sum(n in anchors for n in ('world_camera','world_jump'))
 if icon_count>=3 and world_support: aligned_hud=max(aligned_hud,icon_count)
 achievement_badge=None
 badge_hud=aligned_hud>=3 or (world_support>=1 and sum(scores.get(n,0)>.75 for n in ('icon_activity','icon_game','icon_stage','icon_task','icon_achievement'))>=4)
 if badge_hud:
  # Independent fixed HUD region, not dependent on the trophy mask including
  # the badge itself (which can lower its match score).
  ih,iw=image.shape[:2]
  badge=hsv[round(ih*.075):round(ih*.14),round(iw*.827):round(iw*.865)]
  if badge.size:
   pink=np.uint8((badge[:,:,0]>=145)&(badge[:,:,0]<=179)&(badge[:,:,1]>80)&(badge[:,:,2]>170))*255
   contours,_=cv2.findContours(pink,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
   achievement_badge=any(cv2.contourArea(c)>=10/(scale*scale) for c in contours)
 lower=hsv[int(image.shape[0]*.65):int(image.shape[0]*.85)]
 lower_cyan=float(np.mean((lower[:,:,0]>=75)&(lower[:,:,0]<=100)&(lower[:,:,1]>=60)&(lower[:,:,2]>=140)))
 ticket=hsv[int(image.shape[0]*.28):int(image.shape[0]*.76),int(image.shape[1]*.20):int(image.shape[1]*.80)]
 pink_fraction=float(np.mean((ticket[:,:,0]>=155)&(ticket[:,:,0]<=179)&(ticket[:,:,1]>65)&(ticket[:,:,2]>140)))
 from .map_view import detect_zoom
 is_map=bool('map_pin' in anchors and 'map_label' in anchors)
 zoom=detect_zoom(image,origin) if is_map else None
 notice_panel=scores.get('notification_title',0)>.82
 notice_rows=0
 if notice_panel:
  panel=hsv[int(image.shape[0]*.16):int(image.shape[0]*.88),:int(image.shape[1]*.40)]
  white=np.uint8((panel[:,:,1]<65)&(panel[:,:,2]>215))*255
  contours,_=cv2.findContours(white,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
  for contour in contours:
   _,_,cw,ch=cv2.boundingRect(contour)
   if cw>image.shape[1]*.08 and image.shape[0]*.025<ch<image.shape[0]*.14 and cv2.contourArea(contour)>.55*cw*ch:notice_rows+=1
 return {'anchors':anchors,'scores':scores,'dialogue':dialogue,
         'options':options,
         'gift_prompt':gift_prompt,
         'wheel_prompt':wheel_prompt,
         'scratch_ticket':bool(scores.get('scratch_open',0)>.90 and pink_fraction>.12),
         'achievement_detail':bool(scores.get('achievement_rank',0)>.82 and scores.get('achievement_claim_text',0)>.82),
         'achievement_list':bool(scores.get('achievement_title',0)>.92 and scores.get('achievement_rank',0)<.82),
         'notification_panel':notice_panel,'notification_rows':notice_rows,
         'reward':bool('reward_title' in anchors and cyan_fraction>.35),
         'rank_up':bool(scores.get('rank_title',0)>.88 and lower_cyan>.25),
         'hud_count':aligned_hud,
         'achievement_badge':achievement_badge,
         'icon_count':icon_count,'world_support':world_support,
         'map':is_map,'map_zoom':zoom}
