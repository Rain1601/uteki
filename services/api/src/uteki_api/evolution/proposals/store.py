"""ProposalStore — file-backed CRUD + state transition management.

Layout per proposal (per ``design/02-self-evolution-loop.md`` §VII):

    data/evolution/proposals/P-2026-001/
    ├── meta.json                # state machine truth (Proposal serialised)
    ├── trigger.json             # one-shot context at create time
    ├── decisions/               # append-only state transition log
    │   ├── 001-triggered.json
    │   ├── 002-snapshotting.json
    │   └── ...
    └── (other subdirs populated by later M1.x tasks:
         snapshot/, brief.md, cc_run/, validation.json, post_apply/)

Filesystem-as-DB choices:

- ``meta.json`` is rewritten atomically (``.tmp`` + ``os.replace``) on
  every transition. Crash-safe by virtue of POSIX atomic rename.
- ``decisions/`` is append-only — even after meta.json is rewritten,
  the trail is preserved as discrete files. ``git diff`` shows the
  history naturally.
- ID format ``P-<YYYY>-<NNN>``. ``NNN`` is the next free slot per-year
  by directory scan. Adequate for dev / single-process; concurrent
  multi-process writes would race — Phase 1's drift_monitor + manual
  trigger don't push that volume.

Future swap point: switch ``_root`` to a DB-backed implementation
when concurrent triggers + queryable history matter.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from uteki_api.evolution.proposals.models import (
    Proposal,
    ProposalStatus,
    Transition,
)

logger = logging.getLogger(__name__)

_ID_RE = re.compile(r"^P-(\d{4})-(\d{3})$")


class ProposalStore:
    """File-backed store. One instance per process; threadsafe-ish for
    single-writer (FastAPI request handler) workloads."""

    def __init__(self, root: Path | str = Path("data/evolution/proposals")) -> None:
        self._root = Path(root).resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    # ── ID allocation ────────────────────────────────────────────────

    def _allocate_id(self, year: int | None = None) -> str:
        """Find the next P-<YYYY>-<NNN> slot for ``year`` (defaults to now)."""
        y = year if year is not None else datetime.now(UTC).year
        prefix = f"P-{y}-"
        max_n = 0
        for entry in self._root.iterdir():
            if not entry.is_dir():
                continue
            m = _ID_RE.match(entry.name)
            if m is None:
                continue
            if int(m.group(1)) != y:
                continue
            max_n = max(max_n, int(m.group(2)))
        return f"{prefix}{max_n + 1:03d}"

    # ── Paths ────────────────────────────────────────────────────────

    def _dir(self, proposal_id: str) -> Path:
        return self._root / proposal_id

    def _meta_path(self, proposal_id: str) -> Path:
        return self._dir(proposal_id) / "meta.json"

    def _trigger_path(self, proposal_id: str) -> Path:
        return self._dir(proposal_id) / "trigger.json"

    def _decisions_dir(self, proposal_id: str) -> Path:
        return self._dir(proposal_id) / "decisions"

    # ── Atomic write helpers ─────────────────────────────────────────

    @staticmethod
    def _atomic_write(path: Path, content: str) -> None:
        """Write via .tmp + os.replace. POSIX atomic on same filesystem."""
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)

    def _persist(self, proposal: Proposal) -> None:
        """Rewrite meta.json from the proposal object."""
        self._atomic_write(
            self._meta_path(proposal.proposal_id),
            proposal.model_dump_json(indent=2),
        )

    # ── Public API ───────────────────────────────────────────────────

    def create(
        self,
        *,
        source_run_id: str,
        source_skill: str,
        source_user_id: str,
        triggered_by: str,
        trigger_reason: str = "",
    ) -> Proposal:
        """Create a new proposal with status=triggered. Persists meta.json
        + trigger.json + decisions/001-triggered.json atomically (well,
        as atomically as 3 file writes can be — order is meta last so
        a partial create won't look complete)."""
        proposal_id = self._allocate_id()
        first_transition = Transition(
            to="triggered", by=triggered_by, reason=trigger_reason
        )
        proposal = Proposal(
            proposal_id=proposal_id,
            status="triggered",
            source_skill=source_skill,
            source_run_id=source_run_id,
            source_user_id=source_user_id,
            transitions=[first_transition],
        )

        # 1. Trigger context (immutable after create)
        self._atomic_write(
            self._trigger_path(proposal_id),
            json.dumps(
                {
                    "triggered_by": triggered_by,
                    "trigger_reason": trigger_reason,
                    "source_run_id": source_run_id,
                    "source_skill": source_skill,
                    "source_user_id": source_user_id,
                    "ts": first_transition.ts,
                },
                indent=2,
            ),
        )

        # 2. First decision file
        self._write_decision(proposal_id, 1, first_transition)

        # 3. meta.json (last — readers checking existence use this)
        self._persist(proposal)

        logger.info("created proposal %s for run=%s", proposal_id, source_run_id)
        return proposal

    def get(self, proposal_id: str) -> Proposal:
        path = self._meta_path(proposal_id)
        if not path.exists():
            raise KeyError(f"unknown proposal: {proposal_id}")
        return Proposal.model_validate_json(path.read_text(encoding="utf-8"))

    def exists(self, proposal_id: str) -> bool:
        return self._meta_path(proposal_id).exists()

    def list(
        self,
        *,
        status: ProposalStatus | None = None,
        source_skill: str | None = None,
        source_user_id: str | None = None,
        limit: int = 50,
    ) -> list[Proposal]:
        """Newest-first by created_at. In-memory filter — fine for the
        v1 volume (drift triggers ~1/skill/week, single-digit pending)."""
        items: list[Proposal] = []
        for entry in self._root.iterdir():
            if not entry.is_dir():
                continue
            if _ID_RE.match(entry.name) is None:
                continue
            meta = entry / "meta.json"
            if not meta.exists():
                continue
            try:
                p = Proposal.model_validate_json(meta.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001 — corrupt row skipped
                logger.warning("skipping corrupt proposal %s", entry.name)
                continue
            if status is not None and p.status != status:
                continue
            if source_skill is not None and p.source_skill != source_skill:
                continue
            if source_user_id is not None and p.source_user_id != source_user_id:
                continue
            items.append(p)
        items.sort(key=lambda p: p.created_at, reverse=True)
        return items[:limit]

    def transition(
        self,
        proposal_id: str,
        to_status: ProposalStatus,
        *,
        by: str,
        reason: str = "",
        extra: dict[str, Any] | None = None,
    ) -> Proposal:
        """Move proposal to a new status. Idempotent on identical
        repeat-transitions? No — every call appends to the trail, even
        if status is the same. (Useful for "heartbeat" records during
        long phases like ``generating``.)

        Refuses to transition out of a terminal status — raise instead.
        """
        proposal = self.get(proposal_id)
        if proposal.is_terminal:
            raise ValueError(
                f"proposal {proposal_id} is terminal ({proposal.status}); "
                f"cannot transition to {to_status}"
            )

        new_t = Transition(to=to_status, by=by, reason=reason, extra=extra or {})
        proposal.transitions.append(new_t)
        proposal.status = to_status
        proposal.updated_at = new_t.ts

        # decisions/<NNN>-<status>.json
        self._write_decision(proposal_id, len(proposal.transitions), new_t)
        # rewrite meta.json
        self._persist(proposal)

        logger.info(
            "transition %s: %s → %s by %s",
            proposal_id, proposal.transitions[-2].to if len(proposal.transitions) > 1 else "?",
            to_status, by,
        )
        return proposal

    # ── Internal ─────────────────────────────────────────────────────

    def _write_decision(
        self,
        proposal_id: str,
        n: int,
        transition: Transition,
    ) -> None:
        path = self._decisions_dir(proposal_id) / f"{n:03d}-{transition.to}.json"
        # No atomic rename needed — these files are write-once,
        # numbered to avoid collision. Append-only by construction.
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(transition.model_dump_json(indent=2), encoding="utf-8")


# Module-level default. Tests use the same module-level singleton-rebind
# pattern as RunStore (conftest swaps in a fresh instance per test).
default_proposal_store = ProposalStore()


def reset_default_proposal_store(root: Path | str | None = None) -> ProposalStore:
    """Re-init the module-level singleton at a new root. Used by tests
    to point at per-test directories without leaking between cases."""
    global default_proposal_store
    if root is None:
        root = Path("data/evolution/proposals")
    default_proposal_store = ProposalStore(root)
    return default_proposal_store
