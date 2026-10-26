import json
from pathlib import Path
import tempfile
import unittest
import cv2
import numpy as np
from unittest.mock import patch
import prepare
from prepare import label_row,choose_split
from modular_agent.realtime.kitchen_labels import LabelStore,atomic_json


class YoloDataTests(unittest.TestCase):
    def test_real_box_and_keypoint_normalization(self):
        row=label_row(dict(class_id='rice',x=40,y=30,bbox=[20,10,60,50]),['rice'],[10,0,110,100])
        np.testing.assert_allclose(row,[0,.3,.3,.4,.4,.3,.3,2])
        with self.assertRaises(ValueError):label_row(dict(class_id='rice',x=40,y=30),['rice'],[0,0,100,100])

    def test_missing_boxes_block_export_then_real_boxes_export(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);rec=root/'recording';rec.mkdir();work=root/'manual'
            (rec/'timestamps.json').write_text(json.dumps([dict(t=i) for i in range(4)]))
            writer=cv2.VideoWriter(str(rec/'screen.avi'),cv2.VideoWriter_fourcc(*'MJPG'),10,(48,32))
            for i in range(4):writer.write(np.zeros((32,48,3),np.uint8))
            writer.release();store=LabelStore(rec,work)
            for i in range(4):
                f=store.frame(i,48,32);store.add_point(f,'rice',20,16);f['complete']=True
            store.save();atomic_json(work/'selection.json',dict(frames=[dict(video_index=i) for i in range(4)]))
            classes=root/'classes.json';atomic_json(classes,dict(classes=[dict(id='rice',name='rice')]))
            with patch.object(prepare,'ROOT',root):
                report,path=prepare.prepare(work,rec,classes)
                self.assertIsNone(path);self.assertEqual(report['missing_boxes'],4)
                for f in store.data['frames'].values():store.set_bbox(f,f['points'][0]['instance_id'],[12,10,29,25])
                store.save();report,path=prepare.prepare(work,rec,classes)
                self.assertTrue(report['ready']);self.assertEqual(report['train_frames'],3);self.assertEqual(report['val_frames'],1)
                cfg=json.loads(path.read_text());self.assertEqual(cfg['kpt_shape'],[1,3])
                labels=list(path.parent.glob('labels/*/*.txt'));self.assertEqual(len(labels),4)
                self.assertTrue(all(len(p.read_text().split())==8 for p in labels))

    def test_split_keeps_each_class_in_training(self):
        frames=[dict(video_index=i,points=[dict(class_id='common')]+([dict(class_id='rare')] if i==0 else [])) for i in range(4)]
        train,val=choose_split(frames)
        self.assertTrue(any(f['video_index']==0 for f in train))
        self.assertTrue(all(f['video_index']!=0 for f in val))


class NativePixelTests(unittest.TestCase):
    def test_padding_keeps_pixels_and_point_coordinates(self):
        image=np.arange(410*729*3,dtype=np.uint32).reshape(410,729,3).astype(np.uint8)
        row=[0,.5,.5,.2,.3,.25,.75,2]
        padded,labels,transform=prepare.native_square(image,[row])
        self.assertEqual(padded.shape,(736,736,3))
        left,top=transform['padding_left'],transform['padding_top']
        np.testing.assert_array_equal(padded[top:top+410,left:left+729],image)
        self.assertEqual(transform['scale'],1.0)
        self.assertAlmostEqual(labels[0][5]*736-left,.25*729)
        self.assertAlmostEqual(labels[0][6]*736-top,.75*410)
