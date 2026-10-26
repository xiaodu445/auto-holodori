from __future__ import annotations

from dataclasses import dataclass

from modular_agent.core.models import State
from .registry import RegisteredSkill, SkillRegistry


@dataclass(frozen=True)
class RouteDecision:
    skill: RegisteredSkill | None
    confidence: float
    reason: str


class SkillRouter:
    """Deterministic, inspectable first-tier router.

    A future small model can implement the same `route` contract.
    """

    def __init__(self, registry: SkillRegistry) -> None:
        self._registry = registry

    def route(self, state: State, intent: str = "") -> RouteDecision:
        options = [item for item in self._registry.candidates(state.environment)
                   if item.implementation.can_handle(state)]
        if not options:
            return RouteDecision(None, 0.0, "No registered skill can handle this state")

        intent_words = set(intent.lower().replace("_", " ").split())
        def score(item: RegisteredSkill) -> tuple[float, float, float]:
            haystack = f"{item.metadata.name} {item.metadata.description} {' '.join(item.metadata.tags)}".lower()
            overlap = sum(word in haystack for word in intent_words)
            return (item.metadata.reliability + overlap * 0.1, -item.metadata.cost, -item.metadata.latency_ms)

        best = max(options, key=score)
        return RouteDecision(best, min(1.0, score(best)[0]), "Highest reliability/cost/intent score")

