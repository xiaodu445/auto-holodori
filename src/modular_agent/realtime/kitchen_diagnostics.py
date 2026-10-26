"""Read-only replay analysis; historical reconstructions are explicitly labelled."""
from dataclasses import fields,replace
from collections import Counter
from .kitchen_match import Item,Observation,Settings,plan

def snapshot(events,t):
    visible=[e for e in events if e.get('t',0)<=t]
    detections=[e for e in visible if e['type']=='detection']
    start=next((e for e in visible if e['type']=='session_start'),{})
    ledger_events=[e for e in visible if e.get('logical_tray') is not None]
    logical=ledger_events[-1]['logical_tray'] if ledger_events else None
    clicks=[e for e in visible if e['type']=='click_sent']
    pages=[e for e in visible if e['type'] in ('scene_paused','scene_resumed')]
    settings=start.get('settings',{})
    result=dict(time=t,logical_tray=logical,settings=settings,click_count=len(clicks),last_click=clicks[-1] if clicks else None,page_event=pages[-1] if pages else None,model=start.get('weights','未知'),source='尚无检测',trace=[],observation=None,decision_tray=None,confidence_policy=None)
    readings=[e for e in visible if e['type'] in ('tray_visual_evidence','tray_correction') and e.get('evidence')]
    corrections=[e for e in visible if e['type']=='tray_correction']
    result['slot_reading']=readings[-1] if readings else None
    result['slot_correction']=corrections[-1] if corrections else None
    if not detections:return result
    detection=max(detections,key=lambda e:e.get('t',e['observation']['finished']));raw=detection['observation']
    result['observation']=raw
    actual=[e for e in visible if e['type']=='decision' and e.get('frame_id')==raw['frame_id']]
    if actual:
        event=actual[-1];result.update(source='当时实际决策日志',trace=event['items'],decision_tray=event['logical_tray'],targets=event.get('targets',[]),confidence_policy=event.get('confidence_policy'))
    else:
        # An old recording has no rejection reasons: simulate, never claim historical fact.
        context=[e for e in ledger_events if e.get('t',0)<=detection.get('t',raw['finished'])+.01]
        batch=[e for e in visible if e['type']=='batch_planned' and e.get('frame_id')==raw['frame_id']]
        tray=batch[-1].get('logical_tray') if batch else context[-1]['logical_tray'] if context else raw.get('tray',())
        observation=Observation(**{**raw,'items':tuple(Item(**p) for p in raw['items']),'tray':tuple(tray or ())})
        targets=set(start.get('targets',[]))
        order=[e for e in visible if e['type']=='order_targets' and e.get('t',0)<=detection.get('t',raw['finished'])]
        if order:targets.update(order[-1].get('targets',[]))
        trace=[]
        allowed={f.name for f in fields(Settings)}
        config=Settings(**{k:v for k,v in settings.items() if k in allowed})
        plan(observation,targets,config,observation.finished,trace=trace)
        result.update(source='旧录像：按现行逻辑回算（非当时执行原因）',trace=trace,decision_tray=list(observation.tray),targets=list(targets|set(observation.targets)))
    return result
