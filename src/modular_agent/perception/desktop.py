"""Read-only native window bounds and timeout-isolated UI Automation queries."""
import ctypes
from ctypes import wintypes
from .report import Rect

class DesktopReader:
    def __init__(self):
        from .uia_process import UIAProcess
        self.uia=UIAProcess()

    def warmup(self):
        self.uia.request([],timeout=10)

    def close(self):
        self.uia.close()

    def windows(self):
        from modular_agent.computer.windows import WindowsBackend
        backend=WindowsBackend()
        api=backend.api
        api.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
        api.IsIconic.argtypes=[wintypes.HWND]
        api.GetClassNameW.argtypes=[wintypes.HWND,wintypes.LPWSTR,ctypes.c_int]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD]
        kernel.OpenProcess.restype=wintypes.HANDLE
        kernel.QueryFullProcessImageNameW.argtypes=[wintypes.HANDLE,wintypes.DWORD,wintypes.LPWSTR,ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes=[wintypes.HANDLE]
        result=[]
        for z_order,window in enumerate(backend.windows()):
            window['z_order']=z_order
            native=wintypes.RECT()
            if api.GetWindowRect(window['handle'],ctypes.byref(native)):
                window['bounds']=Rect.from_bbox((native.left,native.top,native.right,native.bottom)).to_dict()
                window['minimized']=bool(api.IsIconic(window['handle']))
                window['source']='win32'
                class_name=ctypes.create_unicode_buffer(256)
                api.GetClassNameW(window['handle'],class_name,len(class_name))
                window['class_name']=class_name.value
                window['process_name']=None
                process=kernel.OpenProcess(0x1000,False,window['pid'])
                if process:
                    try:
                        executable=ctypes.create_unicode_buffer(32768)
                        size=wintypes.DWORD(len(executable))
                        if kernel.QueryFullProcessImageNameW(process,0,executable,ctypes.byref(size)):
                            window['process_name']=executable.value.rsplit(chr(92),1)[-1]
                    finally: kernel.CloseHandle(process)
                result.append(window)
        return result

    def controls(self,handles,timeout=4):
        if not handles: return {'buttons':[],'texts':[],'warnings':[]}
        return self.uia.request(handles,timeout)
