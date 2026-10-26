"""Offline supervised timing experiment from timestamped human demonstrations."""
import argparse
import json
from pathlib import Path
import numpy as np


def features(rows):
    history=[];result=[]
    for row in rows:
        now=row['t']
        if not row.get('rope_valid') or not row.get('avatar_valid'):continue
        history=[p for p in history if 0<now-p[0]<=.12]
        history.append((now,row['rope_y']))
        if len(history)<3:continue
        t=np.array([p[0] for p in history]);y=np.array([p[1] for p in history])
        if t[-1]-t[0]<.025:continue
        velocity=float(np.polyfit(t-t[-1],y,1)[0])
        if abs(velocity)>3:continue
        relative=row['rope_y']-row['avatar_y']
        result.append((now,[relative,velocity,relative**2,velocity**2,relative*velocity,row['avatar_y']]))
    return result


def metrics(probability,target,threshold):
    predicted=probability>=threshold
    tp=int(np.sum(predicted & (target==1)));fp=int(np.sum(predicted & (target==0)));fn=int(np.sum(~predicted & (target==1)))
    precision=tp/max(tp+fp,1);recall=tp/max(tp+fn,1)
    return dict(precision=precision,recall=recall,f1=2*precision*recall/max(precision+recall,1e-9),true_positive_frames=tp,false_positive_frames=fp,missed_positive_frames=fn)


def learn(folder):
    folder=Path(folder);rows=json.loads((folder/'vision-analysis.json').read_text(encoding='utf-8'))
    presses=np.array([e['t'] for e in json.loads((folder/'inputs.json').read_text(encoding='utf-8')) if e['type']=='key_down'])
    records=features(rows)
    if not records or len(presses)<5:raise ValueError('insufficient demonstration data')
    times=np.array([p[0] for p in records]);x=np.array([p[1] for p in records])
    next_index=np.searchsorted(presses,times);distance=np.array([presses[i]-t if i<len(presses) else np.inf for t,i in zip(times,next_index)])
    target=(distance<=.14).astype(float)
    boundary=rows[-1]['t']*.6
    train=times<boundary;test=~train
    if min(np.sum(target[train]),np.sum(target[test]))<3:raise ValueError('insufficient positive examples in time split')
    mean=x[train].mean(axis=0);scale=np.maximum(x[train].std(axis=0),1e-6)
    z=np.column_stack([np.ones(len(x)),(x-mean)/scale]);weights=np.zeros(z.shape[1])
    balance=np.where(target[train]==1,np.sum(target[train]==0)/max(np.sum(target[train]==1),1),1)
    for _ in range(1500):
        p=1/(1+np.exp(-np.clip(z[train]@weights,-30,30)))
        gradient=z[train].T@((p-target[train])*balance)/len(balance)
        gradient[1:]+=.02*weights[1:]
        weights-=.08*gradient
    probability=1/(1+np.exp(-np.clip(z@weights,-30,30)))
    threshold=max(np.linspace(.1,.9,81),key=lambda t:metrics(probability[train],target[train],t)['f1'])
    training=metrics(probability[train],target[train],threshold);validation=metrics(probability[test],target[test],threshold)
    # Candidate only: held-out frame classification is not proof of safe gameplay.
    report=dict(kind='logistic_human_timing_candidate',enabled=False,source=str(folder.resolve()),
        feature_names=['rope_minus_avatar_y','rope_speed','relative_squared','speed_squared','relative_times_speed','avatar_y'],
        mean=mean.tolist(),scale=scale.tolist(),weights=weights.tolist(),threshold=float(threshold),
        label='valid frames in 140ms preceding manual key_down; not verified successful crossings',
        split='chronological first 60 percent training, last 40 percent held out',split_seconds=boundary,
        training_frames=int(train.sum()),validation_frames=int(test.sum()),manual_presses=len(presses),
        press_with_recent_valid_feature=sum(any(0<=d-t<=.14 for t in times) for d in presses),
        training=training,validation=validation,
        limitations=['Long human presses change airtime; no short-jump timing calibration',
            'No per-jump success labels; misses and retries may be in demonstrations',
            'Dropped rope observations reduce feature coverage; model cannot recover invisible rope',
            'One recording; no independent session validation. Candidate stays offline.'])
    output=folder/'imitation-model.json';output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2));return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('recording');a=p.parse_args();learn(a.recording)
