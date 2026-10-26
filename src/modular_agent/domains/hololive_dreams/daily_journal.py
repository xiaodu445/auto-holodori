"""Event and optional reward-evidence journal; no fabricated reward amounts."""
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

class DailyJournal:
 def __init__(self,root,on_event=None):
  self.directory=Path(root)/'runtime/daily-tasks'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
  self.directory.mkdir(parents=True,exist_ok=True)
  self.sequence=0;self.on_event=on_event;self.callback_errors=[]
 def __call__(self,event,**payload):
  self.sequence+=1
  row={'sequence':self.sequence,'time':datetime.now().astimezone().isoformat(),'event':event,**payload}
  with (self.directory/'events.jsonl').open('a',encoding='utf-8') as f:
   f.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')
  if self.on_event:
   try:self.on_event(dict(row))
   except Exception as error:self.callback_errors.append(str(error))
 def finish(self,result):
  self('result',result=result)
  (self.directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')

class RewardRecorder:
 def __init__(self,enabled=False,reader=None,sink=None):
  self.enabled=enabled;self.reader=reader;self.sink=sink;self.active=False;self.records=[]
 def observe(self,report,visible,task):
  if not self.enabled:return
  if not visible:self.active=False;return
  if self.active:return
  self.active=True
  row={'task':task,'verification':'reward_overlay_observed','amounts_verified':False,
       'items':[],'observed_at':report.observed_at,'texts':report.texts,
       'templates':report.knowledge_matches}
  if self.reader:
   try:
    reading=self.reader(report)
    if not isinstance(reading,dict) or not isinstance(reading.get('items',[]),list):
     raise ValueError('奖励reader需返回含items列表的字典')
    row['reader_result']=reading
    # Keep inventory-credit verification separate from reading displayed text.
   except Exception as error:row['reader_error']=str(error)
  self.records.append(row)
  if self.sink:self.sink('reward_evidence',record=row)
