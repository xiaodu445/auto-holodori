"""Local fishing strategy-tree entry; OCR only at round boundaries."""
import argparse
import importlib.util
import json
from pathlib import Path
import time
import unicodedata
import cv2
import numpy as np
from pathlib import Path
from modular_agent.core import Action, Outcome
from modular_agent.computer import ActionComputer
from modular_agent.perception import GeneralVision
from modular_agent.realtime.fishing import load,run_fishing
from modular_agent.realtime.runtime import WindowCapture

def load_tree(root):
    spec=importlib.util.spec_from_file_location('hololive_fishing_loop',Path(root)/'domains/hololive_dreams/models/fishing_loop.py')
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module.FishingLoop

class LoopObserver:
    def __init__(self,root,handle,config_path=None):
        self.config,_,self.detector=load(root,config_path)
        self.capture=WindowCapture(handle)
        self.vision=None
        self.last_boundary=None
        self.recovery_toggle=0
        try: self.initial_bounds=self.capture.bounds()
        except Exception:
            self.capture.close()
            raise
    def close(self):
        try:
            if self.vision is not None: self.vision.close()
        finally: self.capture.close()
    def __call__(self):
        bounds=self.capture.bounds()
        if bounds[2:]!=self.initial_bounds[2:]: raise RuntimeError('window_resized_recalibrate')
        image,current=self.capture.grab(self.config['control_roi'])
        if self.detector.control(image).get('valid'): return {'state':'control','bounds':current}
        image,current=self.capture.grab(self.config['bite_roi'])
        if self.detector.bite(image).get('bite'): return {'state':'bite','bounds':current}
        image,current=self.capture.grab([0,0,1,1])
        visual=self.find_dismiss_prompt(image,current) or self.find_continue_button(image,current) or self.find_close_icon(image,current)
        if self.capture.bounds()!=current: raise RuntimeError('window_changed_during_settlement')
        if visual: return visual
        roi=self.config.get('continue_roi',[.60,.65,1,1])
        image,current=self.capture.grab(roi)
        self.last_boundary=image.copy()
        if self.vision is None:
            self.vision=GeneralVision(enable_ocr=True,enable_uia=False,enable_cv_buttons=False,enable_knowledge=False)
        x,y,w,h=current
        origin=(x+round(roi[0]*w),y+round(roi[1]*h))
        report=self.vision.analyze(image,origin=origin,enable_ocr=True,enable_uia=False,
                                  enable_cv_buttons=False,enable_knowledge=False,template_names=[])
        if report.capabilities.get('ocr')=='failed': raise RuntimeError('settlement_ocr_failed')
        if self.capture.bounds()!=current: raise RuntimeError('window_changed_during_settlement')
        return self.classify(report,current,roi)
    @staticmethod
    def classify(report,bounds,roi):
        x,y,w,h=bounds
        labels={'继续','点击继续'}
        matches=[]
        for row in report.texts:
            text=''.join(unicodedata.normalize('NFKC',row.get('text','')).split())
            if '继续' not in text or row.get('confidence',0)<.65: continue
            box=row.get('bounds',{})
            if not all(k in box for k in ('x','y','width','height')): continue
            cx=box['x']+box['width']/2; cy=box['y']+box['height']/2
            if box['width']<=0 or box['height']<=0: continue
            if (x+roi[0]*w<=cx<x+roi[2]*w and y+roi[1]*h<=cy<y+roi[3]*h):
                matches.append((round(cx),round(cy)))
        if len(matches)==1: return dict(state='continue',point=matches[0],bounds=bounds)
        return dict(state='unknown',bounds=bounds)
    def probe_waiting(self):
        """Once-per-second boundary CV on the right part of the client; no OCR."""
        image, bounds = self.capture.grab([.60, 0, 1, 1])
        if bounds[2:] != self.initial_bounds[2:]:
            raise RuntimeError('window_resized_recalibrate')
        x, y, w, h = bounds
        cropped_bounds = (x + round(.60*w), y, image.shape[1], h)
        target = self.find_continue_button(image, cropped_bounds)
        if target is None:
            target = self.find_close_icon(image, cropped_bounds)
        if target is None:
            prompt, prompt_bounds = self.capture.grab([.40, .82, .60, .97])
            if prompt_bounds != bounds: raise RuntimeError('window_changed_during_waiting_probe')
            prompt_origin = (x+round(.40*w), y+round(.82*h), prompt.shape[1], prompt.shape[0])
            target = self.find_dismiss_prompt(prompt, prompt_origin, cropped=True)
        if self.capture.bounds() != bounds:
            raise RuntimeError('window_changed_during_waiting_probe')
        if target:
            target['bounds'] = bounds
        return target

    def recovery(self):
        known=self()
        if known['state'] in ('control','bite','continue','dismiss','close'): return known
        # Broader local OCR is allowed only after the real-time component yields.
        bounds=self.capture.bounds()
        if bounds[2:]!=self.initial_bounds[2:]: raise RuntimeError('window_resized_recalibrate')
        image,current=self.capture.grab([0,0,1,1])
        self.last_boundary=image.copy()
        if self.vision is None:
            self.vision=GeneralVision(enable_ocr=True,enable_uia=False,enable_cv_buttons=False,enable_knowledge=False)
        report=self.vision.analyze(image,origin=current[:2],enable_ocr=True,enable_uia=False,
                                  enable_cv_buttons=False,enable_knowledge=False,template_names=[])
        if report.capabilities.get('ocr')=='failed': raise RuntimeError('recovery_ocr_failed')
        if self.capture.bounds()!=current: raise RuntimeError('window_changed_during_recovery')
        visual = self.find_close_icon(image, current)
        return visual or self.classify_recovery(report,current)
    @staticmethod
    def find_dismiss_prompt(image, bounds, cropped=False):
        """Recognize the explicit click-to-close label; no broad cyan-circle match."""
        path = Path(__file__).resolve().parents[3] / 'domains/hololive_dreams/data/fishing_samples/reward-dismiss-text.png'
        template = cv2.imread(str(path))
        if template is None: return None
        x,y,w,h = bounds
        left,top = (0,0) if cropped else (round(w*.40),round(h*.82))
        region = image if cropped else image[top:round(h*.97),left:round(w*.60)]
        def white(im):
            hsv=cv2.cvtColor(im,cv2.COLOR_BGR2HSV)
            return cv2.inRange(hsv,np.array([0,0,220],np.uint8),np.array([179,60,255],np.uint8))
        search=white(region); reference=white(template)
        best=None
        for scale in (.65,.75,.85,1.0,1.15,1.3,1.5):
            scaled=cv2.resize(reference,None,fx=scale,fy=scale,interpolation=cv2.INTER_NEAREST)
            th,tw=scaled.shape
            if th>search.shape[0] or tw>search.shape[1]: continue
            _,score,_,point=cv2.minMaxLoc(cv2.matchTemplate(search,scaled,cv2.TM_CCOEFF_NORMED))
            if score>=.80 and (best is None or score>best[0]): best=(score,point,tw,th)
        if best is None: return None
        _,(px,py),tw,th=best
        return dict(state='dismiss',point=(x+left+px+tw//2,y+top+py+th//2),bounds=bounds)

    @staticmethod
    def find_close_icon(image, bounds):
        # The cyan circle is shared by X and the normal fishing back arrow.
        # Compare the inner glyph, never accept the outer circle alone.
        template_path = Path(__file__).resolve().parents[3] / 'domains/hololive_dreams/data/fishing_samples/catalog-close.png'
        template = cv2.imread(str(template_path), cv2.IMREAD_COLOR)
        if template is None: return None
        def glyph(mask):
            height, width = mask.shape
            inner = mask[round(height*.23):round(height*.77), round(width*.23):round(width*.77)]
            points = cv2.findNonZero(inner)
            if points is None: return None
            l,t,w,h = cv2.boundingRect(points)
            if not .8 <= w/max(h,1) <= 1.25: return None
            return cv2.resize(inner[t:t+h,l:l+w], (32,32), interpolation=cv2.INTER_NEAREST) > 0
        def cyan(image):
            return cv2.inRange(cv2.cvtColor(image, cv2.COLOR_BGR2HSV),
                               np.array([80,80,120],np.uint8),np.array([110,255,255],np.uint8))
        template_mask = cyan(template)
        template_contours,_=cv2.findContours(template_mask,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
        reference=None
        for contour in template_contours:
            l,t,tw,th=cv2.boundingRect(contour)
            if 15<=tw<=40 and 15<=th<=40 and abs(l+tw/2-40)<8 and abs(t+th/2-40)<8:
                reference=cv2.resize(template_mask[t:t+th,l:l+tw],(32,32),interpolation=cv2.INTER_NEAREST)>0
                break
        if reference is None: return None
        mask = cyan(image)
        contours, _ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        x,y,w,h=bounds; candidates=[]
        for c in contours:
            left,top,width,height=cv2.boundingRect(c)
            area=cv2.contourArea(c); cx,cy=left+width/2,top+height/2
            if not (.75<width/max(1,height)<1.3 and width<w*.16 and height<h*.2
                    and w*.70<cx<w and 0<cy<h*.35): continue
            # Inspect both enclosing buttons and disconnected inner glyphs. The
            # circle may join the cyan page background; RETR_LIST retains its X.
            if area>=w*h*.0004:
                candidate = glyph(mask[top:top+height,left:left+width])
            else:
                candidate = None
            direct = None
            if width>=12 and height>=12 and area>=80:
                direct=cv2.resize(mask[top:top+height,left:left+width],(32,32),interpolation=cv2.INTER_NEAREST)>0
            variants=[v for v in (candidate,direct) if v is not None]
            if not variants: continue
            candidate=max(variants,key=lambda v:np.logical_and(v,reference).sum()/max(1,np.logical_or(v,reference).sum()))
            overlap = np.logical_and(candidate,reference).sum()/max(1,np.logical_or(candidate,reference).sum())
            if overlap >= .70:
                point=(round(x+cx),round(y+cy))
                if not any(max(abs(a-b) for a,b in zip(point,old))<=8 for old in candidates):
                    candidates.append(point)
        return dict(state='close',point=candidates[0],bounds=bounds) if len(candidates)==1 else None
    @staticmethod
    def find_continue_button(image, bounds):
        """Orange rounded continue button in the lower-right reward overlay."""
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, np.array([8, 80, 150], np.uint8), np.array([35, 255, 255], np.uint8))
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        x,y,w,h=bounds; candidates=[]
        for c in contours:
            left,top,width,height=cv2.boundingRect(c)
            area=cv2.contourArea(c); cx,cy=left+width/2,top+height/2
            if area>=w*h*.003 and width>w*.12 and height>h*.04 and y+h*.72<y+cy<y+h and x+w*.55< x+cx < x+w:
                candidates.append((round(x+cx),round(y+cy)))
        return dict(state='continue',point=max(candidates),bounds=bounds) if candidates else None
    @staticmethod
    def classify_recovery(report,bounds):
        x,y,w,h=bounds
        closes=[]
        for row in report.texts:
            text=unicodedata.normalize('NFKC',row.get('text','')).strip().lower()
            box=row.get('bounds',{})
            if text not in ('x','×','✕','✖','关闭') or row.get('confidence',0)<.85: continue
            if not all(k in box for k in ('x','y','width','height')): continue
            cx=box['x']+box['width']/2; cy=box['y']+box['height']/2
            # Small standalone close labels in the right upper part of client area.
            if (0<box['width']<w*.12 and 0<box['height']<h*.12
                    and x+w*.5<=cx<x+w and y<=cy<y+h*.65): closes.append((round(cx),round(cy)))
        if len(closes)==1: return dict(state='close',point=closes[0],bounds=bounds)
        return LoopObserver.classify(report,bounds,[0,0,1,1])
    def click(self,observation,computer):
        if self.capture.bounds()!=observation['bounds']: raise RuntimeError('window_changed_before_continue')
        computer.release_all()
        x,y=observation['point']
        # Fishing UI exception: user confirmed no Alt. Do not use top-level Alt policy.
        def send(name, arguments):
            result=computer.perform(Action(name,arguments=arguments))
            if result.outcome!=Outcome.SUCCESS: raise RuntimeError(result.message)
        try:
            send('move_to',{'x':x,'y':y})
            send('wait',{'duration':.08})
            if self.capture.bounds()!=observation['bounds']: raise RuntimeError('window_changed_before_press')
            send('mouse_down',{'button':'left'})
            send('wait',{'duration':.12})
            send('mouse_up',{'button':'left'})
        finally:
            computer.release_all()

def run_fishing_loop(root,computer,handle,*,live=False,phase='auto',config_path=None,
                     max_rounds=999,timeout=360000,should_yield=lambda:False,progress=print):
    if live and not computer.live: raise ValueError('live requires a live computer')
    if computer.keys or computer.buttons: raise ValueError('fishing loop requires exclusive released input')
    tree=load_tree(root)(max_rounds=max_rounds,timeout=timeout)
    observer=None
    try:
        observer=LoopObserver(root,handle,config_path)
        result=tree.run(observer,lambda phase,remaining:run_fishing(root,computer,handle,
                        live=live,phase=phase,config_path=config_path,timeout=remaining,
                        should_yield=should_yield,progress=progress,boundary_probe=observer.probe_waiting),
                        lambda o:observer.click(o,computer),computer,phase=phase,live=live,
                        should_yield=should_yield,progress=progress,observe_recovery=observer.recovery,
                        click_recovery=lambda o:observer.click(o,computer))
    finally:
        try: computer.release_all()
        finally:
            if observer is not None: observer.close()
    path=Path(root)/'runtime/fishing/loop-result.json'; path.parent.mkdir(parents=True,exist_ok=True)
    if result.get('reason') in ('settlement_unknown','continue_not_dismissed','continue_changed_before_click','initial_state_unknown') and observer.last_boundary is not None:
        import cv2
        screenshot=path.parent/'last-boundary.png'
        cv2.imwrite(str(screenshot),observer.last_boundary)
        result['boundary_screenshot']=str(screenshot.resolve())
    path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result

def main():
    p=argparse.ArgumentParser(description='Fishing local strategy tree; default no input')
    p.add_argument('--project-root',default='.'); p.add_argument('--config')
    p.add_argument('--live',action='store_true'); p.add_argument('--window-handle',type=int)
    p.add_argument('--phase',choices=['auto','waiting','control'],default='auto')
    p.add_argument('--max-rounds',type=int,default=999); p.add_argument('--timeout',type=float,default=360000)
    p.add_argument('--start-delay',type=float,default=3)
    a=p.parse_args(); root=Path(a.project_root).resolve()
    import math
    if not math.isfinite(a.start_delay) or not 0<=a.start_delay<=30: p.error('invalid start delay')
    load_tree(root)(max_rounds=a.max_rounds,timeout=a.timeout)
    if a.window_handle is None:
        from modular_agent.computer.windows import WindowsBackend
        windows=[w for w in WindowsBackend().windows() if 'hololive-dreams' in w['title'].lower()]
        if len(windows)!=1: p.error('specify --window-handle')
        a.window_handle=windows[0]['handle']
    with ActionComputer(live=a.live,audit_path=root/'runtime/computer-actions.jsonl') as computer:
        print(f'请切回游戏；{a.start_delay:g}秒后开始钓鱼循环，live={a.live}',flush=True)
        until=time.monotonic()+a.start_delay
        while time.monotonic()<until and not computer.stopped: time.sleep(.01)
        if computer.stopped: return
        print(json.dumps(run_fishing_loop(root,computer,a.window_handle,live=a.live,phase=a.phase,
              config_path=a.config,max_rounds=a.max_rounds,timeout=a.timeout),ensure_ascii=False,indent=2))
if __name__=='__main__': main()














