from pathlib import Path
import json,cv2,numpy as np,wave,argparse

def export(recording,output,width=640,template_path=None):
 rec=Path(recording);p=Path(output);p.mkdir(parents=True,exist_ok=True)
 stamps=json.loads((rec/'timestamps.json').read_text(encoding='utf-8'));rows=[json.loads(s) for s in (rec/'audio-timestamps.jsonl').read_text(encoding='utf-8').splitlines()]
 folder=p/'exact-frames';folder.mkdir(exist_ok=True);cap=cv2.VideoCapture(str(rec/'screen.avi'));frames=[]
 for i,r in enumerate(stamps):
  ok,im=cap.read()
  if not ok:raise RuntimeError(f'Missing encoded frame {i}')
  name=f'{i:06d}.jpg'
  if not (folder/name).exists():cv2.imwrite(str(folder/name),cv2.resize(im,(width,round(im.shape[0]*width/im.shape[1]))),[cv2.IMWRITE_JPEG_QUALITY,80])
  frames.append(dict(frame=i,time=r['t'],image='exact-frames/'+name))
 cap.release()
 with wave.open(str(p/'analysis-mono.wav')) as w:
  rate=w.getframerate();x=np.frombuffer(w.readframes(w.getnframes()),'<i2').reshape(-1,w.getnchannels()).mean(axis=1)/32768
 hop=max(1,round(rate*.002));padding=(-len(x))%hop;blocks=np.pad(x,(0,padding)).reshape(-1,hop)
 peaks=np.stack([blocks.min(axis=1),blocks.max(axis=1)],axis=1)
 amap=[dict(wav=r['sample_start']/rate,t=r['t']) for r in rows]
 last=rows[-1];amap.append(dict(wav=(last['sample_start']+last['frames'])/rate,t=last['t']+last['duration']))
 data=dict(recording=str(rec),recording_end=json.loads((rec/'summary.json').read_text(encoding='utf-8'))['elapsed_seconds'] if (rec/'summary.json').exists() else frames[-1]['time'],frames=frames,audio_map=amap,peak_step=hop/rate,peaks=np.round(peaks,4).tolist(),duration=len(x)/rate)
 template=Path(template_path or 'tools/jump_rope/audio_review.html').read_text(encoding='utf-8')
 (p/'index.html').write_text(template.replace('__DATA__',json.dumps(data,ensure_ascii=False).replace('</','<\\/')),encoding='utf-8')
 print(f'Exported {len(frames)} exact frames and {len(peaks)} waveform bins')
if __name__=='__main__':
 parser=argparse.ArgumentParser();parser.add_argument('--recording',required=True);parser.add_argument('--output',required=True);args=parser.parse_args();export(args.recording,args.output)
