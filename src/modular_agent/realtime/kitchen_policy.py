"""Inspectable policy parameters and conservative confidence adaptation."""
import math
# attribute, label, default, numeric type, minimum, maximum
POLICY_FIELDS=(
 ('confidence','正常置信度',.25,float,.05,1.),
 ('confidence_ceiling','置信度上限',.40,float,.05,1.),
 ('confidence_min_free','允许降门槛的最少空槽',4,int,1,7),
 ('confidence_visible_limit','降门槛的可见目标上限',8,int,1,100),
 ('confidence_previous_click_limit','上轮少量点击界限',3,int,0,300),
 ('confidence_step','每轮最多降低幅度',.04,float,.001,.5),
 ('confidence_pressure_boost','空槽吃紧时最多提高幅度',.05,float,0,.5),
 ('confidence_slot_weight','空槽权重（须≥另两项之和）',.7,float,.01,10),
 ('confidence_visible_weight','稀疏程度权重',.2,float,0,10),
 ('confidence_click_weight','上轮少点击权重',.1,float,0,10),
 ('tail_visible_limit','强化残局可见目标上限',6,int,1,100),
 ('tail_min_free','强化残局最少空槽',4,int,2,7),
 ('tail_reserve_slots','强化残局至少保留空槽',2,int,1,6),
 ('tail_max_singles','强化残局最多额外零散点击',3,int,1,20),
)
def confidence_state(settings,*,free,visible,candidates,last_clicks,previous,reliable,floor):
    base=min(settings.confidence,settings.confidence_ceiling);floor=min(base,max(.01,floor))
    result=dict(threshold=base,base=base,floor=floor,free=free,visible=visible,candidates=candidates,last_clicks=last_clicks,reliable=reliable,lowered=False,reason='保持正常门槛')
    if not settings.adaptive_confidence or not settings.exploratory:result['reason']='动态调节或零散取物已关闭';return result
    if last_clicks is None:result['reason']='首轮从正常门槛开始';return result
    if not reliable:result['reason']='槽位证据不可靠，不降低门槛';return result
    if free<settings.confidence_min_free:
        pressure=(settings.confidence_min_free-free)/settings.confidence_min_free
        result.update(threshold=min(settings.confidence_ceiling,base+settings.confidence_pressure_boost*pressure),reason='空槽不足，立即恢复或提高门槛')
        return result
    if visible>settings.confidence_visible_limit or candidates>settings.confidence_visible_limit*3:result['reason']='画面仍密集，保持正常门槛';return result
    if last_clicks>settings.confidence_previous_click_limit:result['reason']='上轮仍在大量点击，保持正常门槛';return result
    slot=(free-settings.confidence_min_free+1)/max(1,8-settings.confidence_min_free)
    sparse=max(0,1-visible/settings.confidence_visible_limit)
    slow=1 if settings.confidence_previous_click_limit==0 else max(0,1-last_clicks/settings.confidence_previous_click_limit)
    weights=(settings.confidence_slot_weight,settings.confidence_visible_weight,settings.confidence_click_weight)
    score=(weights[0]*slot+weights[1]*sparse+weights[2]*slow)/sum(weights)
    target=base-(base-floor)*score
    before=min(settings.confidence_ceiling,max(floor,previous if previous is not None and math.isfinite(previous) else base))
    value=max(floor,target,before-settings.confidence_step)
    result.update(threshold=value,lowered=value<base,score=score,reason='空槽充足且稀疏、上轮点击少，逐步降低门槛')
    return result
