from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import uuid4


class Outcome(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class BoundingBox:
    left: int
    top: int
    right: int
    bottom: int


@dataclass
class State:
    """A structured observation. Raw pixels belong in perception, not here."""

    environment: str
    facts: dict[str, Any] = field(default_factory=dict)
    ocr_text: list[str] = field(default_factory=list)
    objects: dict[str, BoundingBox] = field(default_factory=dict)
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True)
class Action:
    name: str
    target: str | None = None
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResult:
    outcome: Outcome
    data: dict[str, Any] = field(default_factory=dict)
    message: str = ""


@dataclass
class Experience:
    goal: str
    environment: str
    skill_name: str
    outcome: Outcome
    summary: str
    reusable: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid4()))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

