"""Offline empirical low-swing periods from independently fitted curve samples."""
import argparse
import json
from pathlib import Path
import numpy as np

def crossings(rows,level,start,end,max_gap=.14):
    good=sorted([r for r in rows if start<=r['time']<=end and r['fit_support']>.45 and r['template_error']<.018],key=lambda r:r['time'])
    times=[]
    for a,b in zip(good,good[1:]):
        if 0<b['time']-a['time']<=max_gap and a['center_y']<level<=b['center_y']:
            times.append(a['time']+(b['time']-a['time'])*(level-a['center_y'])/(b['center_y']-a['center_y']))
    return times

def build(root):
    root=Path(root);folder=root/'domains/hololive_dreams/data/jump_rope_samples/calibration'
    first=json.loads((root/'domains/hololive_dreams/data/jump_rope_phase/swing_time_v1.json').read_text(encoding='utf-8'))
    middle=json.loads((folder/'yellow-middle.json').read_text(encoding='utf-8'))['rows']
    blue=json.loads((folder/'blue-late.json').read_text(encoding='utf-8'))['rows']
    middle_evidence=[];blue_evidence=[]
    for level,windows in [(.56,[(50.8,51.2),(52.8,53.2)]),(.59,[(58.25,58.5),(60.25,60.5)]),(.62,[(58.35,58.6),(60.35,60.6)])]:
        pair=[crossings(middle,level,*window) for window in windows]
        if not all(len(t)==1 for t in pair):raise ValueError('incomplete middle crossing evidence')
        middle_evidence.append(dict(level=level,times=[t[0] for t in pair],period=pair[1][0]-pair[0][0]))
    for level in [.48,.50,.53,.56,.59,.62]:
        pair=[crossings(blue,level,*window) for window in [(76.,76.7),(77.8,78.4)]]
        if not all(len(t)==1 for t in pair):raise ValueError('incomplete blue crossing evidence')
        blue_evidence.append(dict(level=level,times=[t[0] for t in pair],period=pair[1][0]-pair[0][0]))
    periods=[first['reference_period'],float(np.median([r['period'] for r in middle_evidence])),float(np.median([r['period'] for r in blue_evidence]))]
    if not all(1.5<p<2.6 for p in periods) or not all(a>b for a,b in zip(periods,periods[1:])):raise ValueError('unexpected empirical periods')
    data=dict(schema=1,verified=False,periods=periods,gears=[1/p for p in periods],middle_crossings=middle_evidence,blue_crossings=blue_evidence,
        sources=['domains/hololive_dreams/data/jump_rope_phase/swing_time_v1.json','domains/hololive_dreams/data/jump_rope_samples/calibration/yellow-middle.json','domains/hololive_dreams/data/jump_rope_samples/calibration/blue-late.json'],
        method='Independent color-specific quadratic rope fits; matching ascending center-height crossings with bounded sample gaps, no tracker rates or extrapolation. Blue uses two wholly low-swing passes after 76s, excludes prior normal rotation and skill onset.',
        limits='Empirical candidate gears on one development recording; not verified engine gears/global extrema. Common time warp from first yellow episode; dense holdout unavailable.')
    output=root/'domains/hololive_dreams/data/jump_rope_phase/swing_rates_v1.json';output.write_text(json.dumps(data,indent=2),encoding='utf-8');return data

def main():
    p=argparse.ArgumentParser();p.add_argument('--project-root',default='.');a=p.parse_args();print(json.dumps(build(a.project_root)))

if __name__=='__main__':main()
