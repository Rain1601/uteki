"""EvolutionStore — append-only history of `SkillVersion`s per skill.

Used by the app lifespan to seed/bump versions on startup, and by the API to
expose `/api/agents/{name}/versions`. Default impl is in-memory; swap with a
DB-backed implementation in production.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from uteki_api.evolution.versions import SkillVersion


class EvolutionStore(ABC):
    @abstractmethod
    async def latest(self, skill: str) -> SkillVersion | None: ...

    @abstractmethod
    async def record(self, version: SkillVersion) -> None: ...

    @abstractmethod
    async def list(self, skill: str, limit: int = 20) -> list[SkillVersion]: ...


class InMemoryEvolutionStore(EvolutionStore):
    def __init__(self) -> None:
        # Per-skill, oldest-first.
        self._versions: dict[str, list[SkillVersion]] = {}

    async def latest(self, skill: str) -> SkillVersion | None:
        items = self._versions.get(skill)
        if not items:
            return None
        return items[-1]

    async def record(self, version: SkillVersion) -> None:
        self._versions.setdefault(version.skill, []).append(version)

    async def list(self, skill: str, limit: int = 20) -> list[SkillVersion]:
        items = list(reversed(self._versions.get(skill, [])))
        return items[:limit]


default_evolution_store: EvolutionStore = InMemoryEvolutionStore()
