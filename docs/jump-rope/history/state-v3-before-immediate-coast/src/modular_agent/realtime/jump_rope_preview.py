"""Latest-frame diagnostics in a native non-activating window; no input injection."""
import ctypes as C
from ctypes import wintypes as W
import threading
import time
import cv2
import numpy as np


def render_frame(image,observation,decision,config,fps):
    canvas=image.copy()
    if config.get('local_motion') and canvas.shape[1]<480:
        canvas=cv2.resize(canvas,(480,round(canvas.shape[0]*480/canvas.shape[1])))
    h,w=canvas.shape[:2];l,t,r,b=config['roi']
    def point(x,y):return round((x-l)/(r-l)*w),round((y-t)/(b-t)*h)
    for box in observation.get('motion_boxes',[]):
        cv2.rectangle(canvas,point(box[0],box[1]),point(box[2],box[3]),(0,0,255),1)
    points=observation.get('rope_points',[])
    if not observation.get('rope_valid'):points=[]
    for x,y in points:cv2.circle(canvas,point(x,y),4,(0,255,0),-1)
    if observation.get('rope_valid') and len(points)>=3:
        xy=np.array(points);center=float(observation.get('arrow_position',[.565,0])[0] if observation.get('arrow_position') else .565)
        coef=np.polyfit(xy[:,0]-center,xy[:,1],2)
        xx=np.linspace(xy[:,0].min(),xy[:,0].max(),60)
        curve=np.array([point(x,float(np.polyval(coef,x-center))) for x in xx],np.int32)
        cv2.polylines(canvas,[curve],False,(255,255,0),2)
        if observation.get('rope_y') is not None:
            cv2.circle(canvas,point(center,observation['rope_y']),6,(255,0,255),2)
    if observation.get('rope_valid') and observation.get('shape_projected'):
        center=observation.get('tracked_center_x',.565);coef=observation.get('rope_coefficients')
        if coef is not None:
            xx=np.linspace(center-.035,center+.035,30)
            curve=[point(x,float(np.polyval(coef,x-center))) for x in xx]
            for i in range(0,len(curve)-1,2):cv2.line(canvas,curve[i],curve[i+1],(0,165,255),1)
    whole=observation.get('whole_curve',[]);states=observation.get('whole_point_states',[])
    for i,((x,y),status) in enumerate(zip(whole,states)):
        color=(0,255,0) if status=='measured' else (0,165,255) if status=='predicted' else (110,110,110)
        cv2.circle(canvas,point(x,y),3,color,-1)
        if config.get('phase_rope') and i and status=='unknown' and i%3==0:cv2.line(canvas,point(*whole[i-1]),point(x,y),color,1)
        if i and status!='unknown' and states[i-1]!='unknown':
            if status=='measured' and states[i-1]=='measured' or i%2==0:cv2.line(canvas,point(*whole[i-1]),point(x,y),color,2)
    for x,y in observation.get('whole_observed_points',[]):cv2.circle(canvas,point(x,y),2,(0,255,0),-1)
    for anchor in observation.get('hand_anchors',[]):
        if anchor.get('point'):
            cv2.drawMarker(canvas,point(*anchor['point']),(255,0,255) if anchor['source']=='measured' else (0,165,255),cv2.MARKER_CROSS,18,2)
    arrow=observation.get('arrow_position')
    if arrow:cv2.drawMarker(canvas,point(*arrow),(0,255,255),cv2.MARKER_CROSS,16,2)
    baseline=config['avatar_template'][1]
    band=config.get('local_jump_band',[baseline-.20,baseline+.025])
    for y,color in ([] if config.get('whole_rope') else [(baseline,(255,255,255)),(band[0],(0,165,255)),(band[1],(0,165,255))]):
        py=point(l,y)[1];cv2.line(canvas,(0,py),(w-1,py),color,1)
    prediction=decision.get('prediction') or {}
    if prediction.get('danger_y') is not None:
        py=point(l,prediction['danger_y'])[1];cv2.line(canvas,(0,py),(w-1,py),(255,80,40),2)
    historical=decision.get('prediction') or {}
    if historical.get('historical') and historical.get('rope_y') is not None:
        cv2.drawMarker(canvas,point(arrow[0] if arrow else .565,historical['rope_y']),(0,0,255),cv2.MARKER_DIAMOND,16,2)
    panel=np.zeros((217,w,3),np.uint8)
    def number(value):return '--' if value is None else f'{value:.4f}'
    debug=decision.get('controller_debug',{})
    lines=[f'{fps:.1f} FPS | {decision.get("state")} / {observation.get("motion_mode_candidate") or decision.get("mode")}',
        f'Avatar {observation.get("avatar_valid")} ({observation.get("avatar_source")}) | rope {observation.get("rope_valid")}',
        f'y={number(observation.get("rope_y"))} speed={number(decision.get("motion_speed",historical.get("speed")))}',
        f'curve error={number(observation.get("curve_error"))} source={observation.get("selection_method")}' if observation.get('rope_valid') else f'rope reject: {observation.get("rope_rejection", "missing")}',
        f'slope={number(observation.get("rope_slope"))} curvature={number(observation.get("rope_curvature"))}',
        f'ground={debug.get("ground_frames")} consumed={debug.get("pass_consumed")} outstanding={debug.get("jump_outstanding")}',
        f'input={decision.get("down")} trigger={decision.get("trigger", "--")}',
        f'blocked: {decision.get("input_inhibited")} eta={number(prediction.get("eta"))}',
        'green=points cyan=fit magenta=rope red=prediction',
        'red boxes=motion orange=trial band white=ground']
    if config.get('whole_rope'):
        anchors=observation.get('hand_anchors',[])
        lines=[(f'{fps:.1f} FPS' if fps>0 else 'Offline replay')+' | whole rope judgment only',
            f'track={observation.get("track_id")} {observation.get("tracking_status")} phase={observation.get("motion_phase")}',
            f'coverage={number(observation.get("whole_coverage"))} flow={observation.get("flow_points")}',
            f'left={anchors[0]["source"] if anchors else "--"} right={anchors[1]["source"] if anchors else "--"}',
            f'center y={number(observation.get("rope_y"))} speed={number(observation.get("motion_speed"))}',
            f'rejected={observation.get("continuity_rejections")} residual={number(observation.get("continuity_residual"))}',
            'green=visible orange=history gray=unknown',
            'magenta=template anchor orange=prior/prediction',
            'No Space input; hidden curve is not measured']
    if config.get('phase_rope'):
        phase=observation.get('phase_estimate',{})
        lines=[(f'{fps:.1f} FPS' if fps>0 else 'Offline replay')+(' | signed trajectory v2 | NO INPUT' if config.get('phase_reverse') else ' | fixed trajectory phase v1 | NO INPUT'),
            f'{observation.get("tracking_status")} model exists={observation.get("model_exists")}',
            f'phase={number(phase.get("phase"))} rate={number(phase.get("rate"))} cycles/s',
            f'confidence={number(phase.get("confidence"))} uncertainty={number(phase.get("uncertainty"))} cycles',
            f'visual={observation.get("rope_valid")} quality={number(observation.get("phase_visual_quality"))}',
            f'age={number(phase.get("observation_age"))} s | coverage={number(observation.get("whole_coverage"))}',
            'green=visible support orange=model gray=uncertain model',
            'Rotation atlas only; low swing NOT calibrated',
            (f'direction={phase.get("direction")} turns={phase.get("reversals")} pending={phase.get("reversal_pending")}' if config.get('phase_reverse') else 'No danger phase / jump timing calibration')]
    if config.get('phase_state'):
        phase=observation.get('phase_estimate',{})
        unit='coordinate/s' if observation.get('motion_state')=='low_swing' else 'cycles/s'
        lines=[(f'{fps:.1f} FPS' if fps>0 else 'Offline replay')+' | legal motion state v3 | NO INPUT',
            f'{observation.get("motion_state")} | {observation.get("tracking_status")}',
            f'position={number(phase.get("phase"))} rate={number(phase.get("rate"))} {unit}',
            f'confidence={number(phase.get("confidence"))} uncertainty={number(phase.get("uncertainty"))}',
            f'visual={observation.get("rope_valid")} q={number(observation.get("phase_visual_quality"))} coverage={number(observation.get("whole_coverage"))}',
            f'direction={phase.get("direction")} state changes={observation.get("mode_changes")} wide={phase.get("search_wide")}',
            f'reacquisitions={observation.get("reacquisitions")} candidate={observation.get("mode_candidate")}',
            'green=visible support orange=prediction gray=uncertain',
            'Experimental swing atlas / no jump calibration']
    for i,line in enumerate(lines):cv2.putText(panel,line,(6,18+i*21),cv2.FONT_HERSHEY_SIMPLEX,.40,(230,230,230),1,cv2.LINE_AA)
    return np.concatenate([canvas,panel],axis=0)


class Preview:
    def __init__(self,config):
        self.config=config;self.stop=threading.Event();self.lock=threading.Lock()
        self.latest=None;self.error=None;self.last_publish=0;self.frames=0;self.render_ms=0
        self.thread=threading.Thread(target=self._run,name='jump-rope-preview',daemon=True)
        self.thread.start()
    def publish(self,image,observation,decision,bounds,fps):
        now=time.perf_counter()
        if self.error:raise RuntimeError('preview: '+self.error)
        if self.stop.is_set() or now-self.last_publish<.05:return
        self.last_publish=now
        with self.lock:self.latest=(image.copy(),observation.copy(),decision.copy(),bounds,fps)
    def close(self):
        self.stop.set();self.thread.join(timeout=3)
    def _run(self):
        hwnd=None
        try:
            api=C.WinDLL('user32',use_last_error=True);gdi=C.WinDLL('gdi32',use_last_error=True)
            proc_type=C.WINFUNCTYPE(C.c_ssize_t,W.HWND,W.UINT,W.WPARAM,W.LPARAM)
            api.DefWindowProcW.argtypes=[W.HWND,W.UINT,W.WPARAM,W.LPARAM];api.DefWindowProcW.restype=C.c_ssize_t
            def procedure(window,msg,wp,lp):
                if msg==0x21:return 3 # WM_MOUSEACTIVATE: MA_NOACTIVATE
                if msg==0x10:self.stop.set();return 0
                return api.DefWindowProcW(window,msg,wp,lp)
            callback=proc_type(procedure)
            class Class(C.Structure):
                _fields_=[('style',W.UINT),('proc',proc_type),('extra',C.c_int),('window_extra',C.c_int),('instance',W.HINSTANCE),('icon',W.HICON),('cursor',W.HANDLE),('background',W.HBRUSH),('menu',W.LPCWSTR),('name',W.LPCWSTR)]
            class Header(C.Structure):
                _fields_=[('size',W.DWORD),('width',W.LONG),('height',W.LONG),('planes',W.WORD),('bits',W.WORD),('compression',W.DWORD),('image_size',W.DWORD),('xppm',W.LONG),('yppm',W.LONG),('used',W.DWORD),('important',W.DWORD)]
            class Info(C.Structure):_fields_=[('header',Header),('colors',W.DWORD*3)]
            name=f'JumpRopePreview-{threading.get_ident()}'
            wc=Class();wc.proc=callback;wc.name=name
            api.RegisterClassW.argtypes=[C.POINTER(Class)];api.RegisterClassW.restype=W.ATOM
            if not api.RegisterClassW(C.byref(wc)):raise C.WinError(C.get_last_error())
            api.CreateWindowExW.argtypes=[W.DWORD,W.LPCWSTR,W.LPCWSTR,W.DWORD,C.c_int,C.c_int,C.c_int,C.c_int,W.HWND,W.HMENU,W.HINSTANCE,C.c_void_p];api.CreateWindowExW.restype=W.HWND
            api.ShowWindow.argtypes=[W.HWND,C.c_int];api.GetDC.argtypes=[W.HWND];api.GetDC.restype=W.HDC
            api.ReleaseDC.argtypes=[W.HWND,W.HDC];api.DestroyWindow.argtypes=[W.HWND]
            api.PeekMessageW.argtypes=[C.POINTER(W.MSG),W.HWND,W.UINT,W.UINT,W.UINT]
            api.TranslateMessage.argtypes=[C.POINTER(W.MSG)];api.DispatchMessageW.argtypes=[C.POINTER(W.MSG)];api.DispatchMessageW.restype=C.c_ssize_t
            api.SetWindowPos.argtypes=[W.HWND,W.HWND,C.c_int,C.c_int,C.c_int,C.c_int,W.UINT]
            gdi.SetDIBitsToDevice.argtypes=[W.HDC,C.c_int,C.c_int,W.DWORD,W.DWORD,C.c_int,C.c_int,W.UINT,W.UINT,C.c_void_p,C.POINTER(Info),W.UINT]
            view_size=None
            while not self.stop.is_set():
                with self.lock:item=self.latest;self.latest=None
                if item:
                    started=time.perf_counter();im,o,d,bounds,fps=item
                    canvas=render_frame(im,o,d,self.config,fps)
                    if hwnd is None:
                        x,y,cw,ch=bounds;sw=api.GetSystemMetrics(0);sh=api.GetSystemMetrics(1)
                        free=sw-(x+cw+8)
                        vw=min(canvas.shape[1],free-4) if free>=320 else min(380,max(160,round(cw*.32)))
                        vx=x+cw+8 if free>=320 else x
                        vh=min(sh-40,round(canvas.shape[0]*vw/canvas.shape[1]));vy=max(0,min(y,sh-vh-8));view_size=(vw,vh)
                        hwnd=api.CreateWindowExW(0x08000000|0x80,name,'Jump rope diagnostics',0x80000000|0x00800000,vx,vy,vw+2,vh+2,None,None,None,None)
                        if not hwnd:raise C.WinError(C.get_last_error())
                        # No activation, no topmost overlap with the tracking region.
                        api.SetWindowPos(hwnd,None,vx,vy,vw+2,vh+2,0x0010|0x0004)
                        api.ShowWindow(hwnd,4)
                    canvas=cv2.resize(canvas,view_size);pixels=cv2.cvtColor(canvas,cv2.COLOR_BGR2BGRA)
                    info=Info();info.header=Header(C.sizeof(Header),pixels.shape[1],-pixels.shape[0],1,32,0,pixels.nbytes,0,0,0,0)
                    dc=api.GetDC(hwnd)
                    try:gdi.SetDIBitsToDevice(dc,0,0,pixels.shape[1],pixels.shape[0],0,0,0,pixels.shape[0],pixels.ctypes.data,C.byref(info),0)
                    finally:api.ReleaseDC(hwnd,dc)
                    self.frames+=1;self.render_ms+=(time.perf_counter()-started)*1000
                if hwnd:
                    message=W.MSG()
                    while api.PeekMessageW(C.byref(message),hwnd,0,0,1):
                        api.TranslateMessage(C.byref(message));api.DispatchMessageW(C.byref(message))
                self.stop.wait(.01)
        except Exception as error:self.error=str(error)
        finally:
            if hwnd:api.DestroyWindow(hwnd)
