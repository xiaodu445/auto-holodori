"""Pure patrol planning. Map pixels are coordinates, never world metres.

The controller proposes bounded pulses; a guarded executor owns input. A visited
waypoint and a dispatched pickup are deliberately not collection verification.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import heapq
import math
import numpy as np

from .interaction import RetryBudget, policy_for


@dataclass(frozen=True)
class Position:
    x: float
    y: float
    t: float
    valid: bool = True
    score: float = 0.0
    margin: float = 0.0
    scale: float = 1.0
    reason: str = ''


@dataclass(frozen=True)
class Observation:
    frame_id: int
    t: float
    position: Position | None
    free_scene: bool
    pickup_visible: bool = False
    pickup_enabled: bool = False
    blocked: bool = False
    # Must come from an independent detector; disappearance alone is not enough.
    pickup_result: bool = False


@dataclass(frozen=True)
class Decision:
    kind: str
    reason: str
    keys: tuple[str, ...] = ()
    duration: float = 0.0
    target: tuple[float, float] | None = None


@dataclass
class PatrolSettings:
    arrival_radius: float = 8.0
    max_frame_age: float = 0.5
    max_pulse: float = 0.15
    min_pulse: float = 0.025
    settle_seconds: float = 0.12
    waypoint_timeout: float = 40.0
    stuck_seconds: float = 4.0
    progress_pixels: float = 2.0
    max_run_seconds: float = 1200.0
    max_laps: int = 1
    pickup_timeout: float = 8.0

    def __post_init__(self):
        for name, value in vars(self).items():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(name)
        if self.max_pulse > .3 or self.min_pulse > self.max_pulse or type(self.max_laps) is not int:
            raise ValueError('pulse/lap bounds')


@dataclass
class MotionCalibration:
    """Independent measured map-pixel/second vectors, with a fixed camera.

    Opposite keys are measured independently: animation/acceleration and camera
    behaviour need not be symmetric. No unmeasured diagonal input is generated.
    """
    vectors: dict[str, tuple[float, float]] = field(default_factory=dict)

    def add_sample(self, key, before: Position, after: Position, held_seconds):
        if key not in ('w', 'a', 's', 'd') or not before.valid or not after.valid:
            raise ValueError('invalid calibration sample')
        if not math.isfinite(held_seconds) or not .05 <= held_seconds <= 2 or after.t <= before.t:
            raise ValueError('invalid calibration duration')
        vector = ((after.x-before.x)/held_seconds, (after.y-before.y)/held_seconds)
        if not all(math.isfinite(v) for v in vector) or math.hypot(*vector) < 2:
            raise ValueError('insufficient measured displacement')
        self.vectors[key] = vector

    def validate(self):
        if set(self.vectors) != {'w', 'a', 's', 'd'}:
            raise ValueError('all four WASD vectors must be measured')
        for vector in self.vectors.values():
            if len(vector) != 2 or not all(math.isfinite(v) for v in vector) or math.hypot(*vector) < 2:
                raise ValueError('invalid movement vector')
        # Coverage test: a camera/rotation-based mapping must not masquerade as
        # four fixed world directions. Reject a half-plane of reachable headings.
        angles = sorted(math.atan2(v[1], v[0]) % (2*math.pi) for v in self.vectors.values())
        gaps = [b-a for a,b in zip(angles, angles[1:]+[angles[0]+2*math.pi])]
        if max(gaps) >= math.pi-.05:
            raise ValueError('WASD does not cover the map plane; recalibrate camera')

    def pulse(self, delta, settings):
        self.validate()
        error = np.asarray(delta, dtype=float)
        choices = []
        for key, vector in self.vectors.items():
            velocity = np.asarray(vector, dtype=float)
            projection = float(error @ velocity / (velocity @ velocity))
            if projection <= 0:
                continue
            duration = min(settings.max_pulse, projection*.7)
            if duration < settings.min_pulse:
                continue
            remaining = float(np.linalg.norm(error-velocity*duration))
            if remaining < float(np.linalg.norm(error)):
                choices.append((remaining, key, duration))
        if not choices:
            return None
        _, key, duration = min(choices)
        return (key,), duration


def astar(mask, start, goal, *, cell=8, clearance=6):
    """Conservative 4-neighbour grid, white=walkable; no corner cutting.

    Every pixel of a grid cell must be clear. Clearance erodes the walk mask.
    Caller provides a reviewed mask: map road colours do not prove walkability.
    """
    import cv2
    if cell < 1 or clearance < 0 or mask.ndim != 2:
        raise ValueError('invalid walk mask settings')
    walk = (mask > 127).astype(np.uint8)
    if clearance:
        walk = cv2.erode(walk, np.ones((2*clearance+1,)*2, np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0)
    h,w = walk.shape
    rows,cols = h//cell,w//cell
    if not rows or not cols:
        raise ValueError('walk mask too small')
    grid = walk[:rows*cell,:cols*cell].reshape(rows,cell,cols,cell).min(axis=(1,3)).astype(bool)
    def node(point):
        x,y = point
        if not (math.isfinite(x) and math.isfinite(y) and 0 <= x < cols*cell and 0 <= y < rows*cell):
            raise ValueError('route endpoint outside mask')
        result = (int(y)//cell, int(x)//cell)
        if not grid[result]:
            raise ValueError('route endpoint is blocked')
        return result
    source,dest = node(start),node(goal)
    queue = [(0,source)];cost = {source:0};parents = {}
    while queue:
        _,current = heapq.heappop(queue)
        if current == dest:
            nodes = [dest]
            while nodes[-1] != source:
                nodes.append(parents[nodes[-1]])
            nodes.reverse()
            return [tuple(map(float,start))]+[(c*cell+cell/2,r*cell+cell/2) for r,c in nodes]+[tuple(map(float,goal))]
        for dr,dc in ((-1,0),(1,0),(0,-1),(0,1)):
            nxt = (current[0]+dr,current[1]+dc)
            if not (0 <= nxt[0] < rows and 0 <= nxt[1] < cols and grid[nxt]):
                continue
            new = cost[current]+1
            if new < cost.get(nxt,math.inf):
                cost[nxt] = new;parents[nxt] = current
                heuristic = abs(nxt[0]-dest[0])+abs(nxt[1]-dest[1])
                heapq.heappush(queue,(new+heuristic,nxt))
    raise ValueError('no walkable path')


class PatrolController:
    def __init__(self, route, calibration=None, settings=None):
        self.route = [tuple(map(float,p)) for p in route]
        if not self.route or any(len(p) != 2 or not all(math.isfinite(v) for v in p) for p in self.route):
            raise ValueError('nonempty finite route required')
        self.motion = calibration or MotionCalibration()
        self.settings = settings or PatrolSettings()
        self.index = 0;self.laps = 0;self.visits = 0
        self.start = None;self.waypoint_start = None;self.last_progress = None
        self.best_distance = math.inf;self.last_frame = -1;self.ready_after = -math.inf
        self.pickup = None;self.pickup_start = None;self.pickup_stable = 0
        self.pickup_sent = 0;self.pickup_results = 0;self.pickup_transition = False
        self.pickup_absent = 0;self.pickup_latched = False
        self.halt_reason = None

    def halt(self, reason):
        self.halt_reason = reason
        return Decision('stop',reason)

    def step(self, obs: Observation, now: float, *, cancelled=False):
        if cancelled:
            return self.halt('cancelled')
        if self.halt_reason:
            return Decision('stop',self.halt_reason)
        if self.start is None:
            self.start = now;self.waypoint_start = now;self.last_progress = now
        s = self.settings
        if now-self.start >= s.max_run_seconds:
            return self.halt('run_budget')
        if obs.frame_id <= self.last_frame or not 0 <= now-obs.t <= s.max_frame_age:
            return Decision('wait','stale_frame')
        self.last_frame = obs.frame_id
        if obs.pickup_result and self.pickup and self.pickup.attempts and not self.pickup_transition:
            self.pickup_results += 1;self.pickup_transition = True
        if obs.blocked or not obs.free_scene:
            # Once a popup/transition appears, never supplement the old E.
            if self.pickup and self.pickup.attempts:
                self.pickup_transition = True
            return Decision('wait','popup_or_unknown_scene')
        p = obs.position
        if not p or not p.valid or not 0 <= now-p.t <= s.max_frame_age:
            return Decision('wait','localization_unavailable')
        if now < self.ready_after:
            return Decision('wait','await_post_input_frame')
        # A pickup episode is latched until at least two absent fresh frames.
        if obs.pickup_visible:
            self.pickup_absent = 0
            if self.pickup_latched:
                return self.halt('pickup_prompt_persisted_after_transition')
            if self.pickup is None:
                self.pickup = RetryBudget(policy_for('patrol_pickup',retry_interval=1.5,max_attempts=3,timeout=s.pickup_timeout))
                self.pickup_start = now;self.pickup_stable = 0
            self.pickup_stable += 1
            if now-self.pickup_start >= s.pickup_timeout:
                return self.halt('pickup_unconfirmed')
            if self.pickup_transition:
                self.pickup_latched = True
                return Decision('wait','pickup_transition_no_repeat')
            if self.pickup_stable >= 2 and self.pickup.ready(now, enabled=obs.pickup_enabled):
                self.pickup.sent(now);self.pickup_sent += 1
                self.ready_after = now+.06+s.settle_seconds
                return Decision('pickup','fresh_enabled_pickup_prompt',('e',),.06)
            return Decision('wait','pickup_wait_enabled_or_retry')
        self.pickup_absent += 1
        self.pickup_stable = 0
        if self.pickup is not None or self.pickup_latched:
            if self.pickup_absent < 2:
                return Decision('wait','pickup_prompt_disappearance_unconfirmed')
            self.pickup = None;self.pickup_latched = False;self.pickup_transition = False
            self.waypoint_start = now;self.last_progress = now;self.best_distance = math.inf
        target = self.route[self.index]
        distance = math.hypot(target[0]-p.x,target[1]-p.y)
        if distance <= s.arrival_radius:
            self.visits += 1;self.index += 1
            if self.index == len(self.route):
                self.index = 0;self.laps += 1
                if self.laps >= s.max_laps:
                    return self.halt('route_traversed_collection_unverified')
            self.waypoint_start = now;self.last_progress = now;self.best_distance = math.inf
            return Decision('wait','waypoint_visited',target=target)
        if now-self.waypoint_start >= s.waypoint_timeout:
            return self.halt('waypoint_timeout')
        if distance < self.best_distance-s.progress_pixels:
            self.best_distance = distance;self.last_progress = now
        elif now-self.last_progress >= s.stuck_seconds:
            return self.halt('stuck_replan_required')
        try:
            pulse = self.motion.pulse((target[0]-p.x,target[1]-p.y),s)
        except ValueError:
            return Decision('wait','motion_calibration_required',target=target)
        if pulse is None:
            return self.halt('motion_cannot_reduce_error')
        keys,duration = pulse
        self.ready_after = now+duration+s.settle_seconds
        return Decision('move','closed_loop_map_error',keys,duration,target)

    def summary(self):
        return dict(reason=self.halt_reason,waypoints_visited=self.visits,laps=self.laps,
                    pickup_inputs_proposed=self.pickup_sent,pickup_results_observed=self.pickup_results,
                    collection_verified=False)
