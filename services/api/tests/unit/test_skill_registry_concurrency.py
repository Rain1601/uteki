"""SkillRegistry.create() concurrency-safety contract.

Background: skills are registered as singleton instances in
``skills/__init__.py`` (``_research = ResearchAgent()`` etc.). The harness
writes per-run state onto the instance (``skill.artifacts = ...`` /
``skill.sources = ...`` / ``skill._tool_executor = ...`` / ``skill.as_of = ...``
/ ``skill.model = ...``). With concurrent runs all using ``default_skills.get()``,
the later harness rebinds those attributes mid-execution of the earlier one,
producing observed cross-contamination: TSLA + NVDA parallel runs wrote TSLA
gate files but NVDA-themed synthesis (final-report.md titled "NVDA Investment
Memo" in TSLA's artifact directory).

These tests pin the fix: ``default_skills.create(name)`` must return a fresh
instance every call, so concurrent harness invocations have isolated per-run
state.
"""

from __future__ import annotations

import pytest

from uteki_api.skills import default_skills


def test_create_returns_distinct_instances() -> None:
    a = default_skills.create("research")
    b = default_skills.create("research")
    assert a is not b, "create() must return a fresh instance per call"


def test_create_isolates_per_run_state() -> None:
    """Simulate the harness pattern: write per-run state onto two instances.

    The two writes must not see each other (the bug they fix would be
    a.artifacts and b.artifacts pointing at the same object after the
    second assignment because they were the same instance).
    """
    sentinel_a = object()
    sentinel_b = object()

    a = default_skills.create("research")
    b = default_skills.create("research")

    a.artifacts = sentinel_a  # type: ignore[assignment]
    b.artifacts = sentinel_b  # type: ignore[assignment]

    assert a.artifacts is sentinel_a
    assert b.artifacts is sentinel_b
    assert a.artifacts is not b.artifacts


def test_create_isolates_company_pipeline_per_run_state() -> None:
    """Same isolation must hold for company_research_pipeline — the skill
    that actually showed the TSLA/NVDA contamination in production."""
    sentinel_a = object()
    sentinel_b = object()

    a = default_skills.create("company_research_pipeline")
    b = default_skills.create("company_research_pipeline")

    a.artifacts = sentinel_a  # type: ignore[assignment]
    b.artifacts = sentinel_b  # type: ignore[assignment]

    assert a is not b
    assert a.artifacts is sentinel_a
    assert b.artifacts is sentinel_b


def test_get_still_returns_singleton_for_inspection() -> None:
    """get() is the read-only inspection path used by /admin/reload-skills and
    /api/skills (the registry-as-catalog). Must remain stable so identity
    checks like "did this skill's prompt change" keep working."""
    a = default_skills.get("research")
    b = default_skills.get("research")
    assert a is b, "get() must return the registered singleton (for inspection)"


def test_create_unknown_skill_raises_keyerror() -> None:
    with pytest.raises(KeyError):
        default_skills.create("nonexistent_skill_zzz")
