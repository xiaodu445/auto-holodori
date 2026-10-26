"""Small, layout-constrained claim searches; preserve desktop coordinates."""
GROUPS=[
 (('claim_pass_page','claim_pass_page_sample','claim_achievement_page','claim_event_carousel','claim_event_page'),(0,.04,.24,.24)),
 (('claim_pt_limit',),(.35,.30,.90,.43)),
 (('claim_close',),(.92,.04,.99,.17)),
 (('claim_tasks_tab','claim_pass_tab'),(.08,.21,.40,.30)),
 (('claim_daily_tab','claim_weekly_tab','claim_season_tab'),(.09,.34,.21,.69)),
 (('claim_event_daily','claim_event_free'),(.33,.19,.87,.29)),
 (('claim_all','claim_all_task'),(.72,.80,.97,.96)),
 (('claim_one',),(.77,.26,.95,.82)),
 (('claim_available',),(.82,.22,.96,.99)),
 (('claim_event_home','claim_event_home_sample'),(.90,.50,.98,.70)),
 (('claim_event_go',),(.80,.83,.96,.96)),
]

def match_claims(matcher,image,environment,origin,features,requested,scales=None,threshold=None):
 from .claim_tasks import annotate_enabled
 if any(features.get(n) for n in ('reward','rank_up','dialogue')):
  return [],{'mode':'structure_only','regions':0}
 h,w=image.shape[:2];matches=[];diagnostics=[];regions=0
 for names,zone in GROUPS:
  selected=[n for n in names if n in requested]
  if not selected:continue
  x,y,r,b=map(int,(zone[0]*w,zone[1]*h,zone[2]*w,zone[3]*h))
  factors=(.96,.98,1.0,1.02) if selected==['claim_available'] else scales
  matches.extend(matcher.match(image[y:b,x:r],environment,(origin[0]+x,origin[1]+y),
                  template_names=selected,scales=factors,threshold=max(.92,threshold or .92)))
  diagnostics.extend(getattr(matcher,'last_diagnostics',[]));regions+=1
 matcher.last_diagnostics=diagnostics
 import cv2
 import numpy as np
 def pink(zone):
  a,c,d,e=zone;p=image[int(c*h):int(e*h),int(a*w):int(d*w)]
  if not p.size:return False
  hsv=cv2.cvtColor(p,cv2.COLOR_BGR2HSV)
  mask=np.uint8((hsv[:,:,0]>=145)&(hsv[:,:,0]<=179)&(hsv[:,:,1]>80)&(hsv[:,:,2]>170))
  return int(mask.sum())>=max(8,int(w*h*.00002))
 info={'mode':'regional','regions':regions}
 if any(n.startswith('claim_event') for n in requested):
  info['event_card']=cv2.resize(image[int(h*.25):int(h*.78),int(w*.25):int(w*.78)],(12,8),interpolation=cv2.INTER_AREA).flatten().tolist()
  info['activity_badge']=pink((.59,.075,.63,.145))
 for m in matches:
  if m['label'] in ('claim_event_home','claim_event_home_sample'):
   q=m['bounds'];x=(q['x']-origin[0])/w;y=(q['y']-origin[1])/h
   m['notification_badge']=pink((max(.88,x-.015),max(.40,y-.10),.99,min(.72,y+.03)))
 return annotate_enabled(sorted(matches,key=lambda m:m['similarity'],reverse=True),image,origin),info
