from __future__ import annotations

from dataclasses import dataclass

from modular_agent.core.models import Experience, Outcome, SkillResult
from modular_agent.core.ports import MemoryStore, Observer
from modular_agent.skills.router import SkillRouter


@dataclass
class RunReport:
    outcome: Outcome
    selected_skill: str | None
    used_memory: int
    result: SkillResult
    verification_passed: bool


class AgentOrchestrator:
    """Coordinates one safe Observe → Route → Execute → Verify cycle."""

    def __init__(self, observer: Observer, router: SkillRouter, memory: MemoryStore) -> None:
        self._observer = observer
        self._router = router
        self._memory = memory

    def run_once(self, goal: str) -> RunReport:
        before = self._observer.observe()
        memories = self._memory.retrieve(goal, before.environment)
        decision = self._router.route(before, goal)
        if decision.skill is None:
            result = SkillResult(Outcome.UNKNOWN, message="Escalate to General Agent: no skill route")
            return RunReport(Outcome.UNKNOWN, None, len(memories), result, False)

        result = decision.skill.implementation.execute(before)
        after = self._observer.observe()
        verified = result.outcome == Outcome.SUCCESS and decision.skill.implementation.verify(before, result, after)
        outcome = Outcome.SUCCESS if verified else Outcome.FAILURE
        self._memory.record(Experience(
            goal=goal,
            environment=before.environment,
            skill_name=decision.skill.metadata.name,
            outcome=outcome,
            summary=result.message or f"{decision.skill.metadata.name} completed",
            reusable=verified,
        ))
        return RunReport(outcome, decision.skill.metadata.name, len(memories), result, verified)

