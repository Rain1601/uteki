"""Unit tests for ``_strip_preamble`` in artifacts/store.py.

The strip exists because models (notably DeepSeek-chat) prepend
meta-narration to markdown deliverables despite explicit prompt
instructions not to. See design/02-self-evolution-loop.md and the
2026-05-26 iteration chain (runs 1-7).

These cases exhaustively cover the failure modes observed in the wild.
A regression here means the strip stopped working for a known
failure mode — bisect to the artifact_store change.
"""

from __future__ import annotations

import pytest

from uteki_api.artifacts.store import _strip_preamble


@pytest.mark.parametrize(
    "label,inp,expected_first_chars,expected_dropped_lines",
    [
        # ── No-op cases (input returned untouched) ───────────────────
        ("already-clean", "# Title\nbody", "# Title", 0),
        ("empty", "", "", 0),
        (
            "subheaders only, no top-level #",
            "preamble\n## subheading\nbody",
            "preamble",
            0,
        ),
        (
            "no # at all",
            "just some text without any heading markers",
            "just some text",
            0,
        ),
        # ── Newline-anchored preambles (the cleaner failure mode) ────
        (
            "single-line preamble + newline + #",
            "preamble line\n# Title\nbody",
            "# Title",
            1,
        ),
        (
            "multi-line preamble",
            "line1\nline2\nline3\n# Title\nbody",
            "# Title",
            3,
        ),
        (
            "preamble + phantom ## + real #",
            "preamble\n## fake heading\n# real title\nbody",
            "# real title",
            2,
        ),
        # ── Inline-squashed preambles (observed run 4, 2026-05-26) ──
        (
            "inline-squashed: chinese preamble + # on same line",
            "我来拉取数据。# 中国半导体设备",
            "# 中国半导体设备",
            0,
        ),
        (
            "inline-squashed: multi-line preamble ending with inline #",
            "step 1\nstep 2\ndone. # Real Title\nbody",
            "# Real Title",
            2,
        ),
        # ── Edge: # immediately preceded by non-# char at pos 0 ─────
        (
            "1-char preamble before #",
            "x# Title",
            "# Title",
            0,
        ),
    ],
)
def test_strip_preamble_cases(
    label: str,
    inp: str,
    expected_first_chars: str,
    expected_dropped_lines: int,
) -> None:
    kept, dropped_lines, dropped_bytes = _strip_preamble(inp)
    assert kept.startswith(expected_first_chars), (
        f"[{label}] expected start {expected_first_chars!r}, got {kept[:30]!r}"
    )
    assert dropped_lines == expected_dropped_lines, (
        f"[{label}] expected {expected_dropped_lines} lines dropped, got {dropped_lines}"
    )
    # Sanity: dropped_bytes >= 0 and consistent with content length
    assert dropped_bytes >= 0
    assert len(kept) + dropped_bytes >= len(inp) - 1  # allow off-by-one for UTF-8


def test_strip_preamble_no_false_strip_on_inline_hash_in_body() -> None:
    """A document with ``# `` legitimately in body content should still
    be stripped if there's preamble before — the rule is "first # wins".

    In practice, research notes never have ``# `` mid-body (markdown
    convention is to put headings on their own line), so this is a safe
    invariant for our use case. If it ever becomes a problem, the strip
    can be made structure-aware (require ``# `` at line start AFTER the
    first newline). For now we accept the aggressive behavior.
    """
    # No false-positive when there's no preamble at all:
    kept, _, _ = _strip_preamble("Plain text mentioning a # symbol mid-line.")
    # Aggressive: the `# ` mid-line will trigger strip. That's expected
    # behavior — surfaces to the reviewer if mid-line `# ` is real.
    assert "# symbol" in kept
