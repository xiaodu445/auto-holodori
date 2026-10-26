from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
import json

from modular_agent.core.ports import Skill


@dataclass(frozen=True)
class SkillMetadata:
    name: str
    description: str
    environments: tuple[str, ...] = ("*",)
    cost: float = 0.0
    latency_ms: int = 0
    reliability: float = 0.5
    enabled: bool = True
    tags: tuple[str, ...] = ()


@dataclass
class RegisteredSkill:
    metadata: SkillMetadata
    implementation: Skill


class SkillRegistry:
    """The single source of truth for callable capabilities."""

    def __init__(self) -> None:
        self._skills: dict[str, RegisteredSkill] = {}

    def register(self, metadata: SkillMetadata, implementation: Skill) -> None:
        if metadata.name != implementation.name:
            raise ValueError("metadata.name must match implementation.name")
        self._skills[metadata.name] = RegisteredSkill(metadata, implementation)

    def candidates(self, environment: str) -> list[RegisteredSkill]:
        return [
            item for item in self._skills.values()
            if item.metadata.enabled
            and ("*" in item.metadata.environments or environment in item.metadata.environments)
        ]

    def get(self, name: str) -> RegisteredSkill:
        return self._skills[name]

    def export_manifest(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(item.metadata) for item in self._skills.values()]
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

