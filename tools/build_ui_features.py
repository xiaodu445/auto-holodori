"""Materialize stable UI crops and foreground masks; retain source provenance."""
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from modular_agent.domains.hololive_dreams.visual_features import SPECS
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'domains/hololive_dreams/data/ui_features'
ICON_SPECS=[
 ('icon_activity',(721,68,771,113),(.53,.06,.62,.18)),
 ('icon_game',(793,68,844,113),(.59,.06,.68,.18)),
 ('icon_stage',(870,68,917,113),(.65,.06,.74,.18)),
 ('icon_task',(943,68,990,113),(.71,.06,.80,.18)),
 ('icon_achievement',(1017,68,1064,113),(.77,.06,.86,.18)),
 ('world_camera',(32,581,92,638),(.01,.72,.10,.90)),
 ('world_jump',(1052,581,1146,652),(.81,.73,.94,.92)),
]
def foreground(image):
 hsv=cv2.cvtColor(image,cv2.COLOR_BGR2HSV)
 return np.uint8(((hsv[:,:,1]<85)&(hsv[:,:,2]>185))|((hsv[:,:,0]>=14)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>75)&(hsv[:,:,2]>175)))*255
def write(name,source,box,zone,mode):
 image=cv2.imdecode(np.fromfile(str(source),np.uint8),1)
 x,y,r,b=box;patch=image[y:b,x:r]
 cv2.imencode('.png',patch)[1].tofile(str(OUT/f'{name}.png'))
 item=dict(name=name,image=f'{name}.png',zone=list(zone),mode=mode,source=source.name,crop=list(box),source_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
 if mode=='foreground':
  binary=foreground(patch)
  mask=cv2.dilate(binary,np.ones((5,5),np.uint8))
  cv2.imencode('.png',binary)[1].tofile(str(OUT/f'{name}.foreground.png'))
  cv2.imencode('.png',mask)[1].tofile(str(OUT/f'{name}.mask.png'))
  item.update(foreground=f'{name}.foreground.png',mask=f'{name}.mask.png')
 return item
if __name__=='__main__':
 OUT.mkdir(parents=True,exist_ok=True)
 folder=ROOT/'domains/hololive_dreams/data/world_reference/20261017'
 items=[write(name,folder/f'codex-clipboard-{identifier}.png',box,zone,'gray') for name,identifier,box,zone in SPECS]
 source=folder/'codex-clipboard-9453cc6a-f96b-4d2e-9403-25b833c8a875.png'
 items.extend(write(name,source,box,((box[0]-14)/1264,.065,(box[2]+14)/1264,.18) if name.startswith('icon_') else zone,'foreground') for name,box,zone in ICON_SPECS)
 gift_source=ROOT/'domains/hololive_dreams/data/world_reference/20261018/codex-clipboard-4328b6fa-9541-41c8-8987-32c8b632fef5.png'
 items.append(write('gift_label',gift_source,(1337,536,1396,565),(.70,.35,.99,.80),'foreground'))
 scratch_source=ROOT/'domains/hololive_dreams/data/world_reference/20261022/codex-clipboard-09ae474c-9d87-4d32-b3eb-ad261aba4735.png'
 items.append(write('scratch_label',scratch_source,(920,460,992,489),(.70,.35,.99,.80),'foreground'))
 scratch_open_source=ROOT/'domains/hololive_dreams/data/world_reference/20261025/codex-clipboard-1655f28b-bb1f-4cb7-8273-2900900abaff.png'
 items.append(write('scratch_open',scratch_open_source,(575,628,677,654),(.30,.74,.74,.94),'gray'))
 (OUT/'manifest.json').write_text(json.dumps(dict(schema=1,features=items),ensure_ascii=False,indent=2),encoding='utf-8')
 print(f'{len(items)} independent feature crops exported to {OUT}')
