"""Internal invariants of a saved C4 replay; these do not measure visual accuracy."""
import argparse
import json
import math
from pathlib import Path


def check(rows):
    result=dict(frames=len(rows),transitions=[],direct_rotation_flips=[],wrong_exit_directions=[],nonpositive_clock_frames=0,gear_bounds_violations=0,pure_playback_checks=0,max_pure_playback_error=0.)
    rates=[]
    for i,row in enumerate(rows):
        o=row['observation'];e=o['phase_estimate'];rate=e['clock_rate'];rates.append(rate)
        result['nonpositive_clock_frames']+=int(not math.isfinite(rate) or rate<=0)
        lo,hi=e['speed_bounds'];result['gear_bounds_violations']+=int(not lo-1e-9<=rate<=hi+1e-9)
        previous=rows[i-1]['observation'] if i else None
        if previous is None or previous['motion_state']!=o['motion_state']:
            result['transitions'].append(dict(time=row['time'],mode=o['motion_state'],episode=o['low_swing_episode'],entry=o['low_entry_direction'],turns=o['low_turns_observed'],recovered=o['last_exit_recovered']))
            if previous is not None:
                if previous['motion_state']!='low_swing' and o['motion_state']!='low_swing':result['direct_rotation_flips'].append(row['time'])
                if previous['motion_state']=='low_swing' and o['motion_state']!='low_swing':
                    direction=-1 if o['motion_state']=='rotation_reverse' else 1
                    if direction!=-previous['low_entry_direction']:result['wrong_exit_directions'].append(row['time'])
        if previous is not None and previous['selected_hypothesis']==o['selected_hypothesis'] and e['continuation']=='template_playback':
            direction=-1 if o['motion_state']=='rotation_reverse' else 1
            predicted=previous['phase_estimate']['phase_unwrapped']+direction*previous['phase_estimate']['clock_rate']*(row['time']-rows[i-1]['time'])
            result['pure_playback_checks']+=1
            result['max_pure_playback_error']=max(result['max_pure_playback_error'],abs(predicted-e['phase_unwrapped']))
    result.update(mode_changes=max(0,len(result['transitions'])-1),clock_rate_min=min(rates) if rates else None,clock_rate_max=max(rates) if rates else None,limits='Internal consistency only. No ground truth skill count, tracking accuracy, or live-input validation.')
    result['passed']=bool(rows) and not any(result[key] for key in ['direct_rotation_flips','wrong_exit_directions','nonpositive_clock_frames','gear_bounds_violations']) and result['max_pure_playback_error']<1e-8
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--replay',default='runtime/jump-rope/phase-gear/replay.json');parser.add_argument('--output',default='runtime/jump-rope/phase-gear/constraint-report.json');args=parser.parse_args()
    result=check(json.loads(Path(args.replay).read_text(encoding='utf-8')))
    Path(args.output).write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result))
    if not result['passed']:raise SystemExit(1)

if __name__=='__main__':main()
