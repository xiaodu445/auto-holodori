"""Read-only regression replay of recorded JPEGs; NEVER instantiates input."""
import argparse,importlib.util,json,sys
from collections import Counter
from pathlib import Path
import cv2

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('hold_replay_model',ROOT/'domains/hololive_dreams/models/rhythm/rhythm_game.py')
m=importlib.util.module_from_spec(spec);sys.modules[spec.name]=m;spec.loader.exec_module(m)
p=argparse.ArgumentParser();p.add_argument('review',type=Path);p.add_argument('--duration',type=float,default=45);a=p.parse_args()
d=json.loads((a.review/'analysis.json').read_text(encoding='utf-8'));config=m.load_config(ROOT);v=m.RhythmVision(config);c=m.RhythmController(config)
previous=None;down=set();edges=[];events=[];red=0;paths=0;types={};count=0
def collect(decision,stamp):
    global down
    for key in sorted(down^decision['keys']):edges.append((stamp,key,key in decision['keys']))
    down=set(decision['keys']);events.extend(decision['events'])
for f in d['frames']:
    t=f['time']
    if t>a.duration:break
    if previous is not None:
        cursor=previous+.001
        while cursor<t:
            collect(c.poll(cursor),cursor);cursor+=.001
    im=cv2.imread(str(a.review/f['image']))
    if im is None:raise ValueError('missing '+f['image'])
    notes=v.detect(im,t);red+=sum(n.center[1]>config['prediction_zone'][1] for n in notes);paths+=len(v.hold_paths)
    collect(c.decide(notes,t,v.hold_paths),t)
    for track in c.tracks:types[track['id']]=track['color']
    previous=t;count+=1
    if count%600==0:print('replayed',round(t,2),'s',flush=True)
print('frames',count,'red detections',red,'bottom paths',paths)
print('events',Counter(e.get('type','head') for e in events))
print('heads by colour',Counter(types.get(e.get('id')) for e in events if 'arrival' in e))
for lo,hi in ((17.,17.8),(41.,42.5)):
    print('window',lo,hi,'old API',[(round(e['time'],4),e['key'],e['down']) for e in d.get('input_attempts',[]) if lo<=e['time']<=hi and e['success']])
    print('window',lo,hi,'new simulated',[(round(t,4),key,down) for t,key,down in edges if lo<=t<=hi])
print('No real keyboard input was sent. No Perfect accuracy inferred.')
