"""Small UI anchors from the user's archived MULTI screenshots.

Reference crops contain UI text/icons only. Scores and character portraits are
not used as state evidence. Coordinates below refer to the archived 1260x709
client area (the 38px desktop title bar is excluded when loading references).
"""
from dataclasses import dataclass, field
from pathlib import Path
import cv2
import numpy as np

REFS={
 'portal':('355deb28-b8c8-4e90-acf4-ae94c7ddfbdc',(100,46,300,84)),
 'multi':('355deb28-b8c8-4e90-acf4-ae94c7ddfbdc',(922,260,1080,310)),
 'grade_page':('55bc739d-fa89-486e-b5e6-c5ab1bda0b2d',(652,260,824,310)),
 'grade':('55bc739d-fa89-486e-b5e6-c5ab1bda0b2d',(921,260,1090,310)),
 'matching':('b9bd9a97-c579-467f-b312-e281f99b4ee7',(100,46,230,80)),
 'choosing_others':('ed5dfa2b-5f83-49ce-a30a-4b0b07f8494b',(565,18,733,48)),
 'pickup':('ae214b27-1e43-42e5-b338-25ffe9fc89c4',(908,610,1006,643)),
 'song_header':('ae214b27-1e43-42e5-b338-25ffe9fc89c4',(76,38,136,68)),
 'settings':('29611841-bf0d-4fbf-a113-1f01316f7884',(568,20,722,52)),
 'settings_decide':('29611841-bf0d-4fbf-a113-1f01316f7884',(1115,624,1160,655)),
 'difficulty_easy':('29611841-bf0d-4fbf-a113-1f01316f7884',(704,653,756,680)),
 'difficulty_normal':('29611841-bf0d-4fbf-a113-1f01316f7884',(764,653,842,680)),
 'difficulty_hard':('29611841-bf0d-4fbf-a113-1f01316f7884',(852,653,915,680)),
 'difficulty_expert':('29611841-bf0d-4fbf-a113-1f01316f7884',(926,653,999,680)),
 'loading':('bb7dc6e5-d3cc-43a1-acf4-9e73c28062e9',(1140,651,1240,680)),
 'score':('7fb66b8e-7561-4a23-bf2a-d0ef1255f1af',(301,16,489,47)),
 'next':('7fb66b8e-7561-4a23-bf2a-d0ef1255f1af',(1090,624,1169,657)),
 'get':('2117f56e-7321-4ea2-b2e9-08f666ba2a53',(552,61,711,113)),
 'get_close':('2117f56e-7321-4ea2-b2e9-08f666ba2a53',(586,613,675,643)),
 'achievement':('9d0c8a38-4d48-4087-a932-1eab89c7a4be',(579,108,680,144)),
 'achievement_x':('9d0c8a38-4d48-4087-a932-1eab89c7a4be',(1005,80,1047,121)),
 'exp':('b891672c-1cd6-417d-876b-e25e6ee7c16a',(216,122,308,155)),
 'event':('81b1ad15-29e8-41c5-aa8e-567a00fca017',(673,140,805,166)),
 'again_title':('aadff6b3-7dea-4567-995d-434ff4acce9e',(530,136,714,179)),
 'again':('aadff6b3-7dea-4567-995d-434ff4acce9e',(404,392,572,436)),
}


@dataclass
class LiveFrame:
    state: str
    targets: dict = field(default_factory=dict)
    scores: dict = field(default_factory=dict)
    evidence: str = 'ui_templates'
    key: str = ''
    bounds: tuple = (0,0,1260,709)


class LiveVision:
    def __init__(self,root):
        self.root=Path(root);self.templates={};self.ocr=None
        directory=self.root/'domains/hololive_dreams/data/world_reference/20261021'
        for name,(identifier,rect) in REFS.items():
            path=directory/f'codex-clipboard-{identifier}.png'
            raw=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
            if raw is None:raise ValueError('missing reference: '+str(path))
            client=raw[38:747,:1260];x0,y0,x1,y1=rect
            self.templates[name]=cv2.cvtColor(client[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY)

    def normalize(self,image):
        return cv2.resize(image,(1260,709))

    def match(self,image,name):
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY);x0,y0,x1,y1=REFS[name][1]
        # Search only around the expected UI anchor, with small scale tolerance.
        left=max(0,x0-16);top=max(0,y0-12)
        patch=gray[top:min(709,y1+12),left:min(1260,x1+16)]
        best=(-1.,None)
        for scale in (.97,1.,1.03):
            template=self.templates[name]
            if scale!=1:template=cv2.resize(template,None,fx=scale,fy=scale)
            if template.shape[0]>patch.shape[0] or template.shape[1]>patch.shape[1]:continue
            _,score,_,loc=cv2.minMaxLoc(cv2.matchTemplate(patch,template,cv2.TM_CCOEFF_NORMED))
            if score>best[0]:best=(score,(left+loc[0],top+loc[1],template.shape[1],template.shape[0]))
        return best

    def detect(self,image,bounds=(0,0,1260,709),*,ocr=False,play_detector=None):
        image=self.normalize(image);scores={};rects={}
        def hit(name,threshold=.89):
            if name not in scores:scores[name],rects[name]=self.match(image,name)
            return scores[name]>=threshold
        def target(name,*,white=False):
            if not hit(name):return None
            x,y,w,h=rects[name];patch=image[y:y+h,x:x+w]
            bright=(patch.min(axis=2)>225).mean()
            # The registered labels themselves include the enabled white glyphs.
            saturation=cv2.cvtColor(patch,cv2.COLOR_BGR2HSV)[:,:,1].mean()/255
            if bright<.035 or saturation<.10:return None
            bx,by,bw,bh=bounds
            return {'label':name,'enabled':True,'semantic_confirmed':True,
                    'bounds':{'x':bx+round(x*bw/1260),'y':by+round(y*bh/709),
                              'width':max(1,round(w*bw/1260)),'height':max(1,round(h*bh/709))}}
        def frame(state,**targets):
            return LiveFrame(state,{k:v for k,v in targets.items() if v},scores,bounds=bounds)
        # Modal anchors have precedence over the blurred result header behind them.
        if hit('get') and hit('get_close'):return frame('reward',close=target('get_close'))
        if hit('achievement') and hit('achievement_x'):return frame('achievement',close=target('achievement_x',white=True))
        if hit('again_title') and hit('again'):return frame('again',again=target('again'))
        if hit('loading',.85) or self.match_extra(image,'song_loading','34d0e581-49bf-42d7-a6b8-26786bd9c87c',(1138,650,1240,680))>.85:return frame('loading')
        if hit('score') and hit('next'):
            # Distinguish successive result pages without volatile scores or actors.
            kind='personal' if self._personal(image) else 'score'
            if self.match_extra(image,'score_reward','c5635a36-9e03-4232-8edc-81f49b8a5872',(616,238,708,271))>.89:kind='score_reward'
            return self._key(frame('result',next=target('next')),kind)
        if hit('exp') and hit('next'):return self._key(frame('result',next=target('next')),'exp')
        if hit('event') and hit('next'):return self._key(frame('result',next=target('next')),'event')
        # Difficulty labels sit in the stable bottom bar and do not contain
        # level values or the selected song. Do not wait for the animated title.
        bottom=sum(hit('difficulty_'+name,.85) for name in ('easy','normal','hard','expert'))>=2
        if bottom and hit('settings_decide'):
            result=frame('settings',decide=target('settings_decide'))
            result.evidence='settings_bottom_controls';return result
        if hit('settings'):return frame('settings',decide=target('settings_decide'))
        if hit('pickup') and hit('song_header'):
            # The check glyph is an action icon, not selected-state evidence.
            # Pickup auto-selects/submits a high-score song. Recognition must
            # not depend on the adjacent manual song-confirm button at all.
            return frame('song',pickup=target('pickup'))
        if hit('matching') or hit('choosing_others'):return frame('matching')
        if hit('portal') and hit('multi'):return frame('portal',multi=target('multi'))
        if hit('grade_page') and hit('grade'):return frame('grade',grade=target('grade'))
        if ocr:
            from .visual_features import extract
            features=extract(image,(0,0),self.root)
            if features.get('rank_up') or features.get('reward'):
                bx,by,bw,bh=bounds
                close={'label':'registered_reward_blank','enabled':True,'bounds':{'x':bx+round(bw*.9),'y':by+round(bh*.88),'width':1,'height':1}}
                return LiveFrame('reward',{'close':close},evidence='existing_reward_structure',key='rank_up' if features.get('rank_up') else 'get',bounds=bounds)
            found=self.discover(image,bounds)
            if found:return found
        if play_detector and len(play_detector(image))>=2:return LiveFrame('playing',evidence='existing_rhythm_vision',bounds=bounds)
        return frame('unknown')

    def settlement(self,image):
        """Only result/modal anchor pairs; no OCR or gameplay recognition."""
        image=self.normalize(image)
        for a,b in (('score','next'),('get','get_close'),('achievement','achievement_x'),('again_title','again')):
            if self.match(image,a)[0]>=.89 and self.match(image,b)[0]>=.89:return True
        return False

    def gameplay_hud(self,image):
        """Stable SCORE/LIFE/key badges, independent of notes and score values."""
        if 'hud_score' not in self.templates:
            path=self.root/'domains/hololive_dreams/data/multi_live/rhythm_hud_reference.jpg'
            raw=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)
            if raw is None:raise ValueError('missing gameplay HUD reference')
            source=cv2.resize(raw[:356,:632],(1260,709))
            self.hud_rects={'hud_score':(142,18,470,52),'hud_life':(980,20,1028,52)}
            for index,x in enumerate((140,330,520,710,900,1090)):
                self.hud_rects['hud_key'+str(index)]=(x,652,x+32,687)
            for name,(x0,y0,x1,y1) in self.hud_rects.items():
                self.templates[name]=cv2.cvtColor(source[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY)
        image=self.normalize(image);gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY)
        def hit(name):
            x0,y0,x1,y1=self.hud_rects[name]
            patch=gray[max(0,y0-9):min(709,y1+9),max(0,x0-12):min(1260,x1+12)]
            return cv2.matchTemplate(patch,self.templates[name],cv2.TM_CCOEFF_NORMED).max()>=.85
        return hit('hud_score') and hit('hud_life') and sum(hit('hud_key'+str(i)) for i in range(6))>=3

    def _personal(self,image):
        # Stable judgement words separate personal score from team score/reward pages.
        return self.match_extra(image,'personal', '01901215-aa8e-40b7-a7c0-d87a07882053',(592,274,715,307))>.89

    def match_extra(self,image,name,identifier,rect):
        if name not in self.templates:
            path=self.root/f'domains/hololive_dreams/data/world_reference/20261021/codex-clipboard-{identifier}.png'
            raw=cv2.imdecode(np.fromfile(path,dtype=np.uint8),cv2.IMREAD_COLOR)[38:747,:1260]
            x0,y0,x1,y1=rect;self.templates[name]=cv2.cvtColor(raw[y0:y1,x0:x1],cv2.COLOR_BGR2GRAY)
        x0,y0,x1,y1=rect;patch=cv2.cvtColor(image[max(0,y0-8):y1+8,max(0,x0-8):x1+8],cv2.COLOR_BGR2GRAY)
        return float(cv2.matchTemplate(patch,self.templates[name],cv2.TM_CCOEFF_NORMED).max())

    @staticmethod
    def _key(frame,key):frame.key=key;return frame

    def discover(self,image,bounds):
        from modular_agent.perception.ocr import LocalOCR
        from modular_agent.perception.buttons import ButtonDetector
        from modular_agent.perception.report import ScreenReport
        from .popup_recovery import annotate
        from .interaction import text_button
        if self.ocr is None:self.ocr=LocalOCR()
        texts=self.ocr.recognize(image)
        words=[''.join(t['text'].split()).lower() for t in texts]
        forbidden=('购买','充值','兑换','体力不足','补充体力','连接失败','断开连接','登录失败','发生错误')
        if any(w in t for w in forbidden for t in words):return LiveFrame('blocked',evidence='ocr_error',bounds=bounds)
        if any('决定成员' in t or '确认成员' in t or '匹配中' in t for t in words):return LiveFrame('matching',bounds=bounds)
        if any('loading' in t or '加载中' in t for t in words):return LiveFrame('loading',bounds=bounds)
        # Only a confirmed world HUD authorizes opening Live Portal by its current OCR label.
        if sum(any(w==t for t in words) for w in ('活动','游戏','演出','任务','成就','扭蛋'))>=4:
            stage=next((t for t in texts if t['text'].strip()=='演出' and t['confidence']>=.9),None)
            if stage:
                target=self._map_target(stage['bounds'],bounds,'演出')
                return LiveFrame('world',{'stage':target},evidence='ocr_hud',bounds=bounds)
        report=ScreenReport(frame={'bounds':{'x':0,'y':0,'width':1260,'height':709}},texts=texts,
                            buttons=ButtonDetector().detect(image))
        for t in texts:
            # Synonyms retain the registered popup title/colour requirements.
            word=t['text'].strip().lower()
            if word=='ok':t['text']='确定'
            elif word=='下一波':t['text']='下一步'
            q=t['bounds']
            t['button_ids']=[b['id'] for b in report.buttons if self._contains(b['bounds'],q)]
        annotate(report,image,(0,0))
        button=text_button(report,('确定','继续','下一步','关闭'),known_page=bool(report.frame.get('confirmed_popup')))
        if button:
            return LiveFrame('popup',{'close':self._map_target(button['bounds'],bounds,button['label'])},
                             evidence='registered_popup_ocr',key=str(report.frame['confirmed_popup']),bounds=bounds)
        return None

    @staticmethod
    def _contains(a,b):
        return a['x']<=b['x'] and a['y']<=b['y'] and a['x']+a['width']>=b['x']+b['width'] and a['y']+a['height']>=b['y']+b['height']

    @staticmethod
    def _map_target(q,bounds,label):
        x,y,w,h=bounds
        return {'label':label,'enabled':True,'bounds':{'x':x+round(q['x']*w/1260),'y':y+round(q['y']*h/709),
                'width':max(1,round(q['width']*w/1260)),'height':max(1,round(q['height']*h/709))}}
