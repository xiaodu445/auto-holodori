"""Conservative scene inhibit for movement; never dismisses a popup."""
import cv2
import numpy as np


class JumpHudGate:
    """Normal and physically pressed jump HUD, each with its own template.

    The pressed animation shrinks the circle and enlarges the Space badge.
    Its masked template includes BOTH, with no dependency on ground colour.
    This is only HUD evidence; RouteSceneGate still vetoes popups/disabled UI.
    """
    def __init__(self):
        from .minimap_scan import FreeWorldGate
        from .patrol import DATA
        from modular_agent.domains.hololive_dreams.patrol_vision import read_image
        self.normal=FreeWorldGate()
        folder=DATA/'jump-hud-regression-m019'
        template=cv2.cvtColor(read_image(folder/'pressed-jump.png'),cv2.COLOR_BGR2GRAY)
        mask=read_image(folder/'pressed-mask.png')[:,:,0]
        self.variants=[(cv2.resize(template,None,fx=scale,fy=scale),
                        cv2.resize(mask,None,fx=scale,fy=scale,interpolation=cv2.INTER_NEAREST))
                       for scale in (.94,.97,1.,1.03,1.06)]
        self.state='unknown'

    def read(self,image):
        normal,score=self.normal.read(image)
        if normal:self.state='normal';return True,score
        frame=cv2.resize(image,(1260,709));roi=cv2.cvtColor(frame[500:655,1015:1185],cv2.COLOR_BGR2GRAY)
        best=0.
        for template,mask in self.variants:
            response=1-cv2.matchTemplate(roi,template,cv2.TM_SQDIFF_NORMED,mask=mask)
            response=np.nan_to_num(response,nan=-1,posinf=-1,neginf=-1)
            best=max(best,float(response.max()))
        self.state='pressed' if best>=.96 else 'unknown'
        return self.state=='pressed',max(score,best)


class PersistentWorldHud:
    """Minimap rim and enabled top controls, independent of jump availability."""
    def __init__(self):
        from .patrol import DATA
        from modular_agent.domains.hololive_dreams.patrol_vision import read_image
        source=cv2.resize(read_image(DATA/'references/free-world.png')[38:,:1260],(1260,709))
        self.rim=source[27:231,35:245]
        yy,xx=np.mgrid[:204,:210];radius=np.hypot(xx-108,yy-101)
        self.mask=((radius>=92)&(radius<=98)).astype(np.uint8)*255

    def read(self,image):
        frame=cv2.resize(image,(1260,709))
        response=cv2.matchTemplate(frame[27:231,35:245],self.rim,cv2.TM_SQDIFF_NORMED,mask=self.mask)
        score=1-float(np.nan_to_num(response,nan=1,posinf=1,neginf=1)[0,0])
        hsv=cv2.cvtColor(frame[20:115,700:1235],cv2.COLOR_BGR2HSV)
        warm=(hsv[:,:,0]>=8)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>70)&(hsv[:,:,2]>150)
        return bool(score>=.90 and float(warm.mean())>.035),score


class RouteSceneGate:
    BLOCKERS=('reward','rank_up','dialogue','options','scratch_ticket',
              'achievement_detail','achievement_list','notification_panel','map')

    def __init__(self,root):
        from modular_agent.domains.hololive_dreams.visual_features import extract
        self.hud=JumpHudGate();self.persistent=PersistentWorldHud()
        self.root=root;self.extract=extract;self.features={};self.diagnostics={};self.jump_available=False

    def movement_hud(self,image):
        jump,score=self.hud.read(image)
        self.jump_available=bool(jump and self.enabled(image))
        if jump:return self.jump_available,score
        return self.persistent.read(image)

    def read(self,image):
        hud,score=self.hud.read(image)
        self.features=self.extract(image,(0,0),self.root)
        support=self.features.get('hud_count',0)>=3 or self.features.get('world_support',0)>=2
        enabled=self.enabled(image)
        blockers=[k for k in self.BLOCKERS if self.features.get(k)]
        self.jump_available=bool(hud and enabled)
        persistent=False;persistent_score=0.
        if not hud and hasattr(self,'persistent'):persistent,persistent_score=self.persistent.read(image)
        # No jump button (e.g. swimming) needs independent world controls as
        # well as the minimap rim; a missing button alone grants no permission.
        no_jump_world=persistent and self.features.get('hud_count',0)>=3 and self.features.get('world_support',0)>=1
        self.diagnostics=dict(jump_hud=bool(hud),jump_hud_state=getattr(self.hud,'state','unknown'),
                              jump_hud_score=score,
                              enabled=bool(enabled),support=bool(support),blockers=blockers,
                              persistent_world=bool(persistent),persistent_score=persistent_score,jump_available=self.jump_available)
        clear=((self.jump_available and support) or no_jump_world) and not blockers
        return bool(clear),max(score,persistent_score)

    @staticmethod
    def enabled(image):
        frame=cv2.resize(image,(1260,709))
        hsv=cv2.cvtColor(frame[500:655,1015:1185],cv2.COLOR_BGR2HSV)
        yellow=(hsv[:,:,0]>=8)&(hsv[:,:,0]<=40)&(hsv[:,:,1]>70)&(hsv[:,:,2]>150)
        return float(np.mean(yellow))>.04
