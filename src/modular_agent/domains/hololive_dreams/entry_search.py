"""Cheap structural routing followed by small-region target searches."""
from .templates import MAP,DETAIL,WORLD,READY

GROUPS=[
 (MAP,(0,.02,.36,.24)),
 (['entry_detail_greed','entry_lever_detail','entry_move'],(.55,.15,1,.86)),
 (['entry_area','entry_lobby','map2'],(0,.48,.34,1)),
 (['smallgame','time'],(.10,.14,.96,.94)),
 (['entry_interact','entry_lever_interact','entry_to_game','entry_keep'],(.58,.35,.99,.78)),
 (['entry_ready_logo'],(0,.02,.30,.32)),
 (['entry_ready_start'],(.30,.68,.72,.94)),
]
def match_entry(matcher,image,environment,origin,features,requested,scales=None,threshold=None):
 wide='entry_search_wide' in requested
 if features.get('dialogue') or features.get('reward') or features.get('rank_up'):
  return [],{'mode':'structure_only','regions':0}
 if wide:
  names=MAP+DETAIL+WORLD+READY+['map2','smallgame','time']
  return matcher.match(image,environment,origin,template_names=names,scales=scales,threshold=threshold),{'mode':'wide_recovery','regions':1}
 if features.get('map'):
  allowed=set(MAP+DETAIL+['map2','smallgame','time'])
 elif features.get('options'):
  allowed={'entry_to_game','entry_keep'}
 elif features.get('hud_count',0)>=3:
  allowed={'entry_interact','entry_lever_interact',*READY}
 else:
  allowed=set(requested)-{'menu','stage','task','entry_dialogue'}
 matches=[];regions=0;h,w=image.shape[:2]
 for names,zone in GROUPS:
  selected=[n for n in names if n in allowed]
  if not selected: continue
  x,y,r,b=map(int,(zone[0]*w,zone[1]*h,zone[2]*w,zone[3]*h))
  local_scales=[.65,.75,.85,1.0] if any(n in ('smallgame','time') for n in selected) else scales
  matches.extend(matcher.match(image[y:b,x:r],environment,(origin[0]+x,origin[1]+y),
                              template_names=selected,scales=local_scales,threshold=threshold))
  regions+=1
 return sorted(matches,key=lambda m:m['similarity'],reverse=True),{'mode':'regional','regions':regions}
