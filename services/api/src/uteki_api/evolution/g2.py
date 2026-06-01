"""G2 decision driver — the human-decided endgame of the self-evolution loop.

After A/B (M1.7) writes ab_summary onto the proposal, the operator
chooses one of three terminal verdicts (per design/02 §V G2):

- ``adopted``        — keep the proposed prompt. No file changes; the
                       live SKILL.md already holds it. Pure transition.
- ``rolled_back``    — revert: write snapshot/skill/SKILL.md back to
                       live, reload, record a fresh SkillVersion noting
                       the rollback. The previous (apply-time) version
                       stays in EvolutionStore for audit but the live
                       signature now matches the baseline again.
- ``inconclusive``   — A/B couldn't decide. No file changes. Operator
                       intentionally parks the proposal; M1.8 will not
                       move it further.

All three are terminal (per the state machine in models.py) — no further
transitions allowed once entered.

Rollback intentionally records a NEW SkillVersion in EvolutionStore with
the baseline prompt rather than "popping" the apply-time version. The
audit narrative reads forward in time: v1 (initial) → v2 (apply P-001) →
v3 (rollback P-001 → baseline content). ``params`` carries
``rolled_back_from`` / ``baseline_signature`` so listing skill versions
shows the rollback story explicitly.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from uteki_api.evolution import (
    SkillVersion,
    compute_changelog,
    default_evolution_store,
)
from uteki_api.evolution.apply import (
    _default_skill_root,
    _live_signature,
    _next_version_id,
    _reload_skill_prompt,
)
from uteki_api.evolution.proposals import default_proposal_store
from uteki_api.skills import default_skills
from uteki_api.skills.loader import load_skill_prompt

if TYPE_CHECKING:
    from uteki_api.evolution.proposals.store import ProposalStore
    from uteki_api.evolution.store import EvolutionStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class G2Result:
    proposal_id: str
    ok: bool
    final_status: str  # "adopted" / "rolled_back" / "inconclusive"
    new_version: str | None = None
    live_signature: str | None = None
    duration_s: float = 0.0
    error: str | None = None


# ── Helpers ────────────────────────────────────────────────────────


def _require_ab_eval_with_summary(
    pstore: ProposalStore, proposal_id: str, *, verb: str
) -> Any:
    """G2 entry guard: proposal must be at ``a_b_eval`` AND have
    ``ab_summary`` populated (otherwise the operator hasn't seen A/B data
    yet and can't make an informed choice).

    ``inconclusive`` could in principle be invoked without ab_summary
    (operator giving up before A/B completes) but in practice the right
    answer there is to leave the proposal where it is; we keep the
    guard uniform.
    """
    proposal = pstore.get(proposal_id)
    if proposal.status != "a_b_eval":
        raise ValueError(
            f"{verb}: proposal {proposal_id} is {proposal.status}, "
            "expected a_b_eval"
        )
    if not proposal.ab_summary:
        raise ValueError(
            f"{verb}: proposal {proposal_id} has no ab_summary yet; "
            "run `proposals ab-eval` first or use --force (not in MVP)"
        )
    return proposal


async def _record_rollback_version(
    skill_name: str,
    *,
    evolution_store: EvolutionStore,
    proposal_id: str,
    rolled_back_from_signature: str | None,
    baseline_signature: str,
) -> SkillVersion:
    """Append a SkillVersion reflecting the post-rollback live prompt.

    Same shape as apply._record_skill_version but stamps
    ``params.rolled_back_from`` / ``params.baseline_signature`` so the
    history explicitly says 'this version is a rollback of P-XXX'.
    """
    skill = default_skills.get(skill_name)
    sig = skill.current_signature() or {}
    prompt_text, _refs = load_skill_prompt(skill_name)
    sig = {
        "prompt": sig.get("prompt") or prompt_text,
        "tool_names": list(sig.get("tool_names") or getattr(skill, "DEFAULT_TOOLS", [])),
        "model": str(sig.get("model") or getattr(skill, "DEFAULT_MODEL", "") or ""),
        "params": {
            **(sig.get("params") or {}),
            "rolled_back_from": proposal_id,
            "rolled_back_from_signature": rolled_back_from_signature,
            "baseline_signature": baseline_signature,
        },
    }
    prev = await evolution_store.latest(skill_name)
    new_id = _next_version_id(prev.version if prev else None)
    version = SkillVersion(
        skill=skill_name,
        version=new_id,
        prompt=sig["prompt"],
        tool_names=sig["tool_names"],
        model=sig["model"],
        params=sig["params"],
        created_at=time.time(),
        parent_version=prev.version if prev else None,
        changelog=compute_changelog(prev, sig),
    )
    await evolution_store.record(version)
    return version


# ── Public entry points ────────────────────────────────────────────


async def adopt_proposal(
    proposal_id: str,
    *,
    by: str,
    reason: str = "",
    store: ProposalStore | None = None,
) -> G2Result:
    """G2: adopt the proposed prompt. Terminal transition only.

    No file changes — apply.py already left the proposed prompt on disk
    and A/B confirmed it. The SkillVersion recorded at apply time is
    therefore the canonical 'adopted' version; this just stamps the
    proposal state to terminal so it stops showing up in pending lists.
    """
    pstore = store or default_proposal_store
    started = time.time()
    proposal = _require_ab_eval_with_summary(pstore, proposal_id, verb="adopt")

    pstore.transition(
        proposal_id,
        "adopted",
        by=by,
        reason=reason,
        extra={"applied_signature": proposal.applied_skill_signature},
    )
    logger.info("adopted %s by=%s", proposal_id, by)
    return G2Result(
        proposal_id=proposal_id,
        ok=True,
        final_status="adopted",
        new_version=None,  # apply-time version remains the live one
        live_signature=proposal.applied_skill_signature,
        duration_s=time.time() - started,
    )


async def inconclusive_proposal(
    proposal_id: str,
    *,
    by: str,
    reason: str = "",
    store: ProposalStore | None = None,
) -> G2Result:
    """G2: park the proposal as inconclusive. Terminal transition only.

    Notably this LEAVES the proposed prompt live (apply already wrote it).
    If the operator's intent is 'A/B was inconclusive AND I don't trust
    the proposed prompt', they should rollback instead.
    """
    pstore = store or default_proposal_store
    started = time.time()
    proposal = _require_ab_eval_with_summary(pstore, proposal_id, verb="inconclusive")

    pstore.transition(
        proposal_id,
        "inconclusive",
        by=by,
        reason=reason,
        extra={"applied_signature": proposal.applied_skill_signature},
    )
    logger.info("inconclusive %s by=%s reason=%s", proposal_id, by, reason)
    return G2Result(
        proposal_id=proposal_id,
        ok=True,
        final_status="inconclusive",
        new_version=None,
        live_signature=proposal.applied_skill_signature,
        duration_s=time.time() - started,
    )


async def rollback_proposal(
    proposal_id: str,
    *,
    by: str,
    reason: str = "",
    store: ProposalStore | None = None,
    evolution_store: EvolutionStore | None = None,
    skill_root: Path | None = None,
) -> G2Result:
    """G2: revert the live SKILL.md to the snapshotted baseline.

    Mirrors apply.py's mutation step but in reverse: snapshot/skill/SKILL.md
    overwrites the live file, the skill cache is invalidated + reloaded,
    a fresh SkillVersion is recorded (stamped with rolled_back_from), and
    Proposal.applied_skill_signature is updated to the baseline signature.

    Final transition: a_b_eval → rolled_back (terminal).

    Safety: rollback is best-effort idempotent — if the live file already
    matches the snapshot (operator manually reverted earlier), the file
    write is a no-op but the SkillVersion + transition still happen so
    the audit is uniform.
    """
    pstore = store or default_proposal_store
    estore = evolution_store or default_evolution_store
    sroot = skill_root or _default_skill_root()
    started = time.time()

    proposal = _require_ab_eval_with_summary(pstore, proposal_id, verb="rollback")

    proposal_dir = pstore._dir(proposal_id)  # noqa: SLF001
    snapshot_skill_md = proposal_dir / "snapshot" / "skill" / "SKILL.md"
    live_skill_md = sroot / proposal.source_skill / "SKILL.md"
    if not snapshot_skill_md.exists():
        raise ValueError(
            f"rollback: missing baseline at {snapshot_skill_md} — "
            "cannot revert without the snapshot"
        )
    if not live_skill_md.exists():
        raise ValueError(
            f"rollback: missing live skill at {live_skill_md} — "
            "skill folder went missing between apply and rollback"
        )

    # Capture the pre-rollback signature for the audit stamp.
    rolled_back_from_sig = proposal.applied_skill_signature or _live_signature(
        proposal.source_skill
    )

    # Revert + reload (this IS the rollback).
    baseline_text = snapshot_skill_md.read_text(encoding="utf-8")
    live_skill_md.write_text(baseline_text, encoding="utf-8")
    _reload_skill_prompt(proposal.source_skill)
    baseline_sig = _live_signature(proposal.source_skill)

    # Record the rollback as a new SkillVersion so the audit narrative
    # reads forward in time.
    version = await _record_rollback_version(
        proposal.source_skill,
        evolution_store=estore,
        proposal_id=proposal_id,
        rolled_back_from_signature=rolled_back_from_sig,
        baseline_signature=baseline_sig,
    )

    # Stamp the proposal so /show + audit reflect the rollback.
    proposal = pstore.get(proposal_id)
    proposal.applied_skill_signature = baseline_sig
    pstore._persist(proposal)  # noqa: SLF001

    pstore.transition(
        proposal_id,
        "rolled_back",
        by=by,
        reason=reason,
        extra={
            "new_version": version.version,
            "rolled_back_from_signature": rolled_back_from_sig,
            "baseline_signature": baseline_sig,
        },
    )
    logger.info(
        "rolled_back %s: sig %s -> %s, new_version=%s by=%s",
        proposal_id, rolled_back_from_sig, baseline_sig, version.version, by,
    )
    return G2Result(
        proposal_id=proposal_id,
        ok=True,
        final_status="rolled_back",
        new_version=version.version,
        live_signature=baseline_sig,
        duration_s=time.time() - started,
    )


__all__ = [
    "G2Result",
    "adopt_proposal",
    "inconclusive_proposal",
    "rollback_proposal",
]
