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
        """Return the shared singleton instance — for inspection only.

        Do NOT pass this to AgentHarness or write per-run state to it
        (``skill.artifacts = X``). Two concurrent harness runs would clobber
        each other's facades. Use ``create()`` for that.
        """
        if name not in self._entries:
            raise KeyError(f"Unknown skill: {name}")
        return self._entries[name].skill

    def create(self, name: str) -> BaseAgent:
        """Return a fresh instance suitable for one harness run.

        Concurrency-safety: harness writes per-run state onto the skill
        instance (``self.artifacts`` / ``self.sources`` / ``self._tool_executor``
        / ``self.as_of`` / ``self.model``). With the registry holding a
        singleton, two concurrent runs would race those writes — observed
        in production as TSLA + NVDA parallel runs producing TSLA gates but
        NVDA-themed synthesis (the later harness rebound ``self.artifacts``
        mid-execution of the earlier one).

        Implementation: re-instantiate via the singleton's class with no
        args. All current skills accept ``__init__(self, model=None)`` and
        the heavy load (``load_skill_prompt`` is lru-cached) so the per-run
        cost is microseconds.
        """
        if name not in self._entries:
            raise KeyError(f"Unknown skill: {name}")
        cls = type(self._entries[name].skill)
        return cls()

    def entry(self, name: str) -> SkillEntry:
        if name not in self._entries:
            raise KeyError(f"Unknown skill: {name}")
        return self._entries[name]

    def list(self) -> list[dict[str, Any]]:
        return [e.to_dict() for e in self._entries.values()]

    def names(self) -> list[str]:
        return list(self._entries.keys())


default_skills = SkillRegistry()
