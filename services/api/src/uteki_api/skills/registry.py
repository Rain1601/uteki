"""Skill registry — discoverable catalog of named agents.

Each entry binds a `BaseAgent` instance to metadata (description, version,
default tools, default model). The API layer reads from this registry to list
skills, look one up by name, or fetch its current evolution version.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from uteki_api.agents.base import BaseAgent

SkillKind = Literal["skill", "pipeline"]


@dataclass
class SkillEntry:
    skill: BaseAgent
    description: str
    version: str
    default_tools: list[str] = field(default_factory=list)
    default_model: str = ""
    # M6: distinguishes leaf skills from meta-skills that delegate to others.
    # The frontend can hide pipeline entries from a "raw skill" picker, or
    # render them with a different icon.
    kind: SkillKind = "skill"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.skill.name,
            "description": self.description,
            "version": self.version,
            "default_tools": list(self.default_tools),
            "default_model": self.default_model,
            "kind": self.kind,
        }


class SkillRegistry:
    """Container of skills keyed by `BaseAgent.name`."""

    def __init__(self) -> None:
        self._entries: dict[str, SkillEntry] = {}

    def register(
        self,
        skill: BaseAgent,
        *,
        description: str,
        version: str,
        default_tools: list[str] | None = None,
        default_model: str = "",
        kind: SkillKind = "skill",
    ) -> None:
        self._entries[skill.name] = SkillEntry(
            skill=skill,
            description=description,
            version=version,
            default_tools=list(default_tools or []),
            default_model=default_model,
            kind=kind,
        )

    def get(self, name: str) -> BaseAgent:
        if name not in self._entries:
            raise KeyError(f"Unknown skill: {name}")
        return self._entries[name].skill

    def entry(self, name: str) -> SkillEntry:
        if name not in self._entries:
            raise KeyError(f"Unknown skill: {name}")
        return self._entries[name]

    def list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._entries.values()]

    def names(self) -> list[str]:
        return list(self._entries.keys())


default_skills = SkillRegistry()
