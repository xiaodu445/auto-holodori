import tempfile
import unittest
from pathlib import Path
import cv2
import numpy as np
from modular_agent.perception import TemplateLibrary, KnowledgeMatcher

class TemplateForegroundTests(unittest.TestCase):
    def test_alpha_background_changes_do_not_change_target_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);template=np.zeros((30,30,4),np.uint8)
            rng=np.random.default_rng(12)
            template[8:22,8:22,:3]=rng.integers(20,240,(14,14,3),dtype=np.uint8)
            template[8:22,8:22,3]=255
            source=root/'icon.png';source.write_bytes(cv2.imencode('.png',template)[1].tobytes())
            library=TemplateLibrary(root/'library');library.add('icon',source,['game'],.95)
            matcher=KnowledgeMatcher([library])
            for background in (30,190):
                image=np.full((80,80,3),background,np.uint8)
                image[28:42,18:32]=template[8:22,8:22,:3]
                found=matcher.match(image,'game')
                self.assertTrue(any(m['bounds']['x']==10 and m['bounds']['y']==20 and m['similarity']>.99 for m in found))

    def test_warm_ui_ignores_nonforeground_background(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);template=np.full((32,32,3),(100,30,30),np.uint8)
            cv2.circle(template,(16,16),9,(0,210,255),-1)
            cv2.rectangle(template,(14,10),(18,22),(255,255,255),-1)
            source=root/'icon.png';source.write_bytes(cv2.imencode('.png',template)[1].tobytes())
            library=TemplateLibrary(root/'library');record=library.add('icon',source,['game'],.95)
            records=library.records();records[0].mask_mode='warm_ui';library._save(records)
            image=np.full((80,80,3),(30,60,120),np.uint8)
            hsv=cv2.cvtColor(template,cv2.COLOR_BGR2HSV)
            foreground=((hsv[:,:,0]<=40)&(hsv[:,:,1]>=80)&(hsv[:,:,2]>=180))|((hsv[:,:,1]<=60)&(hsv[:,:,2]>=205))
            roi=image[20:52,10:42];roi[foreground]=template[foreground]
            found=KnowledgeMatcher([library]).match(image,'game')
            self.assertTrue(any(m['bounds']['x']==10 and m['bounds']['y']==20 and m['similarity']>.99 for m in found))
