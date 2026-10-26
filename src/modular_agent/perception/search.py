"""Read-only targeted queries and bounded polling; no stale-frame reuse."""
import math
import time
import unicodedata
from .options import names


def queries(value):
    if isinstance(value,str): value=[value]
    if not isinstance(value,(list,tuple)) or not 1<=len(value)<=100 or any(not isinstance(v,str) or not v.strip() or len(v)>256 for v in value):
        raise ValueError('queries must contain 1..100 nonempty strings')
    return list(dict.fromkeys(value))


def normalized(value):
    return ''.join(unicodedata.normalize('NFKC',value).split()).casefold()

class SearchMixin:
    def find_text(self,query,*,mode='contains',min_confidence=0,**options):
        wanted=queries(query)
        if mode not in ('exact','contains'): raise ValueError('mode must be exact or contains')
        if type(min_confidence) not in (int,float) or not math.isfinite(min_confidence) or not 0<=min_confidence<=1: raise ValueError('Invalid text confidence')
        options.update(enable_ocr=True,enable_uia=False,enable_cv_buttons=False,enable_knowledge=False,prefer_templates=False)
        report=self.observe(**options)
        matches=[]
        for text in report.texts:
            if text.get('confidence',0)<min_confidence: continue
            found=[q for q in wanted if (normalized(q)==normalized(text['text']) if mode=='exact' else normalized(q) in normalized(text['text']))]
            if found: matches.append({**text,'queries':found})
        return {'found':bool(matches),'matches':matches,'frame':report.frame,'observed_at':report.observed_at,'capabilities':report.capabilities,'warnings':report.warnings,'timings_ms':report.timings_ms}

    def find_templates(self,template_names,**options):
        wanted=names(template_names)
        if wanted is None or not wanted: raise ValueError('Specify at least one template name')
        options.update(template_names=wanted,enable_ocr=False,enable_uia=False,enable_cv_buttons=False,enable_knowledge=True,prefer_templates=False)
        report=self.observe(**options)
        return {'found':bool(report.knowledge_matches),'matches':report.knowledge_matches,'frame':report.frame,'observed_at':report.observed_at,'capabilities':report.capabilities,'warnings':report.warnings,'timings_ms':report.timings_ms}

    def wait_for(self,kind,query,*,timeout=30,interval=.5,stable_count=1,require_all=False,cancelled=lambda:False,clock=time.monotonic,sleep=time.sleep,**options):
        wanted=queries(query)
        if kind not in ('text','template'): raise ValueError('kind must be text or template')
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in (timeout,interval)) or not 0<=timeout<=300 or not .1<=interval<=30: raise ValueError('timeout must be 0..300, interval .1..30')
        if type(stable_count) is not int or not 1<=stable_count<=10 or type(require_all) is not bool: raise ValueError('Invalid polling conditions')
        if not callable(cancelled): raise ValueError('cancelled must be callable')
        start=clock();last=None;previous=None;stable=0;attempts=0
        while True:
            if cancelled(): return {'status':'cancelled','found':False,'attempts':attempts,'last_result':last}
            if attempts and clock()-start>=timeout: return {'status':'timeout','found':False,'attempts':attempts,'last_result':last}
            last=self.find_text(wanted,**options) if kind=='text' else self.find_templates(wanted,**options)
            attempts+=1
            if cancelled(): return {'status':'cancelled','found':False,'attempts':attempts,'last_result':last}
            seen=set(q for m in last['matches'] for q in (m.get('queries',[]) if kind=='text' else [m.get('label')]))
            eligible=bool(seen) and (not require_all or set(wanted)<=seen)
            signature=tuple(sorted((m.get('text',m.get('label','')),tuple(round(m['bounds'].get(k,0)/8) for k in ('x','y','width','height'))) for m in last['matches']))
            stable=(stable+1 if signature==previous else 1) if eligible else 0
            previous=signature if eligible else None
            if stable>=stable_count: return {'status':'matched','found':True,'attempts':attempts,'last_result':last}
            remaining=timeout-(clock()-start)
            if remaining<=0: return {'status':'timeout','found':False,'attempts':attempts,'last_result':last}
            # Small slices keep cancellation responsive between recognition calls.
            stop_at=clock()+min(interval,remaining)
            while clock()<stop_at:
                if cancelled(): return {'status':'cancelled','found':False,'attempts':attempts,'last_result':last}
                sleep(min(.1,stop_at-clock()))
