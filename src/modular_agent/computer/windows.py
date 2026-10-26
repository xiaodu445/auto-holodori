"""Native Windows input backend; independent of perception and models."""
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
import os
import subprocess

class MouseInput(C.Structure):
    _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('mouseData', W.DWORD), ('dwFlags', W.DWORD), ('time', W.DWORD), ('dwExtraInfo', C.c_size_t)]
class KeyboardInput(C.Structure):
    _fields_ = [('wVk', W.WORD), ('wScan', W.WORD), ('dwFlags', W.DWORD), ('time', W.DWORD), ('dwExtraInfo', C.c_size_t)]
class HardwareInput(C.Structure):
    _fields_ = [('uMsg', W.DWORD), ('wParamL', W.WORD), ('wParamH', W.WORD)]
class InputUnion(C.Union):
    _fields_ = [('mi', MouseInput), ('ki', KeyboardInput), ('hi', HardwareInput)]
class Input(C.Structure):
    _anonymous_ = ('payload',)
    _fields_ = [('type', W.DWORD), ('payload', InputUnion)]
KEYS = {'backspace':8, 'tab':9, 'enter':13, 'shift':16, 'ctrl':17, 'alt':18, 'escape':27, 'space':32, 'pageup':33, 'pagedown':34, 'end':35, 'home':36, 'left':37, 'up':38, 'right':39, 'down':40, 'insert':45, 'delete':46, 'win':91, 'rctrl':163, 'ralt':165}
KEYS.update({chr(i).lower():i for i in range(65,91)})
KEYS.update({str(i):48+i for i in range(10)})
KEYS.update({f'f{i}':111+i for i in range(1,13)})
EXTENDED = {'pageup','pagedown','end','home','left','up','right','down','insert','delete','win','rctrl','ralt'}
BUTTONS = {'left':(2,4), 'right':(8,16), 'middle':(32,64)}

class WindowsBackend:
    def __init__(self):
        if os.name != 'nt': raise RuntimeError('Live operation requires Windows')
        self.api = C.WinDLL('user32', use_last_error=True)
        self.api.SendInput.argtypes = [W.UINT,C.POINTER(Input),C.c_int]
        self.api.SendInput.restype = W.UINT
        self.api.MapVirtualKeyW.argtypes = [W.UINT,W.UINT]
        self.api.MapVirtualKeyW.restype = W.UINT
        self.api.GetAsyncKeyState.argtypes = [C.c_int]
        self.api.GetAsyncKeyState.restype = C.c_short
        self.api.GetForegroundWindow.restype = W.HWND
        for name in ('IsWindow','IsWindowVisible','GetWindowTextLengthW','SetForegroundWindow'):
            getattr(self.api,name).argtypes = [W.HWND]
        self.api.ShowWindow.argtypes = [W.HWND,C.c_int]
        self.api.GetWindowTextW.argtypes = [W.HWND,W.LPWSTR,C.c_int]
        self.api.GetWindowThreadProcessId.argtypes = [W.HWND,C.POINTER(W.DWORD)]
        self.callback_type = C.WINFUNCTYPE(W.BOOL,W.HWND,W.LPARAM)
        self.api.EnumWindows.argtypes = [self.callback_type,W.LPARAM]
        self.api.GetClassNameW.argtypes = [W.HWND,W.LPWSTR,C.c_int]
        self.api.GetCursorPos.argtypes = [C.POINTER(W.POINT)]
        try:
            self.api.SetThreadDpiAwarenessContext.argtypes = [C.c_void_p]
            self.api.SetThreadDpiAwarenessContext.restype = C.c_void_p
            self.api.SetThreadDpiAwarenessContext(C.c_void_p(-4))
        except AttributeError: pass
    def _send(self,event):
        if self.api.SendInput(1,C.byref(event),C.sizeof(Input)) != 1:
            raise OSError(C.get_last_error(),'SendInput failed; check foreground application permissions')
    def key(self,name,down):
        scan = self.api.MapVirtualKeyW(KEYS[name],0)
        if not scan: raise ValueError(f'No scan code for {name}')
        flags = 8 | (0 if down else 2) | (1 if name in EXTENDED else 0)
        self._send(Input(type=1,ki=KeyboardInput(0,scan,flags,0,0)))
    def text(self,text):
        encoded = text.encode('utf-16-le')
        for offset in range(0,len(encoded),2):
            code = int.from_bytes(encoded[offset:offset+2],'little')
            for flags in (4,6): self._send(Input(type=1,ki=KeyboardInput(0,code,flags,0,0)))
    def mouse(self,dx=0,dy=0,flags=1,data=0):
        self._send(Input(type=0,mi=MouseInput(dx,dy,data & 0xffffffff,flags,0,0)))
    def move_to(self,x,y):
        # DPI awareness is thread-local; executor calls may run on another thread.
        try: self.api.SetThreadDpiAwarenessContext(C.c_void_p(-4))
        except AttributeError: pass
        left,top = self.api.GetSystemMetrics(76),self.api.GetSystemMetrics(77)
        width,height = self.api.GetSystemMetrics(78),self.api.GetSystemMetrics(79)
        if not (left <= x < left+width and top <= y < top+height):
            raise ValueError('Coordinates outside virtual desktop')
        self.mouse(round((x-left)*65535/max(1,width-1)),round((y-top)*65535/max(1,height-1)),0xC001)
    def button(self,name,down): self.mouse(flags=BUTTONS[name][0 if down else 1])
    def emergency_pressed(self): return bool(self.api.GetAsyncKeyState(123) & 0x8000)
    def windows(self):
        result = []
        foreground = self.api.GetForegroundWindow()
        @self.callback_type
        def visit(hwnd,unused):
            length = self.api.GetWindowTextLengthW(hwnd)
            if length and self.api.IsWindowVisible(hwnd):
                title = C.create_unicode_buffer(length+1)
                self.api.GetWindowTextW(hwnd,title,len(title))
                pid = W.DWORD()
                self.api.GetWindowThreadProcessId(hwnd,C.byref(pid))
                result.append({'handle':hwnd,'title':title.value,'pid':pid.value,'foreground':hwnd==foreground})
            return True
        if not self.api.EnumWindows(visit,0): raise OSError('Window enumeration failed')
        return result
    def window_resize_info(self,handle):
        try: self.api.SetThreadDpiAwarenessContext(C.c_void_p(-4))
        except AttributeError: pass
        if not self.api.IsWindow(handle): raise ValueError('Window no longer exists')
        self.api.GetWindowRect.argtypes=[W.HWND,C.POINTER(W.RECT)]
        rect=W.RECT()
        if not self.api.GetWindowRect(handle,C.byref(rect)): raise OSError('Cannot read window bounds')
        self.api.SendMessageTimeoutW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM,W.UINT,W.UINT,C.POINTER(C.c_size_t)]
        self.api.SendMessageTimeoutW.restype=W.LPARAM
        grip=None
        for inset in (2,4,6,8,10,12,16):
            x,y=rect.right-inset,rect.bottom-inset
            hit=C.c_size_t()
            packed=(x & 0xffff)|((y & 0xffff)<<16)
            if self.api.SendMessageTimeoutW(handle,0x84,0,packed,2,200,C.byref(hit)) and hit.value==17:
                grip={'x':x,'y':y}; break
        if grip is None: raise ValueError('没有确认到可拖动的右下边缘；拒绝在游戏内容区盲拖')
        self.api.WindowFromPoint.argtypes=[W.POINT]
        self.api.WindowFromPoint.restype=W.HWND
        self.api.GetAncestor.argtypes=[W.HWND,W.UINT]
        self.api.GetAncestor.restype=W.HWND
        visible=self.api.WindowFromPoint(W.POINT(grip['x'],grip['y']))
        if not visible or self.api.GetAncestor(visible,2)!=handle: raise ValueError('窗口右下边缘被其他窗口覆盖，请先移开遮挡')
        area=W.RECT()
        self.api.SystemParametersInfoW.argtypes=[W.UINT,W.UINT,C.c_void_p,W.UINT]
        if not self.api.SystemParametersInfoW(48,0,C.byref(area),0): raise OSError('Cannot read desktop work area')
        return {'bounds':{'x':rect.left,'y':rect.top,'width':rect.right-rect.left,'height':rect.bottom-rect.top},
            'grip':grip,'work_area':{'left':area.left,'top':area.top,'right':area.right,'bottom':area.bottom}}

    def resize_window(self,handle,width,height):
        try: self.api.SetThreadDpiAwarenessContext(C.c_void_p(-4))
        except AttributeError: pass
        if not self.api.IsWindow(handle): raise ValueError('Window no longer exists')
        self.api.GetWindowRect.argtypes = [W.HWND,C.POINTER(W.RECT)]
        self.api.SetWindowPos.argtypes = [W.HWND,W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT]
        self.api.SetWindowPos.restype = W.BOOL
        self.api.SystemParametersInfoW.argtypes = [W.UINT,W.UINT,C.c_void_p,W.UINT]
        area=W.RECT()
        if not self.api.SystemParametersInfoW(48,0,C.byref(area),0): raise OSError('Cannot read desktop work area')
        if width>area.right-area.left or height>area.bottom-area.top:
            raise ValueError('Requested game size exceeds desktop work area')
        self.api.ShowWindow(handle,9)
        rect=W.RECT()
        if not self.api.GetWindowRect(handle,C.byref(rect)): raise OSError('Cannot read window bounds')
        x=min(max(rect.left,area.left),area.right-width)
        y=min(max(rect.top,area.top),area.bottom-height)
        if not self.api.SetWindowPos(handle,None,x,y,width,height,0x0004):
            raise OSError(C.get_last_error(),'Window resize failed')
        actual=W.RECT()
        if not self.api.GetWindowRect(handle,C.byref(actual)): raise OSError('Cannot verify resized window bounds')
        return {'requested_width':width,'requested_height':height,'immediate_bounds':{'width':actual.right-actual.left,'height':actual.bottom-actual.top}}

    def focus(self,handle):
        if not self.api.IsWindow(handle): raise ValueError('Window no longer exists')
        self.api.ShowWindow(handle,9)
        if not self.api.SetForegroundWindow(handle): raise OSError('Windows refused foreground activation')
    def launch(self,executable,arguments): return subprocess.Popen([executable,*arguments],shell=False).pid
    def cursor(self):
        point = W.POINT()
        if not self.api.GetCursorPos(C.byref(point)): raise OSError('Cannot read cursor position')
        return {'x':point.x,'y':point.y}

    def show_desktop(self):
        handle=self.api.GetForegroundWindow()
        name=C.create_unicode_buffer(256)
        self.api.GetClassNameW(handle,name,len(name))
        if name.value in ('Progman','WorkerW'): return
        try:
            self.key('win',True)
            self.key('d',True)
        finally:
            self.key('d',False)
            self.key('win',False)
