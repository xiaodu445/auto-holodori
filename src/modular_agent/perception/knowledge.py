"""Multi-instance, multi-scale local matching of curated visual knowledge."""
from pathlib import Path
import cv2
import numpy as np
from .report import Rect

class KnowledgeMatcher:
    def __init__(self,libraries=(),scales=(1.0,),max_per_template=10):
        if not scales or any(not np.isfinite(s) or not .25<=s<=4 for s in scales):
            raise ValueError('Template scales must be between .25 and 4')
        if not 1<=max_per_template<=100: raise ValueError('Invalid match limit')
        self.libraries=list(libraries)
        self.scales=tuple(scales)
        self.max_per_template=max_per_template
        self._registries={}
        self._images={}
        self._patches={}

    def _records(self,library):
        stat=library.registry_path.stat()
        key=(stat.st_mtime_ns,stat.st_size)
        cached=self._registries.get(str(library.registry_path))
        if cached is None or cached[0]!=key:
            cached=(key,library.records())
            self._registries[str(library.registry_path)]=cached
        return cached[1]

    def _template(self,library,record):
        path=library.root/record.image_file
        stat=path.stat()
        key=(str(path),stat.st_mtime_ns,stat.st_size,record.mask_mode)
        if key not in self._images:
            if len(self._images)>=256:
                self._images.clear(); self._patches.clear()
            data=cv2.imdecode(np.fromfile(str(path),dtype=np.uint8),cv2.IMREAD_UNCHANGED)
            if data is None: raise ValueError(f'Unreadable template: {record.name}')
            mask=None
            if data.ndim==3:
                if data.shape[2]==4:
                    mask=(data[:,:,3]>0).astype(np.uint8)*255
                    data=data[:,:,:3]
                if record.mask_mode=='warm_ui':
                    hsv=cv2.cvtColor(data,cv2.COLOR_BGR2HSV)
                    warm=(hsv[:,:,0]<=40)&(hsv[:,:,1]>=80)&(hsv[:,:,2]>=180)
                    white=(hsv[:,:,1]<=60)&(hsv[:,:,2]>=205)
                    foreground=(warm|white).astype(np.uint8)*255
                    mask=foreground if mask is None else cv2.bitwise_and(mask,foreground)
                data=cv2.cvtColor(data,cv2.COLOR_BGR2GRAY)
            if mask is not None and np.count_nonzero(mask)<16: raise ValueError(f'Insufficient template foreground: {record.name}')
            self._images[key]=(data,mask)
        data,mask=self._images[key]
        return key,data

    def _patch(self,key,template,scale):
        patch_key=(key,scale)
        if patch_key not in self._patches:
            if len(self._patches)>=1024: self._patches.clear()
            w,h=max(1,round(template.shape[1]*scale)),max(1,round(template.shape[0]*scale))
            patch=cv2.resize(template,(w,h)) if scale!=1 else template
            mask=self._images[key][1]
            if mask is not None and scale!=1: mask=cv2.resize(mask,(w,h),interpolation=cv2.INTER_NEAREST)
            self._patches[patch_key]=(patch,patch.std()<1e-6,mask)
        return self._patches[patch_key]

    def warmup(self):
        for library in self.libraries:
            if not library.registry_path.exists(): continue
            for record in self._records(library):
                key,template=self._template(library,record)
                for scale in self.scales: self._patch(key,template,scale)

    def match(self,image,environment='default',origin=(0,0),*,template_names=None,scales=None,threshold=None):
        from .options import names,scales as validate_scales,validate
        selected=names(template_names)
        request_scales=validate_scales(scales) or self.scales
        validate(template_threshold=threshold)
        if selected==(): return []
        gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY) if image.ndim==3 else image
        all_matches=[]
        self.last_diagnostics=[]
        for library in self.libraries:
            # Do not create an empty registry while observing.
            if not library.registry_path.exists(): continue
            for record in self._records(library):
                if '*' not in record.environments and environment not in record.environments: continue
                if selected is not None and record.name not in selected: continue
                effective_threshold=record.threshold if threshold is None else threshold
                cache_key,template=self._template(library,record)
                candidates=[]
                best_score=-1
                best_scale=None
                for scale in request_scales:
                    w,h=max(1,round(template.shape[1]*scale)),max(1,round(template.shape[0]*scale))
                    if w>gray.shape[1] or h>gray.shape[0]: continue
                    patch,constant,mask=self._patch(cache_key,template,scale)
                    if mask is not None:
                        scores=cv2.matchTemplate(gray,patch,cv2.TM_CCOEFF_NORMED,mask=mask)
                    elif constant:
                        scores=1-cv2.matchTemplate(gray,patch,cv2.TM_SQDIFF)/(255.0**2*w*h)
                    else:
                        scores=cv2.matchTemplate(gray,patch,cv2.TM_CCOEFF_NORMED)
                    scores=np.nan_to_num(scores,nan=-1,posinf=-1,neginf=-1)
                    _,peak,_,_=cv2.minMaxLoc(scores)
                    if peak>best_score: best_score=float(peak);best_scale=scale
                    for _ in range(self.max_per_template):
                        _,similarity,_,point=cv2.minMaxLoc(scores)
                        if similarity<effective_threshold: break
                        x,y=point
                        candidates.append((float(similarity),Rect(x+origin[0],y+origin[1],w,h),scale))
                        # Suppress nearby peaks for this template, preserving distinct instances.
                        scores[max(0,y-h//2):min(scores.shape[0],y+h//2+1),
                               max(0,x-w//2):min(scores.shape[1],x+w//2+1)]=-1
                self.last_diagnostics.append({'name':record.name,'score':round(best_score,4),'scale':best_scale,'threshold':effective_threshold})
                kept=[]
                for score,bounds,scale in sorted(candidates,key=lambda x:x[0],reverse=True):
                    if any(bounds.iou(b)>.4 for _,b,_ in kept): continue
                    kept.append((score,bounds,scale))
                    if len(kept)>=self.max_per_template: break
                for i,(score,bounds,scale) in enumerate(kept):
                    all_matches.append({'id':f'template:{record.id}:{i}',
                        'template_id':record.id,'label':record.name,
                        'bounds':bounds.to_dict(),'similarity':round(max(0,min(1,score)),4),
                        'threshold':effective_threshold,'scale':scale,'source':'template',
                        'role':record.role,'library':str(library.root.resolve()),
                        'knowledge_file':record.knowledge_file,'notes':record.notes,
                        'human_reliability':record.reliability,'environment':environment})
        return sorted(all_matches,key=lambda m:m['similarity'],reverse=True)
