"""Run with bundled python.exe/pythonw.exe -I, clean PATH and neutral CWD."""
import sys,os,json,importlib
from pathlib import Path
runtime=Path(sys.executable).resolve().parent
modules=sorted(p.stem for p in (runtime/'DLLs').glob('*.pyd') if not p.stem.startswith(('_test','xxlimited')))
for name in ['ctypes',*modules]:importlib.import_module(name)
import ctypes as c
from ctypes import wintypes as w
kernel=c.WinDLL('kernel32',use_last_error=True);psapi=c.WinDLL('psapi',use_last_error=True)
kernel.GetCurrentProcess.restype=w.HANDLE
psapi.EnumProcessModules.argtypes=[w.HANDLE,c.POINTER(w.HMODULE),w.DWORD,c.POINTER(w.DWORD)]
psapi.GetModuleFileNameExW.argtypes=[w.HANDLE,w.HMODULE,w.LPWSTR,w.DWORD]
array=(w.HMODULE*4096)();needed=w.DWORD();process=kernel.GetCurrentProcess()
if not psapi.EnumProcessModules(process,array,c.sizeof(array),c.byref(needed)):raise c.WinError()
loaded=[];external=[];windows=Path(os.environ['SystemRoot']).resolve()
for handle in array[:needed.value//c.sizeof(w.HMODULE)]:
    value=c.create_unicode_buffer(32768)
    if not psapi.GetModuleFileNameExW(process,handle,value,len(value)):raise c.WinError()
    path=Path(value.value).resolve();loaded.append(str(path))
    if not (path.is_relative_to(runtime) or path.is_relative_to(windows)):external.append(str(path))
if external:raise RuntimeError('External runtime dependency: '+str(external))
for entry in sys.path:
    if entry and not Path(entry).resolve().is_relative_to(runtime.parent):raise RuntimeError('External sys.path: '+entry)
report={'native_extensions':modules,'ctypes':'ok','executable':sys.executable,'isolated':sys.flags.isolated,'loaded_modules':loaded,'external_modules':external,'sys_path':sys.path}
text=json.dumps(report,ensure_ascii=False)
(runtime.parent/('native-probe-'+Path(sys.executable).stem+'.json')).write_text(text,encoding='utf-8')
print(text,flush=True)
