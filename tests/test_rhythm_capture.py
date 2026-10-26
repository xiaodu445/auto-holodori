from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np
from modular_agent.realtime.rhythm_capture import DXGICapture,create_capture,release_camera

class Guard:
    def __init__(self):
        self.session=SimpleNamespace(monitors=[{},dict(left=0,top=0,width=1920,height=1080)])
        self.rect=(100,200,400,300);self.closed=False
    def bounds(self):return self.rect
    def close(self):self.closed=True

class Camera:
    width=1920;height=1080
    def __init__(self,frames):self.frames=iter(frames);self.closed=False;self.region=None
    def grab(self,**kwargs):self.region=kwargs;return next(self.frames)
    def release(self):self.closed=True

class CaptureTests(unittest.TestCase):
    def test_version_specific_com_ownership(self):
        from unittest.mock import Mock
        pointer=Mock();texture=Mock()
        camera=SimpleNamespace(_duplicator=SimpleNamespace(duplicator=pointer),
                               _stagesurf=SimpleNamespace(texture=texture),release=Mock())
        with patch('importlib.metadata.version',return_value='0.3.0'):release_camera(camera)
        pointer.AddRef.assert_called_once();texture.AddRef.assert_called_once();camera.release.assert_called_once()
    def test_other_versions_use_normal_release(self):
        from unittest.mock import Mock
        pointer=Mock();camera=SimpleNamespace(_duplicator=SimpleNamespace(duplicator=pointer),release=Mock())
        with patch('importlib.metadata.version',return_value='0.3.1'):release_camera(camera)
        pointer.AddRef.assert_not_called();camera.release.assert_called_once()
    def test_fresh_duplicate_and_none(self):
        frame=np.zeros((300,400,3),np.uint8);changed=frame.copy();changed[0,0]=1
        camera=Camera([frame,frame.copy(),None,changed]);guard=Guard()
        capture=DXGICapture(1,camera=camera,guard=guard)
        self.assertIsNotNone(capture.grab((0,0,1,1))[0]);stamp=capture.last_timestamp
        self.assertIsNone(capture.grab((0,0,1,1))[0]);self.assertEqual(stamp,capture.last_timestamp)
        self.assertIsNone(capture.grab((0,0,1,1))[0]);self.assertIsNotNone(capture.grab((0,0,1,1))[0])
        self.assertEqual(camera.region['region'],(100,200,500,500))
        self.assertTrue(camera.region['new_frame_only'])
        self.assertEqual(capture.stats['region_duplicates'],1)
        capture.close();self.assertTrue(camera.closed and guard.closed)
    def test_window_changed_during_capture(self):
        camera=Camera([np.zeros((300,400,3),np.uint8)]);guard=Guard()
        capture=DXGICapture(1,camera=camera,guard=guard)
        with patch.object(guard,'bounds',side_effect=[(100,200,400,300),(101,200,400,300)]):
            with self.assertRaisesRegex(RuntimeError,'changed'):capture.grab((0,0,1,1))
        capture.close()
    def test_outside_primary_rejected(self):
        guard=Guard();guard.rect=(-100,0,400,300);camera=Camera([])
        capture=DXGICapture(1,camera=camera,guard=guard)
        with self.assertRaisesRegex(RuntimeError,'primary'):capture.grab((0,0,1,1))
        capture.close()
    def test_initialization_cleanup(self):
        guard=Guard();camera=Camera([]);camera.width=123
        with self.assertRaises(RuntimeError):DXGICapture(1,camera=camera,guard=guard)
        self.assertTrue(camera.closed and guard.closed)
    def test_auto_fallback_and_explicit_failure(self):
        with patch('modular_agent.realtime.rhythm_capture.DXGICapture',side_effect=RuntimeError('missing')):
            with patch('modular_agent.realtime.rhythm_capture.WindowCapture',return_value=Guard()):
                c=create_capture(1,'auto');self.assertEqual(c.stats['fallback_reason'],'missing')
            with self.assertRaises(RuntimeError):create_capture(1,'dxcam')

if __name__=='__main__':unittest.main()
