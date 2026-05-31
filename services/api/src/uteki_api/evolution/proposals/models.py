"""Proposal data model — the state machine vertices + transition record.

State machine (from design/02-self-evolution-loop.md §III):

    triggered → snapshotting → briefing → spawning → generating
                                                         ↓
                                                    validating
                                                  /         \\
                                              [OK]            [BAD]
                                                ↓                ↓
                                         pending_review     invalidated
                                                ↓                ↓
                                  ┌──── accepted ──┐         discarded
                                  │   rejected     │
                                  │   deferred     │
                                  │   edit_then_apply
                                  ▼
                              applying
                              /       \\
                          [OK]         [FAIL]
                            ↓              ↓
                        a_b_eval      apply_failed
                            ↓
                  ┌─── adopted ─── rolled_back ─── inconclusive

The status field is the authoritative state; ``transitions`` is the
append-only audit trail. Every transition writes a ``decisions/NNN-
<status>.json`` row so we can replay the full history.
"""

from __future__ import annotations

import time
from typing import Any, Literal

from pydantic import BaseModel, Field

ProposalStatus = Literal[
    # Pipeline phase (automated)
    "triggered",
    "snapshotting",
    "briefing",
    "spawning",
    "generating",
    "validating",
    "invalidated",
    # G1 phase (human)
    "pending_review",
    "accepted",
    "rejected",
    "deferred",
    "edit_then_apply",
    "discarded",
    # Apply phase (automated)
    "applying",
    "apply_failed",
    # A/B phase (automated → human decision)
    "a_b_eval",
    # G2 phase (human)
    "adopted",
    "rolled_back",
    "inconclusive",
]

# Statuses where the proposal is "done" — no further transitions allowed.
TerminalStatus = {
    "discarded",
    "rejected",
    "deferred",  # can be re-triggered but as a fresh proposal
    "adopted",
    "rolled_back",
    "inconclusive",
    "invalidated",  # terminal because the CC output was bad; need fresh trigger
    "apply_failed",  # terminal until human investigates
}


class Transition(BaseModel):
    """One state-machine edge fire. Append-only."""

    to: ProposalStatus
    ts: float = Field(default_factory=time.time)
    # "system:drift_monitor" / "system:manual" / "user:<user_id>" / "system:cc_subprocess"
    by: str
    # Free-form context — reason text for rejects, exit code for CC, etc.
    reason: str = ""
    extra: dict[str, Any] = Field(default_factory=dict)


class Proposal(BaseModel):
    """One proposal record. Lives on disk as
    ``data/evolution/proposals/<id>/meta.json``."""

    proposal_id: str  # "P-2026-001"
    status: ProposalStatus = "triggered"

    # What this proposal is about
    source_skill: str
    source_run_id: str
    # M4 multi-tenant — owner of the run that triggered this. Operators
    # see all proposals (admin scope); users see only their own.
    source_user_id: str

    # State machine timestamps
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)

    # Audit trail — every transition appends
    transitions: list[Transition] = Field(default_factory=list)

    # Snapshot reference (set when snapshotting completes)
    snapshot_skill_signature: str | None = None

    # Set when apply completes
    applied_skill_signature: str | None = None

    # Set when a_b_eval completes
    ab_summary: dict[str, Any] | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TerminalStatus
