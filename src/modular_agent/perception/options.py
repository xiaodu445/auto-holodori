"""Validated, per-request perception options and desktop-coordinate cropping."""
import math
from functools import wraps
from .report import Rect

def serialized(method):
    @wraps(method)
    def call(self,*args,**kwargs):
        with self._request_lock:
            if self._closed and method.__name__!='close': raise RuntimeError('Vision instance is closed')
            return method(self,*args,**kwargs)
    return call

def names(value):
    if value is None: return None
    if isinstance(value,str) or not isinstance(value,(list,tuple)) or len(value)>100:
        raise ValueError('template_names must be a list/tuple of at most 100 names')
    if any(not isinstance(v,str) or not v.strip() or len(v)>128 for v in value): raise ValueError('Invalid template name')
    return tuple(dict.fromkeys(value))

def scales(value):
    if value is None: return None
    if isinstance(value,(str,bytes)) or not isinstance(value,(list,tuple)) or not 1<=len(value)<=16:
        raise ValueError('template_scales must contain 1..16 values')
    if any(type(v) not in (int,float) or not math.isfinite(v) or not .25<=v<=4 for v in value): raise ValueError('Invalid template scale')
    return tuple(dict.fromkeys(value))

def validate(*,enable_ocr=None,enable_uia=None,enable_cv_buttons=None,enable_knowledge=None,ocr_max_side=None,template_names=None,template_scales=None,template_threshold=None,region=None):
    for v in (enable_ocr,enable_uia,enable_cv_buttons,enable_knowledge):
        if v is not None and type(v) is not bool: raise ValueError('Module flags must be bool or None')
    if ocr_max_side is not None and (type(ocr_max_side) is not int or not 64<=ocr_max_side<=8192): raise ValueError('ocr_max_side must be 64..8192')
    names(template_names);scales(template_scales)
    if template_threshold is not None and (type(template_threshold) not in (int,float) or not math.isfinite(template_threshold) or not 0<template_threshold<=1): raise ValueError('template_threshold must be finite and in (0,1]')
    rectangle(region)

def rectangle(region):
    if region is None: return None
    if isinstance(region,Rect): result=region
    elif isinstance(region,dict) and set(region)=={'x','y','width','height'}: result=Rect(**region)
    elif isinstance(region,(list,tuple)) and len(region)==4: result=Rect(*region)
    else: raise ValueError('region requires x,y,width,height in desktop physical pixels')
    if any(type(v) is not int for v in (result.x,result.y,result.width,result.height)) or result.width<=0 or result.height<=0:
        raise ValueError('region must use integers and positive dimensions')
    return result

def crop(image,origin,region):
    requested=rectangle(region)
    if requested is None: return image,origin
    bounds=requested.intersection(Rect(origin[0],origin[1],image.shape[1],image.shape[0]))
    if not bounds.area: raise ValueError('Search region does not intersect captured image')
    x,y=bounds.x-origin[0],bounds.y-origin[1]
    return image[y:y+bounds.height,x:x+bounds.width].copy(),(bounds.x,bounds.y)
