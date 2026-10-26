from __future__ import annotations

from typing import Protocol

from .models import Action, Experience, SkillResult, State


class Observer(Protocol):
    def observe(self) -> State: ...


class Skill(Protocol):
    name: str

    def can_handle(self, state: State) -> bool: ...

    def execute(self, state: State) -> SkillResult: ...

    def verify(self, before: State, result: SkillResult, after: State) -> bool: ...


class MemoryStore(Protocol):
    def retrieve(self, query: str, environment: str, limit: int = 5) -> list[str]: ...

    def record(self, experience: Experience) -> None: ...


class ComputerGateway(Protocol):
    def perform(self, action: Action) -> SkillResult: ...

