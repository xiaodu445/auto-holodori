"""Deterministic kitchen triple planner and bounded realtime batch adapter.
No input backend imports: input delivery is never evidence of a match.
"""
from dataclasses import dataclass,asdict
from collections import defaultdict,Counter
import math,threading
from .kitchen_policy import confidence_state,POLICY_FIELDS

@dataclass(frozen=True)
class Item:
    instance_id:str
    class_id:str
    x:float
    y:float
    score:float
    bbox:tuple
    point_score:float=1.0
    point_source:str="keypoint"

@dataclass(frozen=True)
class Observation:
    frame_id:int
    captured:float
    finished:float
    items:tuple
    bounds:tuple=()
    scene:str='playing'
    enabled:bool=True
    tray:tuple=()
    targets:tuple=()
    ui_details:dict=None

@dataclass(frozen=True)
class Settings:
    click_interval:float=.005
    batch_interval:float=.5
    verify_removal:bool=False
    exploratory:bool=True
    only_targets:bool=False
    reserve_slots:int=3
    confidence:float=.5
    adaptive_confidence:bool=True
    confidence_ceiling:float=1.
    confidence_min_free:int=4
    confidence_visible_limit:int=8
    confidence_previous_click_limit:int=3
    confidence_step:float=.04
    confidence_pressure_boost:float=.05
    confidence_slot_weight:float=.7
    confidence_visible_weight:float=.2
    confidence_click_weight:float=.1
    enhanced_tail:bool=True
    tail_visible_limit:int=6
    tail_min_free:int=4
    tail_reserve_slots:int=2
    tail_max_singles:int=3
    max_age:float=.6
    settle:float=.12
    confirmation_timeout:float=1.5
    max_clicks:int=60
    duplicate_radius:float=8
    confirmation_frames:int=2
    def __post_init__(self):
        for name in ['click_interval','batch_interval','max_age','confirmation_timeout','duplicate_radius']:
            if not math.isfinite(getattr(self,name)) or getattr(self,name)<=0:raise ValueError(name)
        if not 0<=self.confidence<=1 or not 0<=self.settle<self.confirmation_timeout:raise ValueError('confidence/settle')
        if type(self.reserve_slots) is not int or not 1<=self.reserve_slots<=6:raise ValueError('reserve_slots')
        if not 3<=self.max_clicks<=300 or self.confirmation_frames<1:raise ValueError('budget')
        for name,_,_,kind,low,high in POLICY_FIELDS:
            value=getattr(self,name)
            if not math.isfinite(value) or not low<=value<=high or (kind is int and type(value) is not int):raise ValueError(name)
        if self.confidence_ceiling<self.confidence:raise ValueError('置信度上限不能低于正常值')
        if self.confidence_slot_weight<self.confidence_visible_weight+self.confidence_click_weight:raise ValueError('空槽权重必须至少等于其他权重之和')


class Latest:
    """Single-slot mailbox: old frames/results cannot build an unbounded queue."""
    def __init__(self):self.lock=threading.Lock();self.value=None
    def put(self,value):
        with self.lock:self.value=value
    def get(self):
        with self.lock:return self.value

def overlap(a,b):
    inter=max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
    return inter/max(1e-9,(a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter)

def duplicate_candidate(item,other,radius=8):
    if item.instance_id==other.instance_id:return True
    distance=math.hypot(item.x-other.x,item.y-other.y)
    if distance<radius:return True
    iou=overlap(item.bbox,other.bbox)
    # Nearly identical boxes with competing classes describe one ambiguous instance.
    if item.class_id!=other.class_id:return iou>.85
    short=min(item.bbox[2]-item.bbox[0],item.bbox[3]-item.bbox[1],other.bbox[2]-other.bbox[0],other.bbox[3]-other.bbox[1])
    return iou>.7 or (iou>.45 and distance<.5*short)

def visible_free_slots(observation):
    logical=sum(bool(c) for c in observation.tray)
    details=observation.ui_details or {}
    physical=details.get('occupied_slots',logical)
    return max(0,7-max(logical,int(physical)))

def policy_state(observation,settings):
    details=observation.ui_details or {};candidates=[]
    for item in sorted(observation.items,key=lambda p:-p.score):
        if len(item.bbox)!=4 or not all(math.isfinite(v) for v in (item.x,item.y,item.score,*item.bbox)):continue
        if not item.bbox[0]<=item.x<item.bbox[2] or not item.bbox[1]<=item.y<item.bbox[3]:continue
        if any(duplicate_candidate(item,other,settings.duplicate_radius) for other in candidates):continue
        candidates.append(item)
    if 'last_round_clicks' not in details:
        # Old recording metadata keeps its historical fixed sparse-rule interpretation.
        normal=settings.confidence;floor=min(normal,max(.05,details.get('tail_confidence',normal)))
        sparse=settings.exploratory and sum(p.score>=normal for p in candidates)<=2 and 0<len(candidates)<=6
        return dict(threshold=floor if sparse else normal,base=normal,reason='旧帧固定残局规则',free=visible_free_slots(observation),visible=sum(p.score>=normal for p in candidates),candidates=len(candidates),legacy=True)
    return confidence_state(settings,free=visible_free_slots(observation),visible=sum(p.score>=settings.confidence for p in candidates),candidates=len(candidates),last_clicks=details['last_round_clicks'],previous=details.get('previous_confidence'),reliable=bool(details.get('tray_capacity_reliable',False)),floor=details.get('tail_confidence',settings.confidence))

def plan(observation,targets,settings,now,trace=None):
    def explain(item,reason,selected=False):
        if trace is not None:trace.append(dict(instance_id=item.instance_id,class_id=item.class_id,score=item.score,selected=selected,reason=reason))
    if observation.scene!='playing' or not observation.enabled or not 0<=now-observation.captured<=settings.max_age:
        for item in observation.items:explain(item,'页面未就绪或输入禁用或截图超时')
        return ()
    priority=set(targets)|set(observation.targets)
    policy=policy_state(observation,settings);threshold=policy['threshold']
    kept=[]
    for item in sorted(observation.items,key=lambda p:-p.score):
        if settings.only_targets and item.class_id not in priority:
            explain(item,'只点击指定食材：该类别非指定或目标尚未识别');continue
        values=[item.x,item.y,item.score,*item.bbox]
        if len(item.bbox)!=4 or not all(math.isfinite(v) for v in values) or item.score<threshold:
            explain(item,'低于置信度门槛或坐标无效');continue
        if not item.bbox[0]<=item.x<item.bbox[2] or not item.bbox[1]<=item.y<item.bbox[3]:
            explain(item,'点击点不在框内');continue
        if any(duplicate_candidate(item,p,settings.duplicate_radius) for p in kept):
            explain(item,'与更高分目标重复或过近');continue
        kept.append(item)
    groups=defaultdict(list)
    for item in kept:groups[item.class_id].append(item)
    # Unknown occupied slots consume capacity but never contribute a class count.
    tray=observation.tray
    counts=Counter(c for c in tray if c not in ('','?'))
    if any(n>=3 for n in counts.values()):
        for item in kept:explain(item,'台账已有三个同类，等待消除')
        return ()
    occupied=sum(c!='' for c in tray) if tray else 0
    free=visible_free_slots(observation);priority=set(targets)|set(observation.targets)
    out=[]
    completions=[]
    for cls,count in counts.items():
        need=3-count
        if len(groups.get(cls,()))>=need:completions.append((need,cls not in priority,-min(p.score for p in groups[cls][:need]),cls))
    for need,_,_,cls in sorted(completions):
        if need>free or need-1>max(0,free-settings.reserve_slots) or len(out)+need>settings.max_clicks:continue
        for item in groups[cls][:need]:explain(item,'补齐台账已有同类',True)
        out.extend(groups[cls][:need]);groups[cls]=groups[cls][need:];free+=3-need;counts[cls]=0
    triples=[]
    for cls,items in groups.items():
        for i in range(0,len(items)-2,3):triples.append(tuple(items[i:i+3]))
    triples.sort(key=lambda triple:(triple[0].class_id not in priority,-min(p.score for p in triple),triple[0].class_id))
    class_order=list(dict.fromkeys(triple[0].class_id for triple in triples))
    triples=[triple for cls in class_order for triple in triples if triple[0].class_id==cls]
    triple_required=3 if (observation.ui_details or {}).get('tray_capacity_reliable',False) else settings.reserve_slots+2
    if free>=triple_required:
        for triple in triples:
            if len(out)+3>settings.max_clicks:break
            out.extend(triple)
            for item in triple:explain(item,'指定食材三消' if item.class_id in priority else '普通食材三消',True)
    # Enhanced tail uses the raw free-slot budget, never presumed future triple removals.
    safe_free=visible_free_slots(observation)
    context=observation.ui_details or {}
    use_enhanced=settings.enhanced_tail and 'last_round_clicks' in context
    if use_enhanced and settings.exploratory and len(tray)==7 and kept:
        reliable=bool(context.get('tray_capacity_reliable',False))
        sparse=policy['visible']<=settings.tail_visible_limit and policy['candidates']<=settings.tail_visible_limit*3
        budget=min(settings.tail_max_singles,settings.max_clicks-len(out),max(0,safe_free-settings.tail_reserve_slots-len(out)))
        if reliable and sparse and safe_free>=settings.tail_min_free and budget>0:
            selected={p.instance_id for p in out};remaining=[p for p in kept if p.instance_id not in selected]
            def tail_rank(p):
                area=max(0,p.bbox[2]-p.bbox[0])*max(0,p.bbox[3]-p.bbox[1])
                return (counts[p.class_id]==0,-area,-p.score,p.class_id)
            rest=sorted(remaining,key=tail_rank)[:budget]
            rest.sort(key=lambda p:p.class_id)
            for item in rest:explain(item,f'残局预算允许：强化残局，空槽{safe_free}、保留{settings.tail_reserve_slots}；门槛{threshold:.3f}',True)
            if rest:return tuple(out+rest)
    # A bounded tail sweep can relax the normal reserve, but never fill all slots.
    safe_free=visible_free_slots(observation)
    if not use_enhanced and settings.exploratory and len(tray)==7 and kept and len(kept)<safe_free and len(kept)<=settings.max_clicks:
        selected={p.instance_id for p in out}
        tail_groups=defaultdict(list)
        for p in kept:
            if p.instance_id not in selected:tail_groups[p.class_id].append(p)
        ordered=sorted(tail_groups,key=lambda cls:(counts[cls]==0,-max((p.bbox[2]-p.bbox[0])*(p.bbox[3]-p.bbox[1]) for p in tail_groups[cls]),-max(p.score for p in tail_groups[cls])))
        rest=[p for cls in ordered for p in sorted(tail_groups[cls],key=lambda p:-p.score)]
        for item in rest:explain(item,('残局预算允许：低门槛补检；' if item.score<settings.confidence else '残局预算允许：')+'检测实例数少于可用空槽，逐件取走后再观察',True)
        return tuple(out+rest)
    # Explore only with observed tray capacity, never from a missing HUD.
    # All already-planned instances are excluded, including complete triples.
    if settings.exploratory and len(tray)==7 and not out:
        selected={p.instance_id for p in out}
        remaining=[p for p in kept if p.instance_id not in selected]
        capacity=min(1,max(0,free-settings.reserve_slots))
        while remaining and capacity>0 and len(out)<settings.max_clicks:
            def rank(p):
                area=max(0,p.bbox[2]-p.bbox[0])*max(0,p.bbox[3]-p.bbox[1])
                return (counts[p.class_id]==0,-area,p.point_source!='keypoint',-p.score,p.instance_id)
            chosen=min(remaining,key=rank);remaining.remove(chosen);out.append(chosen)
            explain(chosen,'保守探索：已有同类优先，其次框面积；本轮限1件',True)
            capacity-=1;counts[chosen.class_id]+=1
    if trace is not None:
        explained={row['instance_id'] for row in trace}
        for item in kept:
            if item.instance_id in explained:continue
            if free<triple_required and len(groups.get(item.class_id,()))>=3:reason='完整三消的中间占位会侵占预留空槽'
            elif out:reason='本轮已有消除组合或已选一件探索；其余留到下一轮'
            elif free<=settings.reserve_slots:reason='台账容量不足，必须保留空槽'
            elif not settings.exploratory:reason='不足三件且零散取物已关闭'
            elif len(tray)!=7:reason='台账尚未初始化'
            else:reason='不足三件或本轮点击预算不足'
            explain(item,reason)
    return tuple(out)

class TrayLedger:
    """Projected tray from delivered clicks; not proof that the game accepted them.
Vision may seed before the first click and report disagreement afterwards,
never silently erase the click history. Can run without tray vision.
"""
    def __init__(self,use_vision=True):
        self.use_vision=use_vision;self.initialized=not use_vision;self.items=[];self.sent=0;self.history=[];self.reset_time=-math.inf
    def observe(self,tray):
        if not self.use_vision:return True
        if self.sent:return self.initialized
        if not tray:
            self.initialized=True;return True
        if len(tray)==7 and '?' not in tray:
            counts=Counter(c for c in tray if c)
            if any(n>=3 for n in counts.values()):return self.initialized
            self.items=[c for c in tray if c];self.initialized=True
        return self.initialized
    def reset(self,now):
        self.items.clear();self.history.clear();self.initialized=True;self.reset_time=now
    def confirm_prefix(self,packet,now):
        if not self.use_vision or not packet or not 0<=now-packet['captured']<=.35 or packet['captured']<=self.reset_time:return False
        # Replace the entire residual snapshot, including an empty prefix.
        updated=list(packet['prefix'][:7])
        if updated==self.items:return False
        self.items=updated;self.initialized=True;return True
    def refresh_slots(self,packet,now):
        if not self.use_vision or not packet or not 0<=now-packet['captured']<=.35 or packet['captured']<=self.reset_time:return False
        slots=packet.get('slots',[])
        if len(slots)!=7:return False
        # Unknown occupies a slot without inheriting a potentially incorrect old class.
        updated=[]
        for i,row in enumerate(slots):
            value=row['value']
            if value:updated.append(value)
        if updated==self.items:return False
        self.items=updated;self.initialized=True;return True
    def on_sent(self,class_id,timestamp=None):
        if timestamp is not None:self.history.append((timestamp,class_id))
        self.sent+=1;self.items.append(class_id)
        if self.items.count(class_id)>=3:
            remaining=3;kept=[]
            for value in self.items:
                if value==class_id and remaining:remaining-=1
                else:kept.append(value)
            self.items=kept
    def slots(self):return tuple(self.items+['']*max(0,7-len(self.items)))


class RecipeTracker:
    """Reset projected capacity only across a scene transition and stable new HUD.
    Partial target disappearance alone must not erase the click history.
    """
    def __init__(self):
        self.baseline=frozenset();self.armed=False;self.candidate=None;self.streak=0
    def transition(self):
        self.armed=True;self.candidate=None;self.streak=0
    def update(self,targets,tray,ledger):
        current=frozenset(targets)
        if len(current)<2:
            self.candidate=None;self.streak=0;return False
        if not self.baseline:
            self.baseline=current;return False
        empty=(len(tray)==7 and all(c=='' for c in tray))
        changed=len(current-self.baseline)>=2
        if not self.armed or not changed or (ledger.use_vision and not empty):
            self.candidate=None;self.streak=0;return False
        self.streak=self.streak+1 if self.candidate==current else 1
        self.candidate=current
        if self.streak<2:return False
        ledger.items.clear();ledger.initialized=True
        self.baseline=current;self.armed=False;self.candidate=None;self.streak=0
        return True


class BatchController:
    """Default: wait a fixed interval, then replan from a newly captured frame.
Optional disappearance checks are weak evidence, never verified match success.
"""
    def __init__(self,settings=None,ledger=None):
        self.ledger=ledger
        self.settings=settings or Settings();self.pending=();self.last_sent=-math.inf
        self.last_frame=-1;self.absent_frames=0;self.pending_seen_frame=-1;self.executing=False;self.recent_batch_counts=[]
    def record_round(self,count):
        self.recent_batch_counts=(self.recent_batch_counts+[count])[-2:]
    def tray_feedback_mode(self):
        return 'full_slots' if len(self.recent_batch_counts)==2 and sum(self.recent_batch_counts)<3 else 'occupied_minus_three'
    def apply_tray_feedback(self,packet,now):
        if self.executing or not self.ledger or not packet or not math.isfinite(self.last_sent):return False
        if now<self.last_sent+self.settings.batch_interval or packet['captured']<self.last_sent:return False
        if self.tray_feedback_mode()=='full_slots' and packet.get('classification_scope','full_slots')!='full_slots':return False
        return self.ledger.refresh_slots(packet,now) if self.tray_feedback_mode()=='full_slots' else self.ledger.confirm_prefix(packet,now)
    def reconcile(self,observation,now):
        if not self.pending:return 'ready'
        if observation.scene!='playing' or not observation.enabled:return 'blocked'
        if not self.settings.verify_removal:
            deadline=self.last_sent+self.settings.batch_interval
            if now<deadline or observation.captured<deadline or observation.frame_id<=self.last_frame:return 'waiting'
            self.pending=();return 'batch_interval_elapsed'
        if now-self.last_sent>self.settings.confirmation_timeout:return 'unconfirmed_batch'
        if observation.captured<self.last_sent+self.settings.settle or observation.frame_id<=self.pending_seen_frame:return 'waiting'
        self.pending_seen_frame=observation.frame_id
        remaining=any(p.class_id==q.class_id and (math.hypot(p.x-q.x,p.y-q.y)<self.settings.duplicate_radius*2 or overlap(p.bbox,q.bbox)>.3) for p in self.pending for q in observation.items if q.score>=self.settings.confidence)
        self.absent_frames=0 if remaining else self.absent_frames+1
        if self.absent_frames>=self.settings.confirmation_frames:
            self.pending=();self.absent_frames=0;return 'targets_no_longer_detected'
        return 'waiting'
    def execute(self,observation,targets,*,clock,wait,stopped,guard,click,latest,emit):
        if self.pending or observation.frame_id<=self.last_frame:return ()
        execution_trace=[]
        batch=plan(observation,targets,self.settings,clock(),trace=execution_trace)
        tail_mode=any(row['selected'] and row['reason'].startswith('残局预算允许') for row in execution_trace)
        tail_reserve=self.settings.tail_reserve_slots if self.settings.enhanced_tail and 'last_round_clicks' in (observation.ui_details or {}) else 1
        tail_budget=max(0,visible_free_slots(observation)-tail_reserve)
        if not batch:return ()
        emit('batch_planned',frame_id=observation.frame_id,items=[asdict(p) for p in batch],logical_tray=list(observation.tray))
        sent=[];deadline=clock();self.executing=True
        try:
            for item in batch:
                delay=deadline-clock()
                if delay>0 and wait(delay):break
                if stopped():break
                guard()
                current=latest()
                if current and (current.scene!='playing' or not current.enabled):break
                # Snapshot freshness is checked by plan before dispatch; finish this cached round.
                if self.ledger:
                    before=len(self.ledger.items);completes=self.ledger.items.count(item.class_id)>=2
                    after=before+1-(3 if completes else 0)
                    if tail_mode:
                        if len(sent)>=tail_budget:break
                    elif after>7-self.settings.reserve_slots and not (completes and after<before):break
                click(item)
                timestamp=clock();sent.append(item);self.last_sent=timestamp
                if self.ledger:self.ledger.on_sent(item.class_id,timestamp)
                emit('click_sent',frame_id=observation.frame_id,timestamp=timestamp,item=asdict(item),verified=False,logical_tray=list(self.ledger.slots()) if self.ledger else None)
                if self.ledger and len(self.ledger.items)>=7:break
                deadline=timestamp+self.settings.click_interval
        finally:
            self.executing=False
            self.last_frame=observation.frame_id
            self.record_round(len(sent))
            if sent:self.pending=tuple(sent)
            emit('batch_dispatched',frame_id=observation.frame_id,sent=len(sent),planned=len(batch),verified=False,partial=len(sent)!=len(batch))
        return tuple(sent)


class ScenePauseGate:
    """Pause rather than terminate on transient scenes; require fresh recovery."""
    def __init__(self,timeout=60,stable_frames=2):
        self.timeout=timeout;self.stable_frames=stable_frames;self.since=None;self.good=0;self.last=-1
    def update(self,scene,frame_id,now):
        if scene!='playing':
            if self.since is None:self.since=now
            self.good=0;self.last=frame_id
            return 'timeout' if now-self.since>=self.timeout else 'paused'
        if self.since is None:return 'playing'
        if frame_id!=self.last:self.good+=1;self.last=frame_id
        if self.good<self.stable_frames:return 'paused'
        self.since=None;self.good=0;return 'resumed'


class RoundVisionGate:
    """One inference token per round, released after the full click batch."""
    def __init__(self):self.lock=threading.Lock();self.claimed=False;self.after=0.
    def claim(self,captured):
        with self.lock:
            if self.claimed or captured<self.after:return False
            self.claimed=True;return True
    def schedule(self,after):
        with self.lock:self.after=after;self.claimed=False


class OrderContinueController:
    """Known Order-page continue only, with bounded retries for dropped input."""
    def __init__(self,scene='order_transition',delay=5):
        from modular_agent.domains.hololive_dreams.interaction import RetryBudget,policy_for
        self.budget=RetryBudget(policy_for('kitchen_result_continue' if scene=='result_transition' else 'kitchen_order_continue',retry_interval=5,max_attempts=3))
        self.scene=scene;self.delay=delay;self.since=None;self.last_frame=-1;self.streak=0
    def ready(self,scene,frame_id,now,enabled=True,stopped=False):
        if scene!=self.scene:
            self.since=None;self.streak=0
            if scene=='playing':self.budget.attempts=0;self.budget.last=-math.inf
            return False
        if self.since is None:self.since=now
        if frame_id!=self.last_frame:self.streak+=1;self.last_frame=frame_id
        return bool(not stopped and self.streak>=2 and now-self.since>=self.delay and now-self.since<25 and self.budget.ready(now,enabled=enabled))
    def sent(self,now):self.budget.sent(now)
