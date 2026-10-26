"""Local Chinese/English OCR, with injectable engine for domain-specific models."""
from __future__ import annotations
import math
import threading
import hashlib
from copy import deepcopy
import numpy as np
from .report import Rect

class LocalOCR:
    def __init__(self, engine=None, min_confidence=.5, max_side=1600):
        if not 0 <= min_confidence <= 1: raise ValueError('Invalid OCR threshold')
        if max_side < 64: raise ValueError('max_side must be at least 64')
        self.lock=threading.RLock()
        self.engine=engine
        self._native_engine=False
        self._cached_key=None
        self._cached_result=None
        self.min_confidence=min_confidence
        self.max_side=max_side

    def warmup(self):
        with self.lock:
            if self.engine is None:
                from rapidocr_onnxruntime import RapidOCR
                self.engine=RapidOCR(intra_op_num_threads=2, inter_op_num_threads=1,det_limit_type='max')
                self._native_engine=True
            self.engine(np.zeros((64,64,3),dtype=np.uint8),**({'use_cls':False} if self._native_engine else {}))

    def recognize(self, image, origin=(0,0),max_side=None):
        with self.lock:
            if self.engine is None: self.warmup()
            return self._recognize(image,origin,self.max_side if max_side is None else max_side)

    def _recognize(self,image,origin,max_side):
        import cv2
        if type(max_side) is not int or max_side<64: raise ValueError('max_side must be at least 64')
        scale=min(1,max_side/max(image.shape[:2]))
        working=cv2.resize(image,None,fx=scale,fy=scale) if scale<1 else image
        cache_key=(image.shape,tuple(origin),max_side,self.min_confidence,hashlib.blake2b(working.tobytes(),digest_size=16).digest())
        if cache_key==self._cached_key: return deepcopy(self._cached_result)
        # Native detector must not upscale a downsampled screenshot again.
        # Game HUD text is normally upright; full mode retains angle classification.
        rows,_=self.engine(working,**({'use_cls':max_side>=1600} if self._native_engine else {}))
        result=[]
        for polygon,text,confidence in (rows or []):
            score=float(confidence)
            if not text or not math.isfinite(score) or score < self.min_confidence: continue
            points=np.asarray(polygon,dtype=float)
            # Use actual resize dimensions; integer rounding can differ between axes.
            points[:,0]*=image.shape[1]/working.shape[1]
            points[:,1]*=image.shape[0]/working.shape[0]
            points[:,0]+=origin[0]; points[:,1]+=origin[1]
            bounds=Rect.from_bbox((math.floor(points[:,0].min()),math.floor(points[:,1].min()),math.ceil(points[:,0].max()),math.ceil(points[:,1].max())))
            result.append({'id':f'ocr:{len(result)}','text':str(text),'confidence':round(score,4),
                'bounds':bounds.to_dict(),'polygon':points.round(2).tolist(),
                'source':'ocr','geometry_kind':'text_polygon','button_ids':[]})
        self._cached_key=cache_key
        self._cached_result=deepcopy(result)
        return result
