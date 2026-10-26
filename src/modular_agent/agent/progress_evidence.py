"""Local progress evidence, independent of model assertions and volatile detection IDs."""
import hashlib
import json


def fingerprint(report):
    def geometry(item):
        bounds=item.get('bounds',{})
        return tuple(round(bounds.get(k,0)/8) for k in ('x','y','width','height'))
    data={
        'texts':sorted((t.get('text','').strip(),geometry(t)) for t in report.texts),
        'buttons':sorted((b.get('label',''),geometry(b)) for b in report.buttons if b.get('semantic_confirmed')),
        'matches':sorted((m.get('label',''),geometry(m)) for m in report.knowledge_matches),
        'windows':sorted((w.get('title',''),w.get('foreground',False),w.get('minimized',False),geometry(w)) for w in report.windows if not report.frame.get('target_window_handle') or w.get('handle')==report.frame['target_window_handle']),
        'pixels':report.frame.get('visual_signature')}
    return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()


class ProgressEvidence:
    def __init__(self):
        self.previous=None
        self.unchanged=0
        self.last_action=None
        self.action_attempts=0
        self.no_effect=0
        self.state={'observations':0}

    def update(self,report,actions=None,action_succeeded=False):
        current=fingerprint(report)
        previous=self.previous
        changed=None if previous is None else current!=previous
        self.unchanged=self.unchanged+1 if changed is False else 0
        recovered=False
        if actions is not None:
            key=json.dumps([{'name':a.name,'arguments':a.arguments} for a in actions],sort_keys=True,ensure_ascii=False)
            same=key==self.last_action
            prior_no_effect=self.no_effect if same else 0
            self.action_attempts=self.action_attempts+1 if same else 1
            self.last_action=key
            self.no_effect=prior_no_effect+1 if changed is False else 0
            recovered=action_succeeded and changed is True and prior_no_effect>0
        reliable=bool(report.frame.get('visual_signature') or report.texts or report.knowledge_matches or any(b.get('semantic_confirmed') for b in report.buttons))
        self.previous=current
        self.state={
            'observations':self.state['observations']+1,
            'state_signature':current[:16], 'previous_signature':previous[:16] if previous else None,
            'observation_changed':changed, 'unchanged_observations':self.unchanged,
            'same_action_attempts':self.action_attempts, 'same_action_no_change_count':self.no_effect,
            'evidence_quality':'local_observation' if reliable else 'insufficient_content',
            'retry_followed_by_change':recovered and reliable,
            'interpretation':'本地识别及缩略像素变化，不等于任务成功或证明因果；状态相同不直接说明游戏卡死。'}
        return self.state.copy()
