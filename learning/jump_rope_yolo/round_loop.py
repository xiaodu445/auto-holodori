"""Offline-testable end-screen loop; live input remains in game_jump_live."""
from collections import Counter
from datetime import datetime
from pathlib import Path
import csv
import json
import cv2
import numpy as np

HERE=Path(__file__).parent

def normalized(image):return cv2.resize(image,(1262,710),interpolation=cv2.INTER_AREA)

class ScreenReader:
    def __init__(self):
        root=HERE/'loop_assets'
        self.templates={name:[(r['box'],cv2.imread(str(root/r['file']))) for r in rows] for name,rows in json.loads((root/'templates.json').read_text()).items()}
        refs=json.loads((HERE/'count_digits_complete_v2.json').read_text(encoding='utf-8'))
        self.refs={k:[np.array(r,bool) for r in values] for k,values in refs['variants'].items()}
    def classify(self,image):
        im=normalized(image);scores={}
        for name,patches in self.templates.items():
            values=[]
            for (x0,y0,x1,y1),ref in patches:
                crop=im[max(0,y0-3):y1+3,max(0,x0-3):x1+3]
                values.append(float(cv2.matchTemplate(crop,ref,cv2.TM_CCOEFF_NORMED).max()))
            scores[name]=min(values)
        name=max(scores,key=scores.get)
        return (name if scores[name]>=.80 else None),scores
    def score(self,image):
        # Only the large current score, excluding the smaller personal best below.
        im=normalized(image);crop=im[255:385,740:1080]
        hsv=cv2.cvtColor(crop,cv2.COLOR_BGR2HSV)
        mask=np.uint8((hsv[:,:,1]<70)&(hsv[:,:,2]>210))*255
        _,_,stats,_=cv2.connectedComponentsWithStats(mask)
        boxes=sorted([r for r in stats[1:] if r[3]>=55 and r[4]>500 and .15<r[2]/r[3]<1.1],key=lambda r:r[0])
        if not 1<=len(boxes)<=3:return None,[]
        digits=[];details=[]
        for x,y,w,h,area in boxes:
            glyph=mask[y:y+h,x:x+w];target=np.zeros((48,40),np.uint8)
            width=min(38,max(1,round(w*46/h)))
            target[1:47,(40-width)//2:(40-width)//2+width]=cv2.resize(glyph,(width,46),interpolation=cv2.INTER_NEAREST)
            shape=target>0
            ranks=sorted([(max(np.count_nonzero(shape&r)/max(1,np.count_nonzero(shape|r)) for r in variants),digit) for digit,variants in self.refs.items()],reverse=True)
            details.append({'digit':ranks[0][1],'score':ranks[0][0],'margin':ranks[0][0]-ranks[1][0]})
            if ranks[0][0]<.55 or ranks[0][0]-ranks[1][0]<.025:return None,details
            digits.append(ranks[0][1])
        return int(''.join(digits)),details
    def gameplay(self,image):
        from counter_reader import counter_glyphs
        im=normalized(image);hsv=cv2.cvtColor(im[255:305,80:200],cv2.COLOR_BGR2HSV)
        green=(hsv[:,:,0]>35)&(hsv[:,:,0]<90)&(hsv[:,:,1]>110)&(hsv[:,:,2]>120)
        return np.count_nonzero(green)>40 and bool(counter_glyphs(im))

class RoundLoop:
    def __init__(self,output,settings=None,reader=None):
        self.settings=settings or {};self.reader=reader or ScreenReader();self.output=Path(output)
        self.output.mkdir(parents=True,exist_ok=True)
        self.candidate=None;self.since=0.;self.last_seen=None;self.last_click=-100.;self.clicked=None;self.attempts=0
        self.in_menus=False;self.awaiting_start=False;self.recorded=False;self.votes=Counter();self.samples=0;self.best_image=None;self.details=[]
        self.play_since=None;self.blocked=False
    def reset_detection(self):
        self.candidate=None;self.last_seen=None;self.play_since=None
    def save_result(self):
        stamp=datetime.now().astimezone();ident=stamp.strftime('%Y%m%d-%H%M%S-%f')
        score,hits=self.votes.most_common(1)[0] if self.votes else (None,0)
        verified=hits>=3 and hits>=self.samples*.6
        row={'time':stamp.isoformat(),'score':score if verified else None,'score_status':'recognized' if verified else 'needs_review','candidate_score':score,'matching_votes':hits,'samples':self.samples,'screenshot':ident+'.png'}
        cv2.imwrite(str(self.output/row['screenshot']),self.best_image)
        (self.output/(ident+'.json')).write_text(json.dumps(dict(row,digit_details=self.details),ensure_ascii=False,indent=2),encoding='utf-8')
        with (self.output/'scores.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
        path=self.output/'scores.csv';new=not path.exists()
        with path.open('a',newline='',encoding='utf-8-sig') as f:
            writer=csv.DictWriter(f,fieldnames=list(row));
            if new:writer.writeheader()
            writer.writerow(row)
        self.recorded=True
        print(f'round_result | score={row["score"]} | status={row["score_status"]} | {row["screenshot"]}',flush=True)
    def update(self,image,now):
        name,scores=self.reader.classify(image)
        action={'block_jump':self.in_menus or name is not None,'screen':name,'scores':scores,'click':None,'new_round':False}
        if name is None:
            self.candidate=None;self.last_seen=None
            if self.in_menus and self.awaiting_start and self.reader.gameplay(image):
                if self.play_since is None:self.play_since=now
                if now-self.play_since>=.5:
                    self.in_menus=False;self.awaiting_start=False;self.recorded=False;self.votes.clear();self.samples=0;self.best_image=None;self.clicked=None;self.attempts=0
                    action.update(block_jump=False,new_round=True)
            else:self.play_since=None
            return action
        self.play_since=None;self.in_menus=True;action['block_jump']=True
        if name!=self.candidate or self.last_seen is None or now-self.last_seen>.3:
            self.candidate=name;self.since=now
            if name!=self.clicked:self.attempts=0
        self.last_seen=now
        if name=='result' and not self.recorded:
            value,details=self.reader.score(image);self.samples+=1;self.best_image=image.copy();self.details=details
            if value is not None:self.votes[value]+=1
        # No blind clicks during transitions; each screen must be independently recognized.
        wait=float(self.settings.get('stable_seconds',.8))
        if name=='result':wait=max(wait,1.2)
        if now-self.since<wait or now-self.last_click<float(self.settings.get('click_interval_seconds',2.)):return action
        if self.clicked==name and now-self.last_click<3.:return action
        if self.attempts>=3:
            if not self.blocked:print('自动循环等待人工检查：同一页面点击3次仍未离开。F8暂停，F12退出。',flush=True)
            self.blocked=True;return action
        self.blocked=False
        if name=='result' and not self.recorded:self.save_result()
        # Never click Boost, currency, advertisements or the event homepage.
        action['click']=(.86,.905);self.clicked=name;self.last_click=now;self.attempts+=1
        if name=='menu':self.awaiting_start=True
        return action
