"""SkillVersion — an immutable snapshot of a skill's configuration.

Each time a skill's `current_signature()` changes (prompt, tools, model, params)
we record a new version with an auto-incremented `vN` id and a human-readable
`changelog` describing the delta from the previous version.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class SkillVersion(BaseModel):
    skill: str
    version: str
    prompt: str = ""
    tool_names: list[str] = Field(default_factory=list)
    model: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    created_at: float
    parent_version: str | None = None
    changelog: str = ""


def compute_changelog(prev: SkillVersion | None, new_fields: dict[str, Any]) -> str:
    """Return a human-readable diff between `prev` and `new_fields`.

    `new_fields` may contain `prompt`, `tool_names`, `model`, `params`.
    """
    if prev is None:
        return "first version"

    parts: list[str] = []

    new_model = new_fields.get("model", "")
    if new_model != prev.model:
        parts.append(f"model: {prev.model!r} → {new_model!r}")

    new_prompt = new_fields.get("prompt", "")
    if new_prompt != prev.prompt:
        parts.append("prompt changed")

    new_tools = list(new_fields.get("tool_names", []) or [])
    prev_tools = list(prev.tool_names)
    added = [t for t in new_tools if t not in prev_tools]
    removed = [t for t in prev_tools if t not in new_tools]
    if added:
        parts.append(f"tools added: {added}")
    if removed:
        parts.append(f"tools removed: {removed}")

    new_params = new_fields.get("params", {}) or {}
    if new_params != prev.params:
        parts.append("params changed")

    if not parts:
        return "no diff"
    return "; ".join(parts)
