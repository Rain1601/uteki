"""Self-evolution proposals — first-class artifacts in the loop.

A Proposal is the audit record of one round of:
    drift / manual trigger → CC review → operator G1 → apply → A/B → G2

Each proposal lives on disk under ``data/evolution/proposals/<P-id>/``
so its meta.json + decisions/ trail survives crashes and is grep-able
in git diff style. See ``design/02-self-evolution-loop.md`` for the
state machine and ``design/proposals-archive/2026-05-26-001-research-
scratchpad/`` for the first hand-driven example.

This module (M1 phase) implements only the bookkeeping layer — the
data model + filesystem store + state transitions. CC spawning,
patch application, A/B eval wiring come in M1.2-M1.8.
"""

from __future__ import annotations

from uteki_api.evolution.proposals.models import (
    Proposal,
    ProposalStatus,
    TerminalStatus,
)
from uteki_api.evolution.proposals.store import ProposalStore, default_proposal_store

__all__ = [
    "Proposal",
    "ProposalStatus",
    "TerminalStatus",
    "ProposalStore",
    "default_proposal_store",
]
