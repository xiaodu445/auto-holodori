"""Build source-frame annotation viewer with ADC-mapped audio; no prediction/input."""
from pathlib import Path
import argparse,json,wave,hashlib
import numpy as np,cv2
from export_audio_review import export

def run(recording,output):
 rec=Path(recording);out=Path(output);out.mkdir(parents=True,exist_ok=True)
 stamps=json.loads((rec/'timestamps.json').read_text(encoding='utf-8'));summary=json.loads((rec/'summary.json').read_text(encoding='utf-8'))
 if len(stamps)!=summary['frames_encoded'] or any(a['t']>=b['t'] for a,b in zip(stamps,stamps[1:])):raise ValueError('invalid recording frame timestamps')
 with wave.open(str(rec/'audio.wav')) as w:
  rate=w.getframerate();x=np.frombuffer(w.readframes(w.getnframes()),'<i2').reshape(-1,w.getnchannels()).mean(axis=1)
 peak=float(np.max(np.abs(x)));gain=min(6.,26000/max(1,peak));mono=np.clip(x*gain,-32768,32767).astype('<i2')
 with wave.open(str(out/'analysis-mono.wav'),'wb') as w:w.setnchannels(1);w.setsampwidth(2);w.setframerate(rate);w.writeframes(mono.tobytes())
 cv2.setNumThreads(1);export(rec,out,width=1280,template_path='tools/jump_rope/recording_review.html')
 images=list((out/'exact-frames').glob('*.jpg'))
 if len(images)!=len(stamps):raise ValueError('exported frame count mismatch')
 manifest=dict(schema=1,recording=rec.as_posix(),frames=len(stamps),first_time=stamps[0]['t'],last_time=stamps[-1]['t'],audio_preview_gain=gain,original_timestamps_sha256=hashlib.sha256((rec/'timestamps.json').read_bytes()).hexdigest(),prediction=False,input_sent=False,frame_range_convention='[start_frame,end_frame_exclusive)',frame_points_coordinate='normalized_game_client',limits='ADC mapping preserves recorded timing but device latency is uncalibrated. Local browser cache must be exported to JSON. Full original recording remains the source.')
 (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps(dict(viewer=str((out/'index.html').resolve()),frames=len(stamps)),ensure_ascii=False),flush=True)
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--recording',required=True);p.add_argument('--output',required=True);a=p.parse_args();run(a.recording,a.output)
