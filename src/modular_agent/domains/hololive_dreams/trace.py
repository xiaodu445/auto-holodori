"""One entry run per directory, with fresh observations, decisions and result."""
import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4

class EntryTrace:
 def __init__(self,root):
  self.directory=Path(root)/'runtime'/'greed-entry'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid4().hex[:8])
  self.directory.mkdir(parents=True,exist_ok=True)
  self.sequence=0
 def write(self,event,**data):
  self.sequence+=1
  row={'sequence':self.sequence,'time':datetime.now().astimezone().isoformat(),'event':event,**data}
  with (self.directory/'events.jsonl').open('a',encoding='utf-8') as f:
   f.write(json.dumps(row,ensure_ascii=False,default=str)+'\n')
 def observation(self,report,recognition,ocr):
  self.write('observation',recognition=recognition.to_dict(),ocr=ocr,report=report.to_dict())
 def decision(self,decision,recognition):
  self.write('decision',ui=recognition.to_dict(),flow_step=decision.get('state'),decision=decision)
 def result(self,result):
  self.write('result',result=result)
  (self.directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2,default=str),encoding='utf-8')
