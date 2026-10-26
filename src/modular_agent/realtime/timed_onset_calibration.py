"""Calibrate trial playback onsets from focused recorded human Space edges.
These are human timing anchors, not verified short-pulse game mechanics.
"""
import json,math
from pathlib import Path
import numpy as np
from modular_agent.realtime.timed_rope_playback import TimedRopeTemplate

def circle_median(values):
 v=np.asarray(values,float)%1;c=min(v,key=lambda x:float(np.sum(abs((v-x+.5)%1-.5))))
 offsets=(v-c+.5)%1-.5;center=(c+float(np.median(offsets)))%1;distance=abs((v-center+.5)%1-.5);mad=float(np.median(distance));keep=distance<=max(.045,min(.12,3*mad));retained=v[keep]
 offsets=(retained-center+.5)%1-.5;return float((center+np.median(offsets))%1),int(keep.sum()),float(np.max(abs(offsets)))

def calibrate_data(data,root):
 rec=root/data['source_recording'];inputs=json.loads((rec/'inputs.json').read_text(encoding='utf-8'));stamps=json.loads((rec/'timestamps.json').read_text(encoding='utf-8'));ann=data['source_interval'];origin=data['training_time_range']['start'];period=data['period_seconds']
 edges=[e['t'] for e in inputs if e['type']=='key_down' and e['key']=='space' and e.get('focused') and stamps[ann['start_frame']]['t']<=e['t']<stamps[ann['end_frame_exclusive']]['t']]
 if not edges:return data
 phases=np.array([(t-origin)/period%1 for t in edges]);groups=[phases]
 if data['state']=='low_swing':
  if len(phases)<2:return data
  centers=[float(phases[0]),float(phases[np.argmax(abs((phases-phases[0]+.5)%1-.5))])]
  if abs((centers[1]-centers[0]+.5)%1-.5)<.20:return data
  for _ in range(8):
   labels=np.argmin(np.column_stack([abs((phases-c+.5)%1-.5) for c in centers]),axis=1);groups=[phases[labels==i] for i in range(2)]
   if any(len(g)==0 for g in groups):return data
   centers=[circle_median(g)[0] for g in groups]
 anchors=[circle_median(g) for g in groups];data['prior_shape_onset_nodes']=data['jump_progress_nodes'];data['jump_progress_nodes']=sorted(a[0] for a in anchors);data['jump_timing_source']='recorded focused human Space onsets, circular median; short-pulse unverified';data['manual_onset_calibration']=dict(source_recording=data['source_recording'],input_file=(rec/'inputs.json').relative_to(root).as_posix(),source_frame_range=ann,event_times=edges,event_phases=phases.tolist(),group_retained_counts=[a[1] for a in anchors],group_max_deviation_cycles=[a[2] for a in anchors],verified=False,short_pulse_verified=False,limits='Recorded key-down timing includes human variability and held presses; this does not verify automatic success.')
 return data

def transfer_onsets(target,reference):
 """Align a source onset shape and adjacent poses in each candidate's own clock."""
 a=TimedRopeTemplate(target);b=TimedRopeTemplate(reference);x=np.linspace(.25,.8,41);grid=np.arange(1024)/1024;anchors=[]
 for onset in reference['jump_progress_nodes']:
  errors=[]
  for u in grid:
   total=[]
   for delta,weight in [(-.025,1),(-.0125,1),(0,3),(.0125,1),(.025,1)]:
    y=a.curve(u+delta,x);z=b.curve(onset+delta,x);valid=np.isfinite(y)&np.isfinite(z)
    if valid.sum()>=12:total.extend([float(np.mean((y[valid]-z[valid])**2))]*weight)
   errors.append(float(np.mean(total)) if len(total)>=4 else math.inf)
  if not math.isfinite(min(errors)):return target
  anchors.append(float(grid[int(np.argmin(errors))]))
 target['prior_shape_onset_nodes']=target['jump_progress_nodes'];target['jump_progress_nodes']=sorted(anchors);target['jump_timing_source']='recorded human onset pose aligned to this candidate clock; unverified';target['manual_onset_reference']=dict(template_id=reference['template_id'],source_state=list(b.context[:3]),method='five neighboring poses; cyclic candidate search',verified=False,short_pulse_verified=False)
 return target
