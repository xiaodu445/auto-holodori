"""Bounded Markdown knowledge access; model notes carry explicit provenance."""
from datetime import datetime, UTC
from pathlib import Path
import re
import hashlib

class AgentKnowledge:
    def __init__(self,root,domain=None):
        self.root=Path(root).resolve()
        if domain and not re.fullmatch(r'[a-z][a-z0-9_-]*',domain): raise ValueError('Invalid domain')
        self.domain=domain
    def _roots(self,scope):
        if scope not in ('auto','global','domain','memory','history'): raise ValueError('Invalid knowledge scope')
        global_root=self.root/'knowledge'
        domain_root=self.root/'domains'/self.domain/'knowledge' if self.domain else None
        roots={'global':[global_root],'domain':[domain_root] if domain_root else [],
            'memory':[self.root/'runtime'/'memory'],
            'history':[self.root/'runtime'/'memory'/'task_sessions'],
            'auto':[global_root]+([domain_root] if domain_root else [])+[self.root/'runtime'/'memory']}[scope]
        return roots

    def _files(self,scope,directory=None):
        roots=self._roots(scope)
        if directory is not None:
            if not isinstance(directory,str) or not directory or '..' in Path(directory).parts or Path(directory).is_absolute(): raise ValueError('directory must be a project-relative knowledge path')
            chosen=(self.root/directory).resolve()
            if not chosen.is_relative_to(self.root) or not any(chosen.is_relative_to(r.resolve()) for r in roots): raise ValueError('Directory outside selected knowledge scope')
            roots=[chosen]
        seen=set()
        for root in roots:
            for path in sorted(root.rglob('*.md')):
                resolved=path.resolve()
                if not resolved.is_relative_to(self.root) or resolved in seen: continue
                if scope!='history' and 'task_sessions' in path.relative_to(self.root).parts: continue
                if not any(resolved.is_relative_to(r.resolve()) for r in roots): continue
                seen.add(resolved)
                yield path

    def index(self,*,scope='auto',directory=None,limit=20,offset=0):
        if type(limit) is not int or not 1<=limit<=40 or type(offset) is not int or offset<0: raise ValueError('Invalid index pagination')
        paths=list(self._files(scope,directory));entries=[]
        for path in paths[offset:offset+limit]:
            with path.open(encoding='utf-8-sig') as stream: header=stream.read(400)
            title=next((line.lstrip('# ').strip() for line in header.splitlines() if line.startswith('#')) ,path.stem)
            entries.append({'path':str(path.relative_to(self.root)),'title':title[:120],'size_bytes':path.stat().st_size})
        return {'scope':scope,'directory':directory,'directories':sorted({str(p.parent.relative_to(self.root)) for p in paths[offset:offset+limit]}),'total_files':len(paths),
            'entries':entries,'next_offset':offset+limit if offset+limit<len(paths) else None}

    def read_document(self,path,*,scope='auto',offset=0,limit=2500):
        if not isinstance(path,str) or not path or Path(path).is_absolute() or '..' in Path(path).parts: raise ValueError('path must be project relative')
        if type(offset) is not int or offset<0 or type(limit) is not int or not 1<=limit<=6000: raise ValueError('Invalid document pagination')
        target=(self.root/path).resolve()
        if not target.is_relative_to(self.root) or not any(target.is_relative_to(r.resolve()) for r in self._roots(scope)) or target.suffix!='.md': raise ValueError('Document outside knowledge scope')
        if scope!='history' and 'task_sessions' in target.relative_to(self.root).parts: raise ValueError('Task sessions require explicit history scope')
        with target.open(encoding='utf-8-sig') as stream:
            # Seek by characters so Chinese pagination is independent of UTF-8 byte length.
            remaining=offset
            while remaining:
                chunk=stream.read(min(remaining,8192))
                if not chunk: break
                remaining-=len(chunk)
            content=stream.read(limit)
            more=bool(stream.read(1))
        return {'path':str(target.relative_to(self.root)),'content':content,'offset':offset,'next_offset':offset+len(content) if more else None,
            'verification':'model_reported' if 'agent_notes' in target.parts else ('session_record' if scope=='history' else 'see_document')}

    def search(self,query,limit=5,*,scope='auto',directory=None,max_chars=10000,entry_chars=2500):
        if not isinstance(query,str) or not 1<=len(query)<=2000: raise ValueError('Query must contain 1..2000 characters')
        if type(limit) is not int or not 1<=limit<=10: raise ValueError('limit must be 1..10')
        if type(max_chars) is not int or not 500<=max_chars<=20000 or type(entry_chars) is not int or not 300<=entry_chars<=6000: raise ValueError('Invalid knowledge text budget')
        terms=set(re.findall(r'\w+',query.lower()))
        chinese=re.findall(r'[\u4e00-\u9fff]+',query)
        grams=set(g[i:i+size] for g in chinese for size in (2,3,4) for i in range(max(0,len(g)-size+1)))
        grams=sorted(grams,key=lambda v:(-len(v),v))[:100]
        ranked=[]
        for path in self._files(scope,directory):
            with path.open(encoding='utf-8-sig') as stream: text=stream.read(12000)
            lower=text.lower();name=str(path.relative_to(self.root)).lower()
            title=text.split('\n',1)[0].lower()
            score=sum(4*(term in lower or term in name)+2*(term in title) for term in terms)
            score+=sum(.25*(term in lower)+.5*(term in title) for term in grams)
            if score: ranked.append((score,str(path.relative_to(self.root)),text))
        ranked.sort(key=lambda item:(-item[0],item[1]))
        entries=[];remaining=max_chars
        for score,path,text in ranked[:limit]:
            if remaining<=0: break
            content=text[:min(entry_chars,remaining)]
            remaining-=len(content)
            entries.append({'path':path,'content':content,'keyword_score':score,
                'truncated':len(content)<len(text),'verification':'model_reported' if 'agent_notes' in path else 'see_document'})
        return entries

    def write(self,summary,evidence,source="顶层模型总结"):
        if not isinstance(summary,str) or not 1<=len(summary)<=4000: raise ValueError('summary must contain 1..4000 characters')
        if not isinstance(evidence,str) or not 1<=len(evidence)<=4000: raise ValueError('evidence must contain 1..4000 characters')
        directory=(self.root/'domains'/self.domain/'knowledge' if self.domain else self.root/'knowledge'/'global')/'agent_notes'
        if not directory.resolve().is_relative_to(self.root): raise ValueError('Knowledge directory escapes project')
        directory.mkdir(parents=True,exist_ok=True)
        identifier=hashlib.sha256((summary+'\n'+evidence).encode('utf-8')).hexdigest()[:24]
        path=directory/(identifier+'.md')
        if path.exists(): return {'path':str(path.relative_to(self.root)),'verification':'model_reported','deduplicated':True}
        path.write_text('# Agent 经验记录\n\n'
            f'- 来源：{source}\n- 验证状态：model_reported（未经独立规则验证）\n'
            f'- 时间：{datetime.now(UTC).isoformat()}\n\n## 经验\n\n{summary}\n\n## 依据\n\n{evidence}\n',encoding='utf-8')
        return {'path':str(path.relative_to(self.root)),'verification':'model_reported'}
