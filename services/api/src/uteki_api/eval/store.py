"""Eval-run history store.

Each ``EvalRunner.run_case`` invocation appends one ``EvalRecord`` to this
store. Used by:
- ``/api/eval/cases/{id}/history`` — per-case trend
- ``/api/eval/history`` — global recent
- ``drift_monitor`` — today-vs-week-ago pass-rate comparison

Storage is **line-delimited JSON** (one record per line, append-only).
- corruption-resistant: a partial last line is the only thing lost
- no rewrite cost as the file grows
- trivial to ``tail -f`` while iterating

File layout (M4 — partitioned by ``user_id``):
    data/users/<user_id>/eval-history/
    ├── all.ndjson                  # every record (chronological)
    └── by-case/
        ├── research-sector-primer.ndjson
        ├── sample-001.ndjson
        └── ...

Platform-level evals (drift_monitor, scheduled jobs) use the reserved
``user_id="system"`` partition. User-triggered ``POST /api/eval/run`` writes
under the caller's id; ``GET /api/eval/history`` reads only the caller's
partition so users don't see each other's eval noise.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from pathlib import Path

from pydantic import BaseModel, Field


class EvalRecord(BaseModel):
    """One eval run on one case. Append-only; never mutated."""

    case_id: str
    started_at: float = Field(default_factory=time.time)
    pass_rate: float = 0.0  # 0..1 — substring + tool scores averaged for this case
    judge_scores: dict[str, int] = Field(default_factory=dict)  # rubric → 1..10
    decision: str | None = None  # evaluator's verdict if pipeline ran (approve/revise/reject)
    run_id: str | None = None
    notes: str = ""


class EvalHistoryStore(ABC):
    @abstractmethod
    async def append(self, user_id: str, record: EvalRecord) -> None: ...

    @abstractmethod
    async def list_case(
        self, user_id: str, case_id: str, limit: int = 50
    ) -> list[EvalRecord]: ...

    @abstractmethod
    async def list_recent(self, user_id: str, limit: int = 100) -> list[EvalRecord]: ...


def _safe_id(s: str) -> str:
    """Filesystem-safe identifier — same convention as ArtifactStore."""
    cleaned = "".join(c if c.isalnum() or c in "._-" else "_" for c in s)
    return cleaned or "_"


class JsonFileEvalHistory(EvalHistoryStore):
    """Append-only ndjson backend, partitioned per user. See module docstring."""

    def __init__(self, root: Path | str = Path("data")) -> None:
        # ``root`` is the data dir; per-user partitions live under it.
        self.root = Path(root).resolve()

    def _user_root(self, user_id: str) -> Path:
        return self.root / "users" / _safe_id(user_id) / "eval-history"

    def _all_path(self, user_id: str) -> Path:
        return self._user_root(user_id) / "all.ndjson"

    def _by_case_dir(self, user_id: str) -> Path:
        return self._user_root(user_id) / "by-case"

    async def append(self, user_id: str, record: EvalRecord) -> None:
        user_root = self._user_root(user_id)
        by_case = self._by_case_dir(user_id)
        user_root.mkdir(parents=True, exist_ok=True)
        by_case.mkdir(parents=True, exist_ok=True)
        line = record.model_dump_json() + "\n"
        # Per-user global ndjson
        with self._all_path(user_id).open("a", encoding="utf-8") as f:
            f.write(line)
        # Per-case file
        case_path = by_case / f"{_safe_id(record.case_id)}.ndjson"
        with case_path.open("a", encoding="utf-8") as f:
            f.write(line)

    @staticmethod
    def _tail_ndjson(path: Path, limit: int) -> list[EvalRecord]:
        if not path.exists():
            return []
        out: list[EvalRecord] = []
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            return []
        # Walk from the end backwards. Cheap for our small files.
        for raw in reversed(text.splitlines()):
            if not raw.strip():
                continue
            try:
                rec = EvalRecord.model_validate_json(raw)
            except Exception:  # noqa: BLE001 — corrupt line skipped
                continue
            out.append(rec)
            if len(out) >= limit:
                break
        return out

    async def list_case(
        self, user_id: str, case_id: str, limit: int = 50
    ) -> list[EvalRecord]:
        path = self._by_case_dir(user_id) / f"{_safe_id(case_id)}.ndjson"
        # newest-first to match other endpoints
        return self._tail_ndjson(path, limit)

    async def list_recent(self, user_id: str, limit: int = 100) -> list[EvalRecord]:
        return self._tail_ndjson(self._all_path(user_id), limit)


# Module-level singleton. ``root="data"`` resolves relative to the API
# process working dir — typically ``services/api/``, so files land in
# ``services/api/data/users/<user_id>/eval-history/`` (gitignored).
default_eval_history: EvalHistoryStore = JsonFileEvalHistory()
