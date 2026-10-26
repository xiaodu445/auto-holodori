"""Physical Space observation and actual-input metering for route learning."""
from collections import deque
import threading
import time
from modular_agent.core import Outcome


class ManualSpaceBuffer:
    def __init__(self):self.events=deque(maxlen=64);self.down=False;self.lock=threading.Lock()

    def feed(self,vk,message,flags,foreground,t):
        if vk!=32 or flags&0x10:return  # LLKHF_INJECTED: never learn our own input.
        with self.lock:
            if message==0x101:self.down=False
            elif message==0x100:
                if foreground and not self.down:self.events.append(t)
                self.down=True

    def take_before(self,t):
        with self.lock:
            result=[]
            while self.events and self.events[0]<=t:result.append(self.events.popleft())
            return result


class ManualSpaceMonitor(ManualSpaceBuffer):
    def __init__(self,handle):
        super().__init__();self.handle=handle;self.done=threading.Event();self.ready=threading.Event();self.error=None
        self.thread=threading.Thread(target=self._run,daemon=True);self.thread.start()
        if not self.ready.wait(1) or self.error:
            self.close();raise OSError(self.error or 'Space hook startup timeout')

    def _run(self):
        import ctypes as C
        from ctypes import wintypes as W
        api=C.WinDLL('user32',use_last_error=True);kernel=C.WinDLL('kernel32',use_last_error=True)
        class Key(C.Structure):
            _fields_=[('vkCode',W.DWORD),('scanCode',W.DWORD),('flags',W.DWORD),('time',W.DWORD),('extra',C.c_size_t)]
        callback_type=C.WINFUNCTYPE(C.c_ssize_t,C.c_int,W.WPARAM,W.LPARAM)
        api.SetWindowsHookExW.argtypes=[C.c_int,callback_type,W.HINSTANCE,W.DWORD];api.SetWindowsHookExW.restype=W.HANDLE
        api.CallNextHookEx.argtypes=[W.HANDLE,C.c_int,W.WPARAM,W.LPARAM];api.CallNextHookEx.restype=C.c_ssize_t
        api.UnhookWindowsHookEx.argtypes=[W.HANDLE];api.UnhookWindowsHookEx.restype=W.BOOL
        api.GetForegroundWindow.restype=W.HWND
        kernel.GetModuleHandleW.argtypes=[W.LPCWSTR];kernel.GetModuleHandleW.restype=W.HMODULE
        def callback(code,message,pointer):
            if code>=0:
                key=C.cast(pointer,C.POINTER(Key)).contents
                self.feed(key.vkCode,message,key.flags,api.GetForegroundWindow()==self.handle,time.perf_counter())
            return api.CallNextHookEx(None,code,message,pointer)
        callback_ref=callback_type(callback);hook=None
        try:
            hook=api.SetWindowsHookExW(13,callback_ref,kernel.GetModuleHandleW(None),0)
            if not hook:raise C.WinError(C.get_last_error())
            self.ready.set();message=W.MSG()
            while not self.done.wait(.005):
                while api.PeekMessageW(C.byref(message),None,0,0,1):
                    api.TranslateMessage(C.byref(message));api.DispatchMessageW(C.byref(message))
        except Exception as error:self.error=str(error);self.ready.set()
        finally:
            if hook:api.UnhookWindowsHookEx(hook)

    def close(self):
        self.done.set();self.thread.join(timeout=1)
        if self.thread.is_alive():raise RuntimeError('Space monitor did not stop')


class InputMeter:
    """Wrap successful dispatches, with a timeline aligned to capture time."""
    def __init__(self,computer,*,clock=time.perf_counter):
        self.computer=computer;self.clock=clock;self.lock=threading.RLock()
        self.history=deque(maxlen=12000)
        self.history.append((clock(),False,0.,0))

    def __getattr__(self,name):return getattr(self.computer,name)

    def _event(self,dx=0):
        t=self.clock();old_t,old_down,total,counts=self.history[-1]
        down='w' in self.computer.keys
        self.history.append((t,down,total+(t-old_t if old_down else 0),counts+dx))

    def perform(self,action):
        with self.lock:
            result=self.computer.perform(action)
            if result.outcome==Outcome.SUCCESS:
                self._event(action.arguments['dx'] if action.name=='move_relative' else 0)
            return result

    def release_all(self):
        with self.lock:
            try:self.computer.release_all()
            finally:self._event()

    def snapshot(self,t):
        with self.lock:
            if ('w' in self.computer.keys)!=self.history[-1][1]:self._event()
            event=next((e for e in reversed(self.history) if e[0]<=t),self.history[0])
            stamp,down,total,counts=event
            return dict(w_seconds=total+(max(0,t-stamp) if down else 0),mouse_counts=counts)
