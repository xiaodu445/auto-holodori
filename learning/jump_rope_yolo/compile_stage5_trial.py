"""Compile experimental stage-5 priors without changing the accepted stage-1–4 bank."""
import copy
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'src'))
from modular_agent.realtime.phase_tracking import CyclicTrajectory
from modular_agent.realtime.motion_states import BoundedTrajectory
from modular_agent.realtime.trajectory_bank import DirectionWarp, AngularWarp
from modular_agent.realtime.timed_rope_playback import TimedRopeTemplate


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    lib = ROOT / 'domains/hololive_dreams/data/jump_rope_template_library'
    base_path = lib / 'generated/stages_1_4_timed/catalog.json'
    base = read(base_path)
    out = lib / 'generated/stages_1_5_yolo07_trial'
    out.mkdir(parents=True, exist_ok=True)
    params = read(ROOT / 'domains/hololive_dreams/models/jump_rope_visible_fit_config.json')
    profile_path = ROOT / 'domains/hololive_dreams/data/jump_rope_phase' / params['stage_profiles_asset']
    branches = read(profile_path)['stages'][4]['branches']
    rotation = CyclicTrajectory(read(ROOT / params['atlas']))
    swing = BoundedTrajectory(read(ROOT / params['swing_atlas']))
    swdata = read(ROOT / params['swing_time_profile_asset'])
    swprofile = swdata.get('data', swdata)
    if 'clock_nodes' not in swprofile:
        swprofile = params['swing_time_profile']
    swwarp = AngularWarp(swprofile)
    reverse_warp = DirectionWarp(params['reverse_time_profile'])
    boundary = float(np.argmax(rotation.curves(np.arange(2048) / 2048)[:, 20, 1]) / 2048)
    timing = read(ROOT / 'domains/hololive_dreams/models/jump_rope_mainline_input_config.json')
    entries = copy.deepcopy(base['templates'])
    for entry in entries:
        assert hashlib.sha256((ROOT / entry['file']).read_bytes()).hexdigest() == entry['sha256']
    for role in ('normal', 'accelerate', 'decelerate', 'low_swing'):
        branch = branches[role]
        for direction in (['bidirectional'] if role == 'low_swing' else ['forward', 'reverse']):
            mode = 'low_swing' if role == 'low_swing' else 'rotation_' + direction
            sign = -1 if direction == 'reverse' else 1
            warp = swwarp if role == 'low_swing' else DirectionWarp(branch['directions'][mode]) if mode in branch.get('directions', {}) else reverse_warp if direction == 'reverse' else AngularWarp()
            nodes = np.linspace(0, 1, 97)
            angles = np.array([warp.evaluate(float(u))[0] for u in nodes])
            angles[-1] = 1
            coordinates = (1 - np.cos(2 * np.pi * angles)) / 2 if role == 'low_swing' else (boundary + sign * angles) % 1
            curves = swing.curves(coordinates) if role == 'low_swing' else rotation.curves(coordinates)
            if role == 'low_swing':
                jumps = [swwarp.inverse(math.acos(1 - 2 * timing['low_forward_coordinate']) / (2 * math.pi)), swwarp.inverse(1 - math.acos(1 - 2 * timing['low_return_coordinate']) / (2 * math.pi))]
            else:
                coordinate = timing['reverse_coordinate'] if direction == 'reverse' else timing['forward_coordinate']
                jumps = [warp.inverse(sign * coordinate - sign * boundary)]
            data = dict(schema=1, template_id=f'stage5-{role}-{direction}-legacy-trial', kind='timed_observed_rope_cycle', stage=5, state=role, direction=direction, camera_id='wide_camera_v1', period_seconds=1 / branch['clock_rate'], samples=[dict(elapsed_cycle_fraction=float(u), points=curve.tolist()) for u, curve in zip(nodes, curves)], jump_progress_nodes=jumps, active_runtime=True, verified=False, source_kind='legacy_shape_and_warp_compiled_to_time', period_source=branch.get('timing_source', 'legacy_unverified_prior'), source_branch=f'stages[4].branches.{role}', source_profile=profile_path.relative_to(ROOT).as_posix(), source_shape=params['swing_atlas'] if role == 'low_swing' else params['atlas'], source_calibration=branch.get('calibration'), max_time_gap_fraction=.18, max_point_gap_x=.12, limitations=['Stage-5 trial: timing and manual onset phase are not independently calibrated.', 'Geometry and onset mapping use the same compiler conventions as the stage-1–4 bank.'])
            TimedRopeTemplate(data)
            path = out / (data['template_id'] + '.json')
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            entries.append(dict(file=path.relative_to(ROOT).as_posix(), sha256=hashlib.sha256(path.read_bytes()).hexdigest(), template_id=data['template_id'], stage=5, state=role, direction=direction, source_kind=data['source_kind'], period_seconds=data['period_seconds']))
    catalog = dict(schema=1, scope='stages_1_5_except_stage2_decelerate_with_stage5_trial', templates=entries, excluded_states=base.get('excluded_states', []), runtime_verified=False, base_catalog=base_path.relative_to(ROOT).as_posix(), limits='Stage 1–4 entries preserved. Stage 5 adds seven unverified legacy candidates for live trial.')
    (out / 'catalog.json').write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(dict(catalog=(out / 'catalog.json').relative_to(ROOT).as_posix(), original_entries=len(base['templates']), added_stage5=[{k: e[k] for k in ('state', 'direction', 'period_seconds')} for e in entries if e['stage'] == 5]), indent=2))


if __name__ == '__main__':
    main()
