"""Read the user's tuning values without executing batch commands."""
import math
import re
from pathlib import Path

FIELDS={
 'FPS':('fps',30,240),'WIDTH':('analysis_width',480,1600),
 'GRID_SNAP':('grid_snap_ms',0,25),'OFFSET':('input_offset_ms',-100,100),
 'RELEASE_LEAD':('release_lead_ms',0,300),'DENSE_GAP':('dense_gap_ms',0,300),
 'DENSE_RECOVERY':('dense_recovery_ms',25,500),'DENSE_TAP':('dense_tap_ms',1,50),
 'MIN_DOWN':('min_down_ms',1,50),'RELEASE_GAP':('release_gap_ms',1,50),
 'KEY_LOOKAHEAD':('key_lookahead_ms',0,300),'SLIDE_GUARD':('slide_guard_ms',0,500),
 'DURATION':('timeout',0,1800),
}


def load_profile(root,profile='mechanism'):
    if profile=='config':return {},[]
    if profile not in ('tuning','mechanism'):raise ValueError('unknown rhythm profile')
    root=Path(root);path=root/'run_rhythm_tuning.cmd'
    text=path.read_text(encoding='utf-8-sig')
    values=dict(re.findall(r'^\s*set\s+"RHYTHM_([A-Z_]+)=([^"\r\n]*)"\s*$',text,re.M|re.I))
    result={'input_mode':'all-held'}
    for source,(key,low,high) in FIELDS.items():
        if source not in values:raise ValueError('missing tuning value RHYTHM_'+source)
        number=float(values[source])
        if not math.isfinite(number) or not low<=number<=high:raise ValueError('invalid tuning value RHYTHM_'+source)
        if key=='timeout' and number!=0 and number<1:raise ValueError('invalid tuning duration')
        if key in ('fps','analysis_width') and not number.is_integer():raise ValueError('integer required: '+source)
        result[key]=int(number) if number.is_integer() else number
    scope=values.get('RELEASE_SCOPE')
    if scope not in ('target','all'):raise ValueError('invalid release scope')
    result['release_scope']=scope
    sources=[str(path)]
    if profile=='mechanism':
        wrapper=root/'run_rhythm_mechanism_test.cmd';command=wrapper.read_text(encoding='utf-8-sig')
        calls=[s for s in command.splitlines() if s.strip().lower().startswith('call ')]
        if len(calls)!=1:raise ValueError('unsupported mechanism wrapper')
        for switch,key,allowed in [('global-flow','global_flow',('off','shadow','active')),
                                  ('measure-clock','measure_clock',('off','shadow')),
                                  ('mechanism-mode','mechanism_mode',('off','shadow','active'))]:
            matches=re.findall(r'--'+switch+r'\s+(\w+)',calls[0])
            if not matches or matches[-1] not in allowed:raise ValueError('unsupported wrapper switch: '+switch)
            result[key]=matches[-1]
        sources.append(str(wrapper))
    return result,sources
