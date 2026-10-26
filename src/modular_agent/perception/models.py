from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class VisionDetection:
    template_id: str
    label: str
    confidence: float
    bbox: tuple[int, int, int, int]
    environment: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CapturedFrame:
    width: int
    height: int
    monitor: int
    left: int = 0
    top: int = 0
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))
