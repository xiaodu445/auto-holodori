import unittest
from unittest.mock import Mock,patch
import numpy as np
from modular_agent.realtime.dxgi_selection import select_output,CaptureSafetyStop,enumerate_outputs
from types import SimpleNamespace

class OutputSelectionTests(unittest.TestCase):
    def setUp(self):
        self.guard=Mock();self.guard.bounds.return_value=(100,200,400,300)
        self.frame=np.zeros((300,400,3),np.uint8)
        self.camera=SimpleNamespace(width=1920,height=1080,grab=Mock(return_value=self.frame))
        self.dxcam=Mock();self.dxcam.create.return_value=self.camera
        self.release=Mock();self.wait=Mock()
    def output(self,device=0,left=0):return dict(device_idx=device,output_idx=0,name='DISPLAY',attached=True,left=left,top=0,width=1920,height=1080)
    def select(self,outputs):return select_output(self.guard,self.dxcam,self.release,inventory=outputs,wait=self.wait)
    def test_first_adapter_fails_next_succeeds(self):
        self.dxcam.create.side_effect=[RuntimeError('unsupported'),self.camera]
        camera,monitor,attempts=self.select([self.output(),self.output(1)])
        self.assertIs(camera,self.camera);self.assertEqual(attempts[0]['result'],'failed');self.assertEqual(attempts[1]['result'],'verified_frame')
        self.assertEqual(self.dxcam.create.call_args.kwargs['device_idx'],1)
    def test_secondary_monitor_coordinate_translation_and_wrong_screen_skipped(self):
        self.guard.bounds.return_value=(-1800,200,400,300)
        _,monitor,attempts=self.select([self.output(),self.output(1,-1920)])
        self.assertEqual(attempts[0]['result'],'not_game_screen');self.assertEqual(monitor['left'],-1920)
        self.assertEqual(self.camera.grab.call_args.kwargs['region'],(120,200,520,500))
        self.assertEqual(self.dxcam.create.call_count,1)
    def test_successful_initialization_without_frame_not_accepted(self):
        failed=SimpleNamespace(width=1920,height=1080,grab=Mock(return_value=None))
        self.dxcam.create.side_effect=[failed,self.camera]
        _,_,attempts=self.select([self.output(),self.output(1)])
        self.assertEqual(failed.grab.call_count,20);self.release.assert_called_once_with(failed)
        self.assertEqual(attempts[1]['result'],'verified_frame')
    def test_all_fail_gives_detailed_reason(self):
        self.dxcam.create.side_effect=RuntimeError('unsupported')
        with self.assertRaisesRegex(RuntimeError,'unsupported'):self.select([self.output(),self.output(1)])
    def test_cancel_releases_camera_and_never_attempts_next_output(self):
        self.guard.bounds.side_effect=[(100,200,400,300),(100,200,400,300),RuntimeError('F12_stop')]
        with self.assertRaisesRegex(CaptureSafetyStop,'F12_stop'):self.select([self.output(),self.output(1)])
        self.release.assert_called_once_with(self.camera);self.assertEqual(self.dxcam.create.call_count,1)
    def test_spanning_window_does_not_select_wrong_output(self):
        self.guard.bounds.return_value=(1800,200,400,300)
        with self.assertRaisesRegex(RuntimeError,'not_game_screen'):self.select([self.output(),self.output(1,1920)])
        self.dxcam.create.assert_not_called()
    def test_invalid_dimensions_release_before_next(self):
        bad=SimpleNamespace(width=1920,height=1080,grab=Mock(return_value=np.zeros((10,10,3),np.uint8)))
        self.dxcam.create.side_effect=[bad,self.camera]
        self.select([self.output(),self.output(1)]);self.release.assert_called_once_with(bad)
    def test_moved_window_aborts_instead_of_trying_other_screen(self):
        self.guard.bounds.side_effect=[(100,200,400,300),(101,200,400,300)]
        with self.assertRaisesRegex(CaptureSafetyStop,'window_changed'):self.select([self.output()])
        self.dxcam.create.assert_not_called()
