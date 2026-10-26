import ctypes
import tempfile
import threading
import unittest
from pathlib import Path
from modular_agent.computer import ActionComputer
from modular_agent.computer.windows import Input, KeyboardInput, MouseInput
from modular_agent.core import Action, Outcome

class FakeBackend:
    def __init__(self): self.events=[]; self.fail_key=None; self.emergency=False
    def emergency_pressed(self): return self.emergency
    def key(self,key,down):
        self.events.append(('key',key,down))
        if key == self.fail_key and down: raise OSError('injection failure')
    def button(self,key,down): self.events.append(('button',key,down))
    def mouse(self,dx=0,dy=0,flags=1,data=0): self.events.append(('mouse',dx,dy,flags,data))
    def move_to(self,x,y): self.events.append(('position',x,y))
    def cursor(self): return {'x':10,'y':20}
    def text(self,text): self.events.append(('text',text))
    def windows(self): return [{'handle':123,'title':'test'}]
    def focus(self,handle): self.events.append(('focus',handle))
    def launch(self,exe,args): self.events.append(('launch',exe,args)); return 42

class ComputerTests(unittest.TestCase):
    def test_native_abi_sizes(self):
        if ctypes.sizeof(ctypes.c_void_p)==8:
            self.assertEqual(ctypes.sizeof(Input),40)
            self.assertEqual(ctypes.sizeof(MouseInput),32)
            self.assertEqual(ctypes.sizeof(KeyboardInput),24)
    def test_dry_run_never_calls_backend(self):
        backend=FakeBackend()
        with ActionComputer(backend=backend) as c:
            result=c.perform(Action('press',arguments={'key':'w'}))
        self.assertEqual(result.outcome,Outcome.SUCCESS)
        self.assertEqual(backend.events,[])
    def test_hold_and_relative_motion_release_keys(self):
        backend=FakeBackend()
        with ActionComputer(live=True,backend=backend) as c:
            result=c.perform(Action('hold',arguments={'keys':['w','shift'],'duration':0,'dx':17,'dy':-9,'steps':4}))
            self.assertFalse(c.keys)
        self.assertEqual(result.outcome,Outcome.SUCCESS)
        motion=[e for e in backend.events if e[0]=='mouse']
        self.assertEqual(sum(e[1] for e in motion),17)
        self.assertEqual(sum(e[2] for e in motion),-9)
        self.assertEqual(backend.events[-2:],[('key','shift',False),('key','w',False)])
    def test_partial_input_failure_releases_every_key(self):
        backend=FakeBackend(); backend.fail_key='shift'
        with ActionComputer(live=True,backend=backend) as c:
            result=c.perform(Action('hotkey',arguments={'keys':['w','shift']}))
            self.assertFalse(c.keys)
        self.assertEqual(result.outcome,Outcome.FAILURE)
        self.assertIn(('key','w',False),backend.events)
        self.assertIn(('key','shift',False),backend.events)
    def test_invalid_batch_is_rejected_before_any_input(self):
        backend=FakeBackend()
        with ActionComputer(live=True,backend=backend) as c:
            with self.assertRaises(ValueError):
                c.run_actions([Action('press',arguments={'key':'w'}),Action('press',arguments={'key':'invalid'})])
        self.assertFalse(backend.events)
    def test_batch_releases_manual_holds(self):
        backend=FakeBackend()
        with ActionComputer(live=True,backend=backend) as c:
            c.run_actions([Action('key_down',arguments={'key':'w'}),Action('mouse_down')])
            self.assertFalse(c.keys); self.assertFalse(c.buttons)
        self.assertIn(('key','w',False),backend.events)
        self.assertIn(('button','left',False),backend.events)
    def test_programmatic_stop_interrupts_wait(self):
        backend=FakeBackend()
        with ActionComputer(live=True,backend=backend) as c:
            timer=threading.Timer(.03,c.stop); timer.start()
            result=c.perform(Action('hold',arguments={'keys':['w'],'duration':3}))
            timer.join(1)
            self.assertFalse(c.keys)
            self.assertEqual(result.outcome,Outcome.FAILURE)
            self.assertEqual(c.perform(Action('press',arguments={'key':'w'})).outcome,Outcome.FAILURE)
    def test_emergency_key_releases_existing_input(self):
        backend=FakeBackend()
        with ActionComputer(live=True,backend=backend) as c:
            c.perform(Action('key_down',arguments={'key':'w'}))
            backend.emergency=True
            result=c.perform(Action('move_relative',arguments={'dx':1,'dy':0}))
            self.assertEqual(result.outcome,Outcome.FAILURE)
            self.assertFalse(c.keys)
    def test_click_and_drag_release_button(self):
        backend=FakeBackend()
        with ActionComputer(live=True,backend=backend) as c:
            c.perform(Action('click',arguments={'count':2}))
            result=c.perform(Action('drag',arguments={'x':50,'y':60,'duration':0,'steps':2}))
        self.assertEqual(result.outcome,Outcome.SUCCESS)
        self.assertEqual(backend.events[-2:],[('position',50,60),('button','left',False)])
    def test_invalid_numeric_inputs(self):
        with ActionComputer() as c:
            for args in ({'duration':float('nan')},{'duration':31},{'duration':True}):
                self.assertEqual(c.perform(Action('wait',arguments=args)).outcome,Outcome.FAILURE)
    def test_audit_omits_text(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'actions.jsonl'
            with ActionComputer(audit_path=path) as c:
                c.perform(Action('text',arguments={'text':'secret-example'}))
            self.assertNotIn('secret-example',path.read_text())
    def test_launch_arguments_are_separate(self):
        backend=FakeBackend()
        with ActionComputer(live=True,backend=backend) as c:
            result=c.perform(Action('launch',arguments={'executable':'game.exe','arguments':['with spaces']}))
        self.assertEqual(result.data['pid'],42)
        self.assertIn(('launch','game.exe',['with spaces']),backend.events)

if __name__ == '__main__': unittest.main()
