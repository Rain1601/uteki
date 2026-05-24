"""Verifier functions used by the Evaluator skill.

All verifiers are **async** (M7) so that ``llm_judge_score`` can call an LLM
without forcing every call site to special-case awaitables. The pure-Python
ones (regex / tool_call / numeric_in_range) don't await anything but their
signatures match so the dispatch table is uniform.

Each returns ``(passed: bool, notes: str)``. ``llm_judge_score`` returns a
third element — the full ``JudgeScore`` — so the evaluator can persist a
``judge-{rubric}.json`` artifact with the LLM's rationale.
"""

from __future__ import annotations

import re
from typing import Any

from uteki_api.eval.judges.runner import JudgeScore, default_judge_runner


async def regex_in_text(pattern: str, target: str) -> tuple[bool, str]:
    """Pass iff ``re.search(pattern, target, IGNORECASE)`` finds a match.

    Returns the first 3 matched strings in ``notes`` for traceability.
    """
    if not pattern:
        return False, "empty pattern"
    try:
        compiled = re.compile(pattern, flags=re.IGNORECASE)
    except re.error as e:
        return False, f"invalid regex: {e}"
    matches = compiled.findall(target or "")
    if not matches:
        return False, f"no match for pattern {pattern!r}"
    flat: list[str] = []
    for m in matches:
        if isinstance(m, tuple):
            flat.append("|".join(str(x) for x in m if x))
        else:
            flat.append(str(m))
    sample = ", ".join(flat[:3])
    return True, f"matched {len(flat)} occurrence(s); sample: {sample}"


async def tool_call_in_run(
    tool_name: str,
    run_events: list[dict[str, Any]],
) -> tuple[bool, str]:
    """Pass iff any event has ``type == 'tool_call'`` and ``data.name == tool_name``."""
    if not tool_name:
        return False, "empty tool_name"
    count = 0
    for ev in run_events or []:
        if not isinstance(ev, dict):
            continue
        if ev.get("type") != "tool_call":
            continue
        data = ev.get("data") or {}
        if isinstance(data, dict) and data.get("name") == tool_name:
            count += 1
    if count == 0:
        return False, f"no tool_call event for {tool_name!r}"
    return True, f"{count} tool_call event(s) for {tool_name!r}"


async def numeric_in_range(
    name: str,
    lo: float,
    hi: float,
    target: str,
) -> tuple[bool, str]:
    """Pass iff a number appears near ``name`` in ``target`` and is in [lo, hi]."""
    if not name or hi < lo:
        return False, "invalid args"
    label_re = re.compile(re.escape(name), flags=re.IGNORECASE)
    m = label_re.search(target or "")
    if m is None:
        return False, f"label {name!r} not found in draft"
    window = (target or "")[m.end() : m.end() + 80]
    num_match = re.search(r"-?\d+(?:\.\d+)?", window)
    if num_match is None:
        return False, f"no number found within 80 chars after {name!r}"
    try:
        val = float(num_match.group(0))
    except ValueError:
        return False, f"failed to parse number {num_match.group(0)!r}"
    if val < lo or val > hi:
        return False, f"value {val} outside [{lo}, {hi}]"
    return True, f"value {val} in [{lo}, {hi}]"


async def llm_judge_score(
    rubric_name: str,
    target: str,
    *,
    run_events: list[dict[str, Any]] | None = None,
    avoid_model: str | None = None,
) -> tuple[bool, str, JudgeScore]:
    """Score ``target`` against a rubric via LLM. Returns also the full JudgeScore.

    The third return slot carries the rich ``JudgeScore`` so the evaluator
    can persist a ``judge-{rubric}.json`` artifact with the full rationale.
    Pure-Python verifiers don't have this third payload — the evaluator
    branches on the verifier name when handling its return.
    """
    judge = await default_judge_runner.judge(
        rubric_name,
        target,
        run_events or [],
        avoid_model=avoid_model,
    )
    passed = judge.score_1_to_10 >= judge.pass_threshold
    notes = (
        f"judge {judge.rubric}={judge.score_1_to_10}/10 "
        f"(threshold {judge.pass_threshold}, by {judge.judge_model}): "
        f"{judge.rationale[:120]}"
    )
    return passed, notes, judge


# Dispatch table — name → callable. The evaluator skill walks the contract's
# acceptance_criteria and looks up the verifier by string name.
VERIFIERS = {
    "regex_in_text": regex_in_text,
    "tool_call_in_run": tool_call_in_run,
    "numeric_in_range": numeric_in_range,
    "llm_judge_score": llm_judge_score,
}
