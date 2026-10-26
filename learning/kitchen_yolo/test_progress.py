import unittest
from unittest.mock import patch
from train import publish_progress

class ProgressTests(unittest.TestCase):
    def test_transient_reader_lock_retries(self):
        with patch('train.atomic_json',side_effect=[PermissionError('locked'),None]) as write,patch('train.time.sleep'):
            self.assertTrue(publish_progress('unused',{}));self.assertEqual(write.call_count,2)
    def test_progress_failure_cannot_abort_training(self):
        with patch('train.atomic_json',side_effect=PermissionError('locked')) as write,patch('train.time.sleep'):
            self.assertFalse(publish_progress('unused',{}));self.assertEqual(write.call_count,5)

class AugmentationTests(unittest.TestCase):
    def test_mild_changes_geometry_without_mirroring_or_mixing(self):
        from train import augmentation_parameters
        baseline=augmentation_parameters(True)
        mild=augmentation_parameters(True,True)
        self.assertTrue(all(value==0 for value in baseline.values()))
        self.assertEqual(mild['degrees'],30)
        self.assertEqual(mild['translate'],.03)
        self.assertEqual(mild['scale'],.1)
        for key in ['fliplr','flipud','mosaic','mixup','copy_paste','hsv_h']:self.assertEqual(mild[key],0)
