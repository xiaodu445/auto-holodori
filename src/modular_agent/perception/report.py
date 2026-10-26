"""Structured local perception output. All rectangles use desktop physical pixels."""
from dataclasses import asdict, dataclass, field
from datetime import datetime, UTC
from typing import Any

@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    width: int
    height: int

    @classmethod
    def from_bbox(cls, bbox):
        left, top, right, bottom = map(int, bbox)
        return cls(left, top, max(0, right-left), max(0, bottom-top))

    def to_dict(self):
        return {**asdict(self), 'bbox': [self.x, self.y, self.x+self.width, self.y+self.height]}

    @property
    def area(self): return self.width*self.height

    def intersection(self, other):
        return Rect.from_bbox((max(self.x,other.x), max(self.y,other.y),
            max(max(self.x,other.x),min(self.x+self.width,other.x+other.width)),
            max(max(self.y,other.y),min(self.y+self.height,other.y+other.height))))

    def iou(self, other):
        area=self.intersection(other).area
        return area/max(1,self.area+other.area-area)

@dataclass
class ScreenReport:
    frame: dict[str, Any]
    windows: list[dict] = field(default_factory=list)
    buttons: list[dict] = field(default_factory=list)
    texts: list[dict] = field(default_factory=list)
    knowledge_matches: list[dict] = field(default_factory=list)
    capabilities: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    timings_ms: dict = field(default_factory=dict)
    observed_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    def to_dict(self): return asdict(self)

    def to_state(self, environment='desktop'):
        from modular_agent.core.models import State, BoundingBox
        return State(environment=environment,
            facts={'screen': self.to_dict()},
            ocr_text=[t['text'] for t in self.texts],
            objects={item['id']: BoundingBox(*item['bounds']['bbox'])
                     for item in self.buttons+self.knowledge_matches})
