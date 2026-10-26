"""Domain-only local fishing recognition."""
import cv2
import numpy as np

class FishingVision:
    def __init__(self, config, bite_template):
        self.config, self.bite_template = config, bite_template
    @staticmethod
    def mask(hsv, bounds):
        return cv2.inRange(hsv, np.array(bounds[0],np.uint8), np.array(bounds[1],np.uint8))
    def control(self, image):
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        h,w = image.shape[:2]
        yellow = self.mask(hsv,self.config['yellow_hsv'])
        fish = self.mask(hsv,self.config['fish_hsv'])
        def boxes(mask, minimum):
            contours,_ = cv2.findContours(mask,cv2.RETR_EXTERNAL,cv2.CHAIN_APPROX_SIMPLE)
            return [cv2.boundingRect(c) for c in contours if cv2.contourArea(c) >= minimum*w*h]
        fishes = [b for b in boxes(fish,.003) if .15*w < b[0]+b[2]/2 < .85*w and b[2]>.60*w and b[3]<.18*h]
        if len(fishes)!=1: return {'valid':False,'reason':'fish_missing_or_ambiguous'}
        # Stripe gaps are closed locally; fish occlusion leaves two yellow pieces.
        yellow = cv2.morphologyEx(yellow,cv2.MORPH_CLOSE,np.ones((max(3,round(h*.018)),3),np.uint8))
        pieces = [b for b in boxes(yellow,.002) if b[2]>.2*w and .1*w < b[0]+b[2]/2 < .9*w]
        if not pieces: return {'valid':False,'reason':'bar_missing'}
        x,y,fw,fh = fishes[0]
        # Only merge fragments aligned with fish and close enough to form one bar.
        pieces = [b for b in pieces if abs(b[0]+b[2]/2-(x+fw/2))<.3*w]
        if not pieces: return {'valid':False,'reason':'bar_alignment'}
        top=min(b[1] for b in pieces); bottom=max(b[1]+b[3] for b in pieces)
        if not .08 < (bottom-top)/h < .55: return {'valid':False,'reason':'bar_size'}
        return dict(valid=True, fish=(y+fh/2)/h, center=(top+bottom)/2/h,
                    bar_height=(bottom-top)/h, bar_top=top/h, bar_bottom=bottom/h)
    def bite(self, image):
        # Small local template only; never scans full screen or runs OCR.
        h,w=image.shape[:2]
        template=cv2.resize(self.bite_template,(max(1,round(w*.906)),max(1,round(h*.366))))
        if template.shape[0]>h or template.shape[1]>w: return {'bite':False,'score':0}
        score=float(cv2.minMaxLoc(cv2.matchTemplate(image,template,cv2.TM_CCOEFF_NORMED))[1])
        return {'bite':score>=self.config['bite_threshold'],'score':score}

