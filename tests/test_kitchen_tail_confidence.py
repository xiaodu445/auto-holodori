import unittest
from unittest.mock import Mock
from modular_agent.realtime.kitchen_match import Item,Observation,Settings,plan
from modular_agent.realtime.kitchen_vision import KitchenDetector
class TailThresholdTests(unittest.TestCase):
    def item(self,index=0,score=.18):return Item(str(index),'seaweed',20+index*40,30,score,(10+index*40,20,35+index*40,45))
    def test_sparse_low_confidence_target_can_be_taken(self):
        item=self.item();ob=Observation(1,0,0,(item,),tray=('',)*7,ui_details=dict(tail_confidence=.12))
        self.assertEqual(plan(ob,set(),Settings(confidence=.25),0),(item,))
    def test_dense_board_keeps_normal_threshold(self):
        items=tuple(self.item(i,.9 if i<3 else .18) for i in range(4))
        ob=Observation(1,0,0,items,tray=('',)*7,ui_details=dict(tail_confidence=.12))
        result=plan(ob,set(),Settings(confidence=.25),0)
        self.assertEqual(len(result),3);self.assertNotIn(items[-1],result)
    def test_disabled_exploration_does_not_lower_threshold(self):
        ob=Observation(1,0,0,(self.item(),),tray=('',)*7,ui_details=dict(tail_confidence=.12))
        self.assertEqual(plan(ob,set(),Settings(confidence=.25,exploratory=False),0),())
    def test_low_threshold_never_ignores_capacity_or_only_targets(self):
        ob=Observation(1,0,0,(self.item(),),tray=('a',)*6+('',),ui_details=dict(tail_confidence=.12))
        self.assertEqual(plan(ob,set(),Settings(confidence=.25),0),())
        ob=Observation(1,0,0,(self.item(),),tray=('',)*7,ui_details=dict(tail_confidence=.12))
        self.assertEqual(plan(ob,{'milk_blue'},Settings(confidence=.25,only_targets=True),0),())
class TensorRTFallbackTests(unittest.TestCase):
    def detector(self):
        d=KitchenDetector.__new__(KitchenDetector);d.engine_size=736;d.tail_confidence=.12;d.device='0';d.model=Mock()
        d._fallback=Mock(side_effect=lambda reason:setattr(d,'engine_size',None));return d
    def test_different_native_resolution_falls_back_without_resizing(self):
        d=self.detector();d._predict_model('image',960)
        d._fallback.assert_called_once();self.assertEqual(d.model.predict.call_args.kwargs['imgsz'],960)
    def test_engine_failure_retries_pytorch_only_once(self):
        d=self.detector();d.model.predict.side_effect=[RuntimeError('incompatible engine'),['result']]
        self.assertEqual(d._predict_model('image',736),['result']);d._fallback.assert_called_once()
    def test_pytorch_failure_is_not_hidden(self):
        d=self.detector();d.engine_size=None;d.model.predict.side_effect=RuntimeError('bad')
        with self.assertRaises(RuntimeError):d._predict_model('image',736)
        d._fallback.assert_not_called()
