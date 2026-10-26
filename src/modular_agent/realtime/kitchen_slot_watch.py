"""Independent occupancy scan; only the residual prefix needs class recognition."""
import cv2,numpy as np
from .kitchen_ui import HudReader,TRAY_RECTS,crop_rect,descriptor,matches_empty_slot

class SlotWatcher:
    def __init__(self,bank):self.reader=HudReader(bank)
    def reset(self):pass
    def observe(self,image,frame_id,captured,full_slots=False):
        patches=[crop_rect(image,rect) for rect in TRAY_RECTS]
        occupied_flags=[]
        for patch in patches:
            small=cv2.resize(patch,(32,32)).astype(float)
            empty=descriptor(patch) is None or matches_empty_slot(small,self.reader.empties)
            occupied_flags.append(not empty)
        occupied=sum(occupied_flags);prefix_count=max(0,occupied-3)
        details=[]
        for i,(patch,occupied_here) in enumerate(zip(patches,occupied_flags)):
            classify_here=occupied_here and (full_slots or i<prefix_count)
            key,score,margin=self.reader.classify_tray(patch) if classify_here else (None,0.,0.)
            value='' if not occupied_here else key if classify_here and score>=.78 and margin>=.025 else '?'
            details.append(dict(slot=i,value=value,occupied=occupied_here,classified=classify_here,score=score,margin=margin))
        prefix=[row['value'] or '?' for row in details[:prefix_count]]
        return dict(frame_id=frame_id,captured=captured,prefix=prefix,occupied_count=occupied,slots=details,classification_scope='full_slots' if full_slots else 'residual_prefix',rule='occupied_minus_three')
