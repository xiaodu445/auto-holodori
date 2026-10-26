"""Build reviewed HUD references from explicit class assignments, no pseudo labels."""
import json,sys,cv2
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from modular_agent.realtime.kitchen_ui import TARGET_RECTS,TRAY_RECTS,crop_rect

def main():
    sources=json.loads((ROOT/'runtime/kitchen/ui-bank-audit/sources.json').read_text(encoding='utf-8'))
    assignments={2:['cereal','milk_blue','Hand'],4:['meat_pack','onion','breadcrumbs'],7:['rice_plate','gravy_boat','chili'],10:['noodle_pan','can','seaweed'],12:['IANGCHANG','hamburger_patty','rice_box'],15:['udon','Yellow_egg','scallion'],16:['White_Egg','flour_bag','tuna_can']}
    folder=ROOT/'data/kitchen/ui-icons';folder.mkdir(exist_ok=True);existing=json.loads((folder/'index.json').read_text(encoding='utf-8')) if (folder/'index.json').exists() else {};icons=list(existing.get('icons',[]))
    for source,classes in assignments.items():
        rec,index=sources[source];cap=cv2.VideoCapture(str(ROOT/'runtime/kitchen/recordings'/rec/'screen.avi'));cap.set(cv2.CAP_PROP_POS_FRAMES,index);ok,image=cap.read();cap.release();assert ok
        for slot,key in enumerate(classes):
            file=f'target-{source}-{slot}.png';cv2.imwrite(str(folder/file),crop_rect(image,TARGET_RECTS[slot]));icons.append(dict(file=file,class_id=key,source_recording=rec,frame=index,region='target',reviewed=True))
    rec='20261023-002908-164722';cap=cv2.VideoCapture(str(ROOT/'runtime/kitchen/sessions'/rec/'screen.avi'));cap.set(cv2.CAP_PROP_POS_FRAMES,136);ok,image=cap.read();cap.release();assert ok
    for region,rects,classes in [('target',TARGET_RECTS,['Spider','fish_fillet_board','instant_noodles']),('tray',TRAY_RECTS,['milk_blue','Spider','rice_plate'])]:
        for slot,key in enumerate(classes):
            file=f'{region}-live-{slot}.png';cv2.imwrite(str(folder/file),crop_rect(image,rects[slot]));icons.append(dict(file=file,class_id=key,source_session=rec,frame=136,region=region,reviewed=True))
    empties=[]
    for slot in [3,4,5,6]:
        file=f'empty-{slot}.png';cv2.imwrite(str(folder/file),crop_rect(image,TRAY_RECTS[slot]));empties.append(file)
    (folder/'index.json').write_text(json.dumps(dict(icons=list({e['file']:e for e in icons}.values()),empty_icons=sorted(set(empties+existing.get('empty_icons',[]))),scope='reviewed UI crops; incomplete category coverage; scores are similarities not calibrated probabilities'),ensure_ascii=False,indent=2),encoding='utf-8')
    print('icons',len(icons))

if __name__=='__main__':main()
