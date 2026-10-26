"""Local perception facade for general and domain agents; no external model calls."""
from __future__ import annotations
import time
import hashlib
import threading
from .options import serialized,validate,crop,rectangle
import cv2
from pathlib import Path
import numpy as np
from .buttons import ButtonDetector
from .desktop import DesktopReader
from .knowledge import KnowledgeMatcher
from .ocr import LocalOCR
from .report import Rect, ScreenReport
from .screen import capture_monitor
from .search import SearchMixin

class GeneralVision(SearchMixin):
    def __init__(self,*,ocr=None,desktop=None,knowledge=None,enable_ocr=True,
                 enable_uia=True,enable_cv_buttons=True,enable_knowledge=True):
        validate(enable_ocr=enable_ocr,enable_uia=enable_uia,enable_cv_buttons=enable_cv_buttons,enable_knowledge=enable_knowledge)
        self._request_lock=threading.RLock()
        self._closed=False
        self.enable_knowledge=enable_knowledge
        self.ocr=ocr if ocr is not None else LocalOCR()
        self.desktop=desktop if desktop is not None else DesktopReader()
        self.knowledge=knowledge if knowledge is not None else KnowledgeMatcher()
        self.enable_ocr=enable_ocr
        self.enable_uia=enable_uia
        self.enable_cv_buttons=enable_cv_buttons
        self.detector=ButtonDetector()
        self.console_handle=0
        import os
        if os.name=='nt':
            import ctypes
            get_console=ctypes.windll.kernel32.GetConsoleWindow
            get_console.restype=ctypes.c_void_p
            self.console_handle=get_console() or 0

    @serialized
    def warmup(self,progress=lambda message:None):
        # Keep work sequential to avoid loading multiple large models at once.
        stages=[]
        if self.enable_ocr and hasattr(self.ocr,'warmup'): stages.append(('OCR',self.ocr.warmup))
        if self.enable_uia and hasattr(self.desktop,'warmup'): stages.append(('窗口控件常驻进程',self.desktop.warmup))
        if self.enable_knowledge and hasattr(self.knowledge,'warmup'): stages.append(('图标模板缓存',self.knowledge.warmup))
        for name,operation in stages:
            start=time.perf_counter()
            try:
                operation()
                progress(f'{name}预热完成（{(time.perf_counter()-start)*1000:.0f} 毫秒）。')
            except Exception as error: progress(f'{name}预热未完成，将按需重试：{type(error).__name__}')

    @serialized
    def close(self):
        if self._closed: return
        self._closed=True
        if hasattr(self.desktop,'close'): self.desktop.close()

    @classmethod
    def for_project(cls,root,domain=None,**kwargs):
        from .template_library import TemplateLibrary
        root=Path(root)
        libraries=[]
        paths=[root/'knowledge'/'vision_library']
        if domain:
            import re
            if not re.fullmatch(r'[a-z][a-z0-9_-]*',domain): raise ValueError('Invalid domain')
            paths.append(root/'domains'/domain/'vision_library')
        for path in paths:
            if (path/'registry.json').exists(): libraries.append(TemplateLibrary(path))
        return cls(knowledge=KnowledgeMatcher(libraries),**kwargs)

    @serialized
    def observe(self,monitor=0,environment='default',window_handle=None,*,enable_ocr=None,enable_uia=None,enable_cv_buttons=None,ocr_max_side=None,prefer_templates=False,template_priority_exclude=(),enable_knowledge=None,template_names=None,template_scales=None,template_threshold=None,region=None):
        validate(enable_ocr=enable_ocr,enable_uia=enable_uia,enable_cv_buttons=enable_cv_buttons,enable_knowledge=enable_knowledge,ocr_max_side=ocr_max_side,template_names=template_names,template_scales=template_scales,template_threshold=template_threshold,region=region)
        if not isinstance(environment,str) or not environment.strip() or len(environment)>128: raise ValueError('Invalid environment')
        if type(prefer_templates) is not bool: raise ValueError('Invalid mode flag')
        if type(monitor) is not int or monitor<0: raise ValueError('Invalid monitor')
        if window_handle is not None and (type(window_handle) is not int or window_handle<=0): raise ValueError('Invalid window handle')
        start=time.perf_counter()
        windows=[]; warnings=[]
        try: windows=self.desktop.windows()
        except Exception as error: warnings.append(f'Window enumeration failed: {error}')
        image,frame=capture_monitor(monitor)
        origin=(frame.left,frame.top)
        if window_handle is not None:
            window=next((w for w in windows if w['handle']==window_handle),None)
            if window is None or window['minimized']: raise ValueError('Requested window unavailable or minimized')
            screen=Rect(origin[0],origin[1],frame.width,frame.height)
            bounds=Rect.from_bbox(window['bounds']['bbox']).intersection(screen)
            if not bounds.area: raise ValueError('Window is outside captured monitor')
            x,y=bounds.x-origin[0],bounds.y-origin[1]
            image=image[y:y+bounds.height,x:x+bounds.width].copy()
            origin=(bounds.x,bounds.y)
        image,origin=crop(image,origin,region)
        # Do not feed our own progress back into OCR/template decisions.
        ignored=[w for w in windows if (self.console_handle and w.get('handle')==self.console_handle) or w.get('title','').startswith(('Agent 日志（','start_agent.cmd'))]
        target=next((w for w in windows if w.get('handle')==window_handle),None)
        masked_windows=[]
        for window in ignored:
            if window.get('minimized'): continue
            # EnumWindows returns top-to-bottom order. Background consoles do not occlude the game.
            if target and (target.get('foreground') and not window.get('foreground') and window.get('z_order',float('inf'))>target.get('z_order',-1)):
                continue
            if target and 'z_order' in target and 'z_order' in window and window['z_order']>target['z_order']:
                continue
            masked=Rect.from_bbox(window['bounds']['bbox']).intersection(Rect(origin[0],origin[1],image.shape[1],image.shape[0]))
            if masked.area:
                masked_windows.append({'handle':window['handle'],'bounds':masked.to_dict()})
                x,y=masked.x-origin[0],masked.y-origin[1]
                image[y:y+masked.height,x:x+masked.width]=0
        windows=[w for w in windows if w not in ignored]
        capture_ms=(time.perf_counter()-start)*1000
        report=self.analyze(image,origin=origin,environment=environment,windows=windows,
            read_controls=True,window_handle=window_handle,enable_ocr=enable_ocr,enable_uia=enable_uia,enable_cv_buttons=enable_cv_buttons,ocr_max_side=ocr_max_side,prefer_templates=prefer_templates,template_priority_exclude=template_priority_exclude,enable_knowledge=enable_knowledge,template_names=template_names,template_scales=template_scales,template_threshold=template_threshold)
        report.frame.update({'source':'screen','monitor':monitor,
                             'captured_at':frame.captured_at.isoformat()})
        if region is not None: report.frame['requested_region']=rectangle(region).to_dict()
        report.frame['masked_agent_regions']=masked_windows
        report.frame['excluded_agent_windows']=[w['handle'] for w in ignored]
        if window_handle is not None:
            report.frame['target_window_handle']=window_handle
            report.frame['capture_method']='visible_desktop_crop'
            report.warnings.append('这是可见桌面裁剪；遮挡区域不包含游戏实际像素，空白 OCR 不代表未截图。')
        report.warnings[:0]=warnings
        report.capabilities['windows']='ok' if not warnings else 'failed'
        report.timings_ms['capture_and_windows']=round(capture_ms,2)
        return report

    @serialized
    def analyze(self,image,*,origin=(0,0),environment='default',windows=(),
                read_controls=False,window_handle=None,enable_ocr=None,enable_uia=None,enable_cv_buttons=None,ocr_max_side=None,prefer_templates=False,template_priority_exclude=(),enable_knowledge=None,template_names=None,template_scales=None,template_threshold=None,region=None):
        validate(enable_ocr=enable_ocr,enable_uia=enable_uia,enable_cv_buttons=enable_cv_buttons,enable_knowledge=enable_knowledge,ocr_max_side=ocr_max_side,template_names=template_names,template_scales=template_scales,template_threshold=template_threshold,region=region)
        if not isinstance(environment,str) or not environment.strip() or len(environment)>128: raise ValueError('Invalid environment')
        if type(read_controls) is not bool or type(prefer_templates) is not bool: raise ValueError('Invalid mode flag')
        use_knowledge=self.enable_knowledge if enable_knowledge is None else enable_knowledge
        use_ocr=self.enable_ocr if enable_ocr is None else enable_ocr
        use_uia=self.enable_uia if enable_uia is None else enable_uia
        use_cv=self.enable_cv_buttons if enable_cv_buttons is None else enable_cv_buttons
        if not isinstance(image,np.ndarray) or image.size==0 or image.dtype!=np.uint8 or image.ndim not in (2,3):
            raise ValueError('Expected a nonempty uint8 image')
        if image.ndim==3 and image.shape[2]!=3: raise ValueError('Expected BGR image with three channels')
        if len(origin)!=2 or any(type(v) is not int for v in origin): raise ValueError('Origin must contain two integers')
        image,origin=crop(image,origin,region)
        height,width=image.shape[:2]
        frame_bounds=Rect(origin[0],origin[1],width,height)
        report=ScreenReport(frame={'source':'image','coordinate_space':'desktop_physical_pixels',
            'bounds':frame_bounds.to_dict(),'width':width,'height':height,
            'origin':{'x':origin[0],'y':origin[1]},'environment':environment,
            'knowledge_library_count':len(self.knowledge.libraries) if hasattr(self.knowledge,'libraries') else None})
        thumbnail=cv2.resize(image,(16,16),interpolation=cv2.INTER_AREA)
        report.frame['ocr_max_side']=ocr_max_side if use_ocr else None
        report.frame['template_scales']=list(template_scales) if template_scales is not None else (list(self.knowledge.scales) if hasattr(self.knowledge,'scales') else None)
        report.frame['template_names']=list(template_names) if template_names is not None else None
        if region is not None: report.frame['requested_region']=rectangle(region).to_dict()
        report.frame['visual_signature']=hashlib.sha256((thumbnail//16).tobytes()).hexdigest()[:16]
        report.windows=[{**w,'intersects_frame':bool(Rect.from_bbox(w['bounds']['bbox']).intersection(frame_bounds).area)}
            for w in windows]
        report.capabilities={'windows':'provided' if windows else 'not_requested',
            'uia':'disabled' if not use_uia else 'not_requested',
            'ocr':'disabled' if not use_ocr else 'pending',
            'cv_buttons':'disabled' if not use_cv else 'pending',
            'knowledge':'pending' if use_knowledge else 'disabled'}
        def stage(name,operation):
            start=time.perf_counter()
            try:
                result=operation()
                report.capabilities[name]='ok'
                return result
            except Exception as error:
                report.capabilities[name]='failed'
                report.warnings.append(f'{name}: {type(error).__name__}: {error}')
                return None
            finally: report.timings_ms[name]=round((time.perf_counter()-start)*1000,2)
        def match_templates():
            options={}
            if environment=='hololive_dreams' and template_names and any(n.startswith('claim_') for n in template_names):
                from modular_agent.domains.hololive_dreams.claim_search import match_claims
                matches,search=match_claims(self.knowledge,image,environment,origin,
                    report.frame.get('world_features',{}),template_names,template_scales,template_threshold)
                report.frame['claim_search']=search
                return matches
            if environment=='hololive_dreams' and template_names and any(n.startswith('entry_') for n in template_names):
                from modular_agent.domains.hololive_dreams.entry_search import match_entry
                matches,search=match_entry(self.knowledge,image,environment,origin,
                    report.frame.get('world_features',{}),template_names,template_scales,template_threshold)
                report.frame['entry_search']=search
                return matches
            if template_names is not None: options['template_names']=template_names
            if template_scales is not None: options['scales']=template_scales
            if template_threshold is not None: options['threshold']=template_threshold
            matches=self.knowledge.match(image,environment,origin,**options)
            return matches
        if environment=='hololive_dreams':
            from modular_agent.domains.hololive_dreams.visual_features import extract
            from pathlib import Path
            game_features=stage('world_features',lambda:extract(image,origin,Path(__file__).resolve().parents[3]))
            report.frame['world_features']=game_features or {}
        if prefer_templates and use_knowledge:
            report.knowledge_matches=stage('knowledge',match_templates) or []
            if any(m['label'] not in template_priority_exclude for m in report.knowledge_matches):
                use_ocr=False
                report.capabilities['ocr']='skipped_template_match'
                report.frame['ocr_skipped_for_templates']=True
        if use_uia and read_controls:
            handles=[window_handle] if window_handle is not None else [w['handle'] for w in windows if w.get('foreground') and not w.get('minimized')]
            if handles:
                controls=stage('uia',lambda:self.desktop.controls(handles))
                if controls:
                    report.buttons.extend(controls['buttons'])
                    report.texts.extend(controls['texts'])
                    report.warnings.extend(controls.get('warnings',[]))
                    if controls.get('warnings'): report.capabilities['uia']='partial'
            else: report.capabilities['uia']='no_target_window'
        if use_ocr:
            texts=stage('ocr',lambda:self.ocr.recognize(image,origin,**({'max_side':ocr_max_side} if ocr_max_side is not None else {})))
            if texts: report.texts.extend(texts)
        if use_cv:
            candidates=stage('cv_buttons',lambda:self.detector.detect(image,origin)) or []
            for candidate in candidates:
                bounds=Rect.from_bbox(candidate['bounds']['bbox'])
                if not any(bounds.iou(Rect.from_bbox(b['bounds']['bbox']))>.6 for b in report.buttons):
                    report.buttons.append(candidate)
        if not prefer_templates and use_knowledge:
            report.knowledge_matches=stage('knowledge',match_templates) or []
        for match in report.knowledge_matches:
            if match['role']=='button':
                bounds=Rect.from_bbox(match['bounds']['bbox'])
                overlap=next((b for b in report.buttons if bounds.iou(Rect.from_bbox(b['bounds']['bbox']))>.6),None)
                if overlap is not None:
                    overlap.setdefault('knowledge_match_ids',[]).append(match['id'])
                    # Human-curated template provides a stronger semantic signal than shape alone.
                    if overlap['source']=='cv_shape':
                        overlap.update(label=match['label'],source='template',confidence=match['similarity'],semantic_confirmed=True)
                else:
                    report.buttons.append({'id':match['id']+':button','label':match['label'],
                        'bounds':match['bounds'],'confidence':match['similarity'],'source':'template',
                        'semantic_confirmed':True,'enabled':None,'text_ids':[],
                        'knowledge_match_ids':[match['id']]})
        # UIA can expose offscreen descendants. Keep intersecting elements and report full bounds.
        for key in ('buttons','texts'):
            items=getattr(report,key)
            setattr(report,key,[i for i in items if Rect.from_bbox(i['bounds']['bbox']).intersection(frame_bounds).area])
        # OCR has actual glyph geometry; UIA labels may cover the entire control.
        # Merge equal overlapping labels, retaining UIA associations and OCR bounds.
        uia_texts=[t for t in report.texts if t['source']=='uia']
        removed=set()
        for text in report.texts:
            if text['source']!='ocr': continue
            bounds=Rect.from_bbox(text['bounds']['bbox'])
            for native in uia_texts:
                native_bounds=Rect.from_bbox(native['bounds']['bbox'])
                same=''.join(text['text'].split())==''.join(native['text'].split())
                overlap=bounds.intersection(native_bounds).area/max(1,min(bounds.area,native_bounds.area))
                if same and overlap>=.7:
                    text['button_ids']=list(dict.fromkeys(text['button_ids']+native['button_ids']))
                    text.setdefault('additional_sources',[]).append('uia')
                    removed.add(native['id'])
        report.texts=[t for t in report.texts if t['id'] not in removed]
        for text in report.texts:
            bounds=Rect.from_bbox(text['bounds']['bbox'])
            containing=[b for b in report.buttons if bounds.area and bounds.intersection(Rect.from_bbox(b['bounds']['bbox'])).area/bounds.area>=.7]
            if containing:
                button=min(containing,key=lambda b:Rect.from_bbox(b['bounds']['bbox']).area)
                if button['id'] not in text['button_ids']: text['button_ids'].append(button['id'])
            for button in report.buttons:
                if button['id'] in text['button_ids'] and text['id'] not in button['text_ids']:
                    button['text_ids'].append(text['id'])
                    if not button['label']: button['label']=text['text']
        if environment=='hololive_dreams' and use_ocr and use_cv:
            from modular_agent.domains.hololive_dreams.popup_recovery import annotate
            annotate(report,image,origin)
        return report
