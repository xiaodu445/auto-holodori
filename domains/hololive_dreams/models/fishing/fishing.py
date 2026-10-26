"""Domain state machine; recognition and controller are separate modules."""
import importlib.util
from pathlib import Path

def _sibling(name):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(name+'.py'))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

FishingVision=_sibling('fishing_vision').FishingVision
FishingController=_sibling('fishing_controller').FishingController

class FishingProgram:
    def __init__(self, config, vision):
        self.config,self.vision=config,vision
        self.controller=FishingController(config)
        self.state=config['start_phase']
        self.last_seen=None
        self.bite_count=0
        self.started=None
    def roi(self): return self.config['control_roi'] if self.state in ('control','hook') else self.config['bite_roi']
    def reset_motion(self): self.controller.reset()
    def detect(self,image): return self.vision.control(image) if self.state in ('control','hook') else self.vision.bite(image)
    def step(self, observation, now, down):
        if self.started is None: self.started=now
        if self.state=='waiting':
            self.bite_count=self.bite_count+1 if observation.get('bite') else 0
            if self.bite_count>=self.config['bite_stable_frames']:
                self.state='hook'; self.started=now
                return dict(down=True,force=True)
            return dict(down=False)
        if self.state=='hook':
            # One press/release; no repeated clicking while transition is pending.
            if now-self.started < self.config['hook_press_seconds']: return dict(down=True)
            if observation.get('valid'):
                self.state='control'; self.reset_motion(); self.last_seen=now
                return dict(down=False,force=True)
            if now-self.started>self.config['hook_timeout']: return dict(down=False,force=True,stop='hook_transition_unknown')
            return dict(down=False,force=True)
        if observation.get('valid'):
            if self.last_seen is not None and now-self.last_seen>self.config['short_loss_seconds']: self.reset_motion()
            self.last_seen=now
            return self.controller.decide(observation,now,down)
        age=now-(self.last_seen if self.last_seen is not None else self.started)
        if age>self.config['long_loss_seconds']:
            return dict(down=False,force=True,stop='track_lost_result_pending')
        return dict(down=down if age<=self.config['short_loss_seconds'] else False,force=True)

