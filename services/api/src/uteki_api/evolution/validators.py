"""Validators for cc_runner output (M1.4).

Pure functions used by ``cc_runner._validate_outputs`` to decide whether a
proposal advances to ``pending_review`` (good output) or ``invalidated``
(bad output). All checks are local — no LLM calls, no network.

The motivating contract (design/02 §VIII): CC's output is best-effort, and
"gives an unappliable diff" is a real failure mode that must be caught
*before* the operator sees a misleading G1 prompt. Catching it here also
gives us data on "which model + brief produced the most bad outputs" so
the brief template can evolve.

Returned shape (per design/05 Phase 1 task 1.4 acceptance):

    validation.json: {
        "ok": bool,
        "reasons": [str, ...],          # empty when ok
        "stats": {
            "critique_bytes": int,
            "critique_finding_count": int,
            "patch_bytes": int,
            "patch_file_count": int,
            "patch_lines_added": int,
            "patch_lines_removed": int,
            "patch_lines_total": int,    # added + removed; capped vs MAX_PATCH_LINES
        },
        "checked_at": float,
    }

``ok=True`` requires every check below to pass; the ``reasons`` list
enumerates every failed check so the operator can see all problems at
once, not just the first.
"""

from __future__ import annotations

import asyncio
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

# Per the brief template: total +/- diff lines must stay under this cap.
# Smaller than the design/02 "≤30 lines" wording because the brief itself
# says ≤30 lines; we leave headroom for context lines.
MAX_PATCH_LINES = 60

# A "finding" in critique.md = a level-3 (or deeper) heading. Two levels
# of evidence for non-emptiness: bytes + structured-finding count.
_FINDING_HEADING_RE = re.compile(r"^###\s+", re.MULTILINE)

# Unified diff frame markers — defensive parser, doesn't require git.
_DIFF_FILE_HEADER_RE = re.compile(r"^(?:---|\+\+\+)\s+\S", re.MULTILINE)
_DIFF_HUNK_HEADER_RE = re.compile(r"^@@\s+-\d", re.MULTILINE)


@dataclass(slots=True)
class DiffStats:
    file_count: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    has_hunks: bool = False

    @property
    def lines_total(self) -> int:
        return self.lines_added + self.lines_removed


@dataclass(slots=True)
class ValidationReport:
    ok: bool
    reasons: list[str] = field(default_factory=list)
    stats: dict[str, int | float | str | None] = field(default_factory=dict)
    checked_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


# ── Pure validators ──────────────────────────────────────────────────


def count_findings(critique_text: str) -> int:
    """Count level-3 headings (### Finding #N / ### Issue ...).

    The brief tells CC to use ``### Finding #N`` per finding, but real CC
    may use ``### Issue`` / ``### Problem`` / etc. Count any ``###``
    heading — that's still a meaningful sectioning signal.
    """
    return len(_FINDING_HEADING_RE.findall(critique_text))


def parse_diff_stats(diff_text: str) -> DiffStats:
    """Parse +/- line counts from a unified diff without invoking git.

    Counts:
    - file headers (``--- ...`` lines) for file_count
    - lines starting with ``+`` (not ``+++``) for additions
    - lines starting with ``-`` (not ``---``) for removals
    - presence of ``@@`` hunk markers (any) for has_hunks

    Returns zero-everywhere DiffStats on an empty / whitespace-only diff.
    """
    if not diff_text or not diff_text.strip():
        return DiffStats()

    stats = DiffStats()
    # File headers come in --- / +++ pairs; count the +++ lines to avoid
    # double-counting (and to match how a reader thinks about "this file").
    plusplus_headers = re.findall(r"^\+\+\+\s+\S", diff_text, flags=re.MULTILINE)
    stats.file_count = len(plusplus_headers)

    stats.has_hunks = bool(_DIFF_HUNK_HEADER_RE.search(diff_text))

    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            stats.lines_added += 1
        elif line.startswith("-"):
            stats.lines_removed += 1

    return stats


async def git_apply_check(diff_path: Path, base_dir: Path) -> tuple[bool, str]:
    """Ask git whether the diff applies cleanly to files under base_dir.

    Uses ``git apply --check -p1 <diff_path>`` from ``base_dir``. No real
    git repo is required — apply --check works on any filesystem.

    Empty diffs are considered trivially applicable (no-op).

    Returns (ok, stderr-or-empty-on-success). When git is missing or hangs,
    ok=False with a descriptive reason; we don't want the validator to be
    the thing that crashes the pipeline.
    """
    if not diff_path.exists() or diff_path.stat().st_size == 0:
        return True, ""

    try:
        proc = await asyncio.create_subprocess_exec(
            "git", "apply", "--check", "-p1", str(diff_path.resolve()),
            cwd=str(base_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return False, "git binary not found; cannot apply --check"

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=15.0)
    except TimeoutError:
        proc.kill()
        return False, "git apply --check timed out after 15s"

    if proc.returncode == 0:
        return True, ""
    err = stderr.decode("utf-8", errors="replace").strip() or stdout.decode(
        "utf-8", errors="replace"
    ).strip() or f"git apply --check exit={proc.returncode}"
    return False, err


# ── Composite validation ────────────────────────────────────────────


async def validate_cc_outputs(
    *,
    critique_path: Path,
    patch_path: Path,
    apply_base_dir: Path,
    max_patch_lines: int = MAX_PATCH_LINES,
) -> ValidationReport:
    """Run every check and assemble a ValidationReport.

    ``ok`` is the conjunction of every individual check. ``reasons`` lists
    each specific failure so the operator can see all problems at once
    instead of "fix one, re-run, see the next".
    """
    reasons: list[str] = []
    stats: dict[str, int | float | str | None] = {}

    # Critique present + non-empty + structurally non-trivial
    if not critique_path.exists():
        reasons.append("critique.md missing")
        critique_text = ""
    else:
        critique_text = critique_path.read_text(encoding="utf-8", errors="replace")
    stats["critique_bytes"] = len(critique_text.encode("utf-8"))
    if critique_path.exists() and not critique_text.strip():
        reasons.append("critique.md empty")
    finding_count = count_findings(critique_text)
    stats["critique_finding_count"] = finding_count
    if critique_path.exists() and critique_text.strip() and finding_count == 0:
        # Soft signal — log it but don't hard-fail. Some critiques are
        # narrative-style and lack ### headings yet are still valid output.
        # Operator can decide at G1. We surface it as a stat, not a reason.
        pass

    # Patch present (empty patch allowed — explicit no-op signal from CC)
    if not patch_path.exists():
        reasons.append("patch.diff missing")
        patch_text = ""
    else:
        patch_text = patch_path.read_text(encoding="utf-8", errors="replace")
    stats["patch_bytes"] = len(patch_text.encode("utf-8"))

    diff_stats = parse_diff_stats(patch_text)
    stats["patch_file_count"] = diff_stats.file_count
    stats["patch_lines_added"] = diff_stats.lines_added
    stats["patch_lines_removed"] = diff_stats.lines_removed
    stats["patch_lines_total"] = diff_stats.lines_total

    if patch_text.strip():
        # Non-empty patch must be structurally a unified diff.
        if not diff_stats.has_hunks:
            reasons.append("patch.diff is non-empty but has no @@ hunk markers")
        if not _DIFF_FILE_HEADER_RE.search(patch_text):
            reasons.append("patch.diff is non-empty but has no ---/+++ file header")
        if diff_stats.lines_total > max_patch_lines:
            reasons.append(
                f"patch.diff exceeds cap: {diff_stats.lines_total} > {max_patch_lines} +/- lines"
            )
        # And actually apply-checkable.
        apply_ok, apply_err = await git_apply_check(patch_path, apply_base_dir)
        if not apply_ok:
            reasons.append(f"git apply --check failed: {apply_err[:200]}")
        stats["patch_applies"] = apply_ok
    else:
        stats["patch_applies"] = True  # empty patch is trivially applicable

    return ValidationReport(ok=not reasons, reasons=reasons, stats=stats)
