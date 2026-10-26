"""Offline curve-end cleanup probe: no desktop capture, COM or game input."""
from importlib.metadata import version
from types import SimpleNamespace
from modular_agent.realtime.rhythm_capture import DXGICapture

def check_cleanup():
    actual=version('dxcam')
    class Pointer:
        calls=0
        def AddRef(self):self.calls+=1
    pointer=Pointer();texture=Pointer();calls=[]
    camera=SimpleNamespace(_duplicator=SimpleNamespace(duplicator=pointer),
        _stagesurf=SimpleNamespace(texture=texture),is_released=False,release=lambda:calls.append('released'))
    capture=DXGICapture.__new__(DXGICapture)
    capture.camera=camera;capture.guard=SimpleNamespace(close=lambda:None)
    capture.close();capture.close()
    assert calls==['released'] and capture.camera is None
    expected=1 if actual=='0.3.0' else 0
    assert pointer.calls==expected and texture.calls==expected
    return {'dxcam_version':actual,'camera_release_calls':len(calls),'native_addref_calls':pointer.calls+texture.calls,'game_input':False}

if __name__=='__main__':
    import json
    print(json.dumps(check_cleanup()))
