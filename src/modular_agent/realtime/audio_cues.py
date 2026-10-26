"""Local audio motif features and bounded DTW; no speech model in runtime."""
import math
import wave
import json
from pathlib import Path
import numpy as np

LABELS={'falling_obstacles','low_swing','accelerate','decelerate'}
# Falling objects degrade observation; they say nothing about speed/direction.
MOTION_CUES={'low_swing','accelerate','decelerate'}

def cue_effect(label):
    if label not in LABELS:return dict(motion_hint=None,occlusion_hint=False)
    return dict(motion_hint=label if label in MOTION_CUES else None,occlusion_hint=label=='falling_obstacles')

def low_entry_authorized(event,now,lifetime=4.,threshold=.22,margin=.04):
    """Authorize destructive low-mode entry, not a forced mode/direction switch."""
    return bool(event and event.get('motion_hint')=='low_swing'
                and 0<=now-event['time']<=lifetime
                and event['distance']<=threshold and event['margin']>=margin)

def read_mono(path):
    with wave.open(str(path)) as w:
        if w.getsampwidth()!=2:raise ValueError('16-bit PCM required')
        rate=w.getframerate();channels=w.getnchannels();x=np.frombuffer(w.readframes(w.getnframes()),'<i2').reshape(-1,channels).mean(axis=1)/32768
    if rate!=16000:
        if rate>16000:
            cutoff=7000/rate;kernel=np.sinc((np.arange(63)-31)*2*cutoff)*np.hamming(63);kernel/=kernel.sum();x=np.convolve(x,kernel,mode='same')
        n=int(round(len(x)*16000/rate));x=np.interp(np.arange(n)*rate/16000,np.arange(len(x)),x)
    return x.astype(np.float32)

def sample_times(rows,rate):
    if not rows or rate<=0:raise ValueError("audio timestamps and positive rate required")
    starts=np.array([r['sample_start'] for r in rows]+[rows[-1]['sample_start']+rows[-1]['frames']],float)/rate
    times=np.array([r['t'] for r in rows]+[rows[-1]['t']+rows[-1]['duration']],float)
    if np.any(np.diff(starts)<=0) or np.any(np.diff(times)<=0):raise ValueError('nonmonotonic audio timestamps')
    return starts,times

def features(x,rate=16000):
    if rate!=16000:raise ValueError('features require 16kHz mono')
    x=np.asarray(x,float)
    if len(x)<512:return np.empty((0,32))
    frames=np.lib.stride_tricks.sliding_window_view(x,512)[::160]
    power=abs(np.fft.rfft(frames*np.hanning(512),axis=1))**2
    # Log-spaced frequency triangles; per-frame unit normalization removes gain.
    frequencies=np.fft.rfftfreq(512,1/rate);edges=np.geomspace(100,7000,34)
    filters=np.array([np.maximum(0,np.minimum((frequencies-edges[i])/(edges[i+1]-edges[i]),(edges[i+2]-frequencies)/(edges[i+2]-edges[i+1]))) for i in range(32)])
    value=np.log(np.maximum(power@filters.T,1e-12));value-=value.mean(axis=1,keepdims=True)
    value/=np.maximum(np.linalg.norm(value,axis=1,keepdims=True),1e-8)
    return value.astype(np.float32)

def dtw_distance(a,b,band=.25):
    a=np.asarray(a,float);b=np.asarray(b,float)
    if not len(a) or not len(b):return math.inf
    if a.shape[1]!=b.shape[1]:raise ValueError('incompatible feature dimensions')
    cost=1-np.clip(a@b.T,-1,1);previous=np.full(len(b)+1,np.inf);previous[0]=0.
    for i in range(1,len(a)+1):
        current=np.full(len(b)+1,np.inf);center=i*len(b)/len(a);width=max(3,int(band*len(b)))
        for j in range(max(1,int(center-width)),min(len(b),int(center+width))+1):current[j]=cost[i-1,j-1]+min(previous[j],current[j-1],previous[j-1])
        previous=current
    return float(previous[-1]/(len(a)+len(b)))

class CueMatcher:
    def __init__(self,templates,threshold=.16,margin=.03):
        if not 0<threshold<1 or not 0<=margin<1:raise ValueError('invalid cue thresholds')
        if not templates or any(t['label'] not in LABELS or not t.get('human_reviewed') for t in templates):raise ValueError('audio templates require human reviewed skill labels')
        self.templates=templates;self.threshold=threshold;self.margin=margin
    def classify(self,samples):
        f=features(samples);scores={}
        for t in self.templates:
            d=dtw_distance(f,t['features']);scores[t['label']]=min(scores.get(t['label'],math.inf),d)
        ranked=sorted(scores.items(),key=lambda x:x[1]);label,d=ranked[0];gap=ranked[1][1]-d if len(ranked)>1 else 0.
        accepted=label if d<=self.threshold and gap>=self.margin else None
        return dict(label=accepted,**cue_effect(accepted),distance=d,margin=gap,scores=scores,limits='Candidate cue only; thresholds need held-out background calibration. Not an action or a posterior probability.')

def build_templates(recording,annotations,output):
    recording=Path(recording);audio=read_mono(recording/'audio.wav');summary=json.loads((recording/'summary.json').read_text(encoding='utf-8'));rows=[json.loads(s) for s in (recording/'audio-timestamps.jsonl').read_text(encoding='utf-8').splitlines()];wav,mono=sample_times(rows,summary['audio']['sample_rate']);templates=[]
    for a in annotations:
        if a.get('label') not in LABELS or not a.get('human_reviewed'):continue
        start,end=a['start'],a['end']
        if not 0<end-start<=4 or start<mono[0] or end>mono[-1]:raise ValueError('cue interval outside recording or too long')
        x1,x2=np.interp([start,end],mono,wav);f=features(audio[round(x1*16000):round(x2*16000)])
        if not len(f):raise ValueError('cue too short')
        templates.append(dict(label=a['label'],human_reviewed=True,start=start,end=end,features=f.tolist()))
    if not templates:raise ValueError('no human-reviewed cue labels; refusal to invent skill meanings')
    data=dict(schema=1,verified=False,recording=str(recording),sample_rate=16000,templates=templates,limits='Reviewed meanings, not validated detection thresholds. Need separate occurrence and negative background tests.')
    Path(output).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8');return data


def main():
    import argparse
    parser=argparse.ArgumentParser(description='Build offline cue candidates from human-reviewed intervals; never sends input.')
    parser.add_argument('--recording',required=True)
    parser.add_argument('--annotations',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    reviewed=json.loads(Path(args.annotations).read_text(encoding='utf-8-sig'))
    if reviewed.get('schema')!=1 or Path(reviewed.get('recording','')).resolve()!=Path(args.recording).resolve():
        parser.error('annotation recording does not match selected recording')
    data=build_templates(args.recording,reviewed['annotations'],args.output)
    print(f"Saved {len(data['templates'])} reviewed cue candidates; detection thresholds remain unvalidated.")

if __name__=='__main__':main()
