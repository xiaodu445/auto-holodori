from modular_agent.core.models import Action, Outcome, SkillResult


class DryRunComputer:
    """Safe default computer gateway. It records intent but never controls the PC."""

    def perform(self, action: Action) -> SkillResult:
        return SkillResult(Outcome.SUCCESS, {"action": action.name, "dry_run": True}, "Action simulated")

