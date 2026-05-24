"""Skill prompt loader.

Composes the final system prompt that the LLM sees, in stable order:

    1. _shared/guardrails.md       (always; defines cite-or-flag etc.)
    2. <skill>/SKILL.md            (the forked agent prompt)
    3. <skill>/references/*.md     (sorted by filename, sub-skill detail)
    4. _shared/addendum_zh.md      (zh-CN output convention)

Why this order:
- Guardrails first → can't be drowned out by lengthy upstream prose.
- Skill prompt + references in the middle → form the working "core".
- Addendum last → final-mile reminder right before user turn.

The composed text is hashed to a stable signature; `BaseAgent.current_signature`
includes it so the evolution store auto-bumps the version when any of the
underlying markdown files change. No need to edit Python on a prompt tweak.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path

_SKILLS_ROOT = Path(__file__).resolve().parent
_SHARED = _SKILLS_ROOT / "_shared"


def _read_text(path: Path) -> str:
    """Read UTF-8 text; missing → empty string (so partial setup is non-fatal)."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""


@lru_cache(maxsize=32)
def load_skill_prompt(skill_name: str) -> tuple[str, tuple[str, ...]]:
    """Return ``(system_prompt, references_used)`` for the named skill.

    ``references_used`` is the list of reference filenames that contributed
    (useful for the frontend to show "this run consulted X.md"). The result
    is cached — call ``load_skill_prompt.cache_clear()`` in tests if you edit
    the markdown live.
    """
    skill_dir = _SKILLS_ROOT / skill_name
    if not skill_dir.is_dir():
        raise FileNotFoundError(f"Skill directory not found: {skill_dir}")

    parts: list[str] = []
    refs: list[str] = []

    guardrails = _read_text(_SHARED / "guardrails.md")
    if guardrails:
        parts.append(guardrails)

    main = _read_text(skill_dir / "SKILL.md")
    if main:
        parts.append(main)

    refs_dir = skill_dir / "references"
    if refs_dir.is_dir():
        for ref in sorted(refs_dir.glob("*.md")):
            content = _read_text(ref)
            if content:
                parts.append(f"<!-- reference: {ref.name} -->\n{content}")
                refs.append(ref.name)

    addendum = _read_text(_SHARED / "addendum_zh.md")
    if addendum:
        parts.append(addendum)

    composed = "\n\n---\n\n".join(parts)
    return composed, tuple(refs)


def compute_signature(text: str) -> str:
    """12-char SHA-256 prefix. Used as the ``prompt`` field of skill signature."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
