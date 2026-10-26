"""Optional DXGI capture for rhythm; synchronous latest-frame acquisition."""
from __future__ import annotations
import time
import zlib
from modular_agent.realtime.runtime import WindowCapture
from modular_agent.realtime.dxgi_selection import select_output,CaptureSafetyStop


def release_camera(camera):
    """Balance dxcam 0.3.0 explicit Releases with comtypes pointer ownership.

    0.3.0 manually Release()s these pointers and also drops their owning Python
    wrappers, whose destructors Release again. Retain one native reference for
    each explicit release. Do not change installed vendor files or other versions.
    """
    from importlib.metadata import version
    retained=[]
    if getattr(camera,'_duplicator',None) is not None and not getattr(camera,'is_released',False) and version('dxcam')=='0.3.0':
        for owner,name in ((getattr(camera,'_duplicator',None),'duplicator'),
                           (getattr(camera,'_stagesurf',None),'texture')):
            pointer=getattr(owner,name,None)
            if pointer is not None:
                pointer.AddRef();retained.append(pointer)
    camera.release()


class DXGICapture:
    def __init__(self,handle,*,camera=None,guard=None):
        self.guard=guard or WindowCapture(handle)
        self.camera=None;self.last_timestamp=None;self.last_hash=None;self.last_bounds=None
        self.stats=dict(backend='dxcam',polls=0,new_desktop_frames=0,no_new_frame=0,region_duplicates=0)
        try:
            if camera is None:
                import dxcam
                camera,monitor,attempts=select_output(self.guard,dxcam,release_camera)
                self.stats['output_selection']=attempts
                self.monitor=monitor
            else:self.monitor=dict(self.guard.session.monitors[1])
            self.camera=camera
            # The selected output owns the entire game client area. Never use
            # another output merely because its resolution happens to match.
            monitor=self.monitor
            if (monitor['width'],monitor['height'])!=(camera.width,camera.height):
                raise RuntimeError('DXGI output does not match selected monitor')
        except Exception:
            self.close();raise

    def bounds(self):return self.guard.bounds()

    def grab(self,roi):
        started=time.perf_counter();bounds=self.bounds()
        x,y,w,h=bounds;l,t,r,b=roi;m=self.monitor
        region=(x+round(l*w)-m['left'],y+round(t*h)-m['top'],
                x+round(r*w)-m['left'],y+round(b*h)-m['top'])
        if not (0<=region[0]<region[2]<=m['width'] and 0<=region[1]<region[3]<=m['height']):
            raise RuntimeError('DXGI requires game wholly on selected monitor (primary or secondary)')
        self.stats['polls']+=1
        # No background queue and no cached-image replay. Owned frame memory
        # remains valid through processing and preview publication.
        frame=self.camera.grab(region=region,copy=True,new_frame_only=True)
        completed=time.perf_counter()
        if self.bounds()!=bounds:raise RuntimeError('window_changed_during_capture')
        if frame is None:
            self.stats['no_new_frame']+=1;return None,bounds
        self.stats['new_desktop_frames']+=1
        if frame.shape[:2]!=(region[3]-region[1],region[2]-region[0]):
            raise RuntimeError('DXGI unexpected frame dimensions')
        signature=zlib.crc32(memoryview(frame))
        if signature==self.last_hash and bounds==self.last_bounds:
            self.stats['region_duplicates']+=1;return None,bounds
        self.last_hash,self.last_bounds=signature,bounds
        # Acquisition interval midpoint, not a claimed presentation timestamp.
        self.last_timestamp=(started+completed)/2
        return frame,bounds

    def close(self):
        try:
            if self.camera is not None:
                release_camera(self.camera);self.camera=None
        finally:self.guard.close()


def create_capture(handle,backend='auto'):
    if backend not in ('auto','dxcam','mss'):raise ValueError('invalid capture backend')
    if backend!='mss':
        try:return DXGICapture(handle)
        except CaptureSafetyStop:raise
        except Exception as error:
            if backend=='dxcam':raise
            fallback=str(error)
    else:fallback=None
    capture=WindowCapture(handle)
    capture.stats=dict(backend='mss',fallback_reason=fallback)
    return capture
