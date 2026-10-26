"""PE32/PE32+ ordinary and delay-import closure for portable Windows Python."""
from pathlib import Path
import struct,shutil,json

def imports(path):
    data=Path(path).read_bytes()
    if data[:2]!=b'MZ':raise ValueError('Not a PE: '+str(path))
    pe=struct.unpack_from('<I',data,0x3c)[0]
    count=struct.unpack_from('<H',data,pe+6)[0];size=struct.unpack_from('<H',data,pe+20)[0];opt=pe+24
    magic=struct.unpack_from('<H',data,opt)[0];directory=opt+(112 if magic==0x20b else 96)
    base=struct.unpack_from('<Q' if magic==0x20b else '<I',data,opt+(24 if magic==0x20b else 28))[0]
    sections=[struct.unpack_from('<IIII',data,opt+size+i*40+8) for i in range(count)]
    def offset(rva):
        for vs,va,rs,raw in sections:
            if va<=rva<va+max(vs,rs):return raw+rva-va
        raise ValueError('Invalid PE RVA: '+str(path))
    def name(rva):
        at=offset(rva);return data[at:data.index(b'\0',at)].decode('ascii')
    names=[]
    for index,step in [(1,20),(13,32)]:
        rva,length=struct.unpack_from('<II',data,directory+index*8)
        if not rva:continue
        at=offset(rva)
        while any(data[at:at+step]):
            if index==1:names.append(name(struct.unpack_from('<I',data,at+12)[0]))
            else:
                flags,n=struct.unpack_from('<II',data,at);names.append(name(n if flags&1 else n-base))
            at+=step
    return sorted(set(names),key=str.lower)

def collect(runtime,python_root):
    runtime=Path(runtime);python_root=Path(python_root)
    search={p.name.lower():p for folder in [python_root/'Library/bin',python_root/'DLLs',python_root] for p in folder.glob('*.dll')}
    packaged={p.name.lower():p for p in runtime.rglob('*.dll')}
    pending=[p for p in runtime.rglob('*') if p.suffix.lower() in ('.exe','.dll','.pyd')];seen=set();edges=[];missing=[]
    system=Path(__import__('os').environ['SystemRoot'])/'System32'
    while pending:
        path=pending.pop()
        if path in seen:continue
        seen.add(path)
        for name in imports(path):
            key=name.lower();kind='package'
            dep=search.get(key)
            if dep:
                # Application directory resolves dependencies before any Python bootstrap.
                target=runtime/dep.name
                if not target.exists():shutil.copy2(dep,target)
                packaged[key]=target;pending.append(target)
            elif key in packaged:pass
            elif key.startswith(('api-ms-','ext-ms-')):kind='windows-api-set'
            elif (system/name).is_file() and not key.startswith(('vcruntime','msvcp','concrt','lib','ffi','python')):kind='windows-system'
            else:kind='missing';missing.append((str(path.relative_to(runtime)),name))
            edges.append({'file':str(path.relative_to(runtime)),'dependency':name,'resolution':kind})
    report={'scanned':len(seen),'edges':edges,'missing':missing}
    (runtime.parent/'native-dependencies.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    if missing:raise RuntimeError('Unresolved native dependencies: '+str(missing))
    return report
