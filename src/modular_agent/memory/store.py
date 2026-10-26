from __future__ import annotations

from pathlib import Path
import re

from modular_agent.core.models import Experience


class MarkdownMemoryStore:
    """Human-reviewable long-term memory; raw execution traces stay out of it."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "discoveries").mkdir(exist_ok=True)
        (self.root / "failures").mkdir(exist_ok=True)

    def retrieve(self, query: str, environment: str, limit: int = 5) -> list[str]:
        terms = set(re.findall(r"\w+", query.lower()))
        candidates: list[tuple[int, Path]] = []
        for path in self.root.rglob("*.md"):
            text = path.read_text(encoding="utf-8").lower()
            environment_bonus = 3 if environment.lower() in str(path).lower() else 0
            candidates.append((sum(term in text for term in terms) + environment_bonus, path))
        ranked = sorted(candidates, key=lambda item: item[0], reverse=True)
        return [path.read_text(encoding="utf-8") for score, path in ranked if score > 0][:limit]

    def record(self, experience: Experience) -> None:
        if not experience.reusable:
            return
        safe_environment = re.sub(r"[^a-zA-Z0-9_-]+", "_", experience.environment)
        destination = self.root / "discoveries" / f"{safe_environment}.md"
        entry = (
            f"\n## {experience.created_at.date()} — {experience.skill_name}\n\n"
            f"- Goal: {experience.goal}\n"
            f"- Outcome: {experience.outcome}\n"
            f"- Reusable knowledge: {experience.summary}\n"
        )
        with destination.open("a", encoding="utf-8") as file:
            file.write(entry)
