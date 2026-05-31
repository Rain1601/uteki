"""Unit tests for evolution/validators.py (M1.4).

Pure-function checks — no subprocess in most cases; the git-apply check
spawns a real git but doesn't need a repo or network.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from uteki_api.evolution.validators import (
    MAX_PATCH_LINES,
    count_findings,
    git_apply_check,
    parse_diff_stats,
    validate_cc_outputs,
)

# ── count_findings ───────────────────────────────────────────────────


def test_count_findings_counts_level3_headings() -> None:
    text = """# Title

## Section A

### Finding #1: foo
- bar

### Finding #2: baz

## Section B
Just prose, no findings here.

### Issue #3: also counts
"""
    assert count_findings(text) == 3


def test_count_findings_handles_empty_and_no_h3() -> None:
    assert count_findings("") == 0
    assert count_findings("# Top\n## Sub\nNo level-3 here") == 0


# ── parse_diff_stats ─────────────────────────────────────────────────


def test_parse_diff_stats_empty() -> None:
    s = parse_diff_stats("")
    assert s.file_count == 0
    assert s.lines_added == 0
    assert s.lines_removed == 0
    assert s.has_hunks is False
    assert s.lines_total == 0


def test_parse_diff_stats_whitespace_only() -> None:
    s = parse_diff_stats("\n   \n\t\n")
    assert s.lines_added == 0
    assert s.lines_removed == 0


def test_parse_diff_stats_typical_unified_diff() -> None:
    diff = """--- a/SKILL.md
+++ b/SKILL.md
@@ -1,3 +1,4 @@
 line one
-line two old
+line two new
+brand new line
 line three
"""
    s = parse_diff_stats(diff)
    assert s.file_count == 1
    assert s.has_hunks is True
    assert s.lines_added == 2  # "line two new" + "brand new line"
    assert s.lines_removed == 1  # "line two old"
    assert s.lines_total == 3
    # Crucially: --- / +++ headers must NOT be counted as +/- lines.


def test_parse_diff_stats_multi_file() -> None:
    diff = """--- a/A.md
+++ b/A.md
@@ -1,1 +1,1 @@
-old A
+new A
--- a/B.md
+++ b/B.md
@@ -1,1 +1,1 @@
-old B
+new B
"""
    s = parse_diff_stats(diff)
    assert s.file_count == 2
    assert s.lines_added == 2
    assert s.lines_removed == 2


# ── git_apply_check ──────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_git_apply_check_empty_diff_trivially_ok(tmp_path: Path) -> None:
    empty_diff = tmp_path / "empty.diff"
    empty_diff.write_text("", encoding="utf-8")
    ok, reason = await git_apply_check(empty_diff, tmp_path)
    assert ok
    assert reason == ""


@pytest.mark.asyncio
async def test_git_apply_check_missing_file_treated_as_empty(tmp_path: Path) -> None:
    missing = tmp_path / "nope.diff"
    ok, reason = await git_apply_check(missing, tmp_path)
    assert ok  # missing file == no-op patch, trivially applies


@pytest.mark.asyncio
async def test_git_apply_check_clean_apply(tmp_path: Path) -> None:
    """Set up a target file + matching diff and verify --check passes."""
    target = tmp_path / "SKILL.md"
    target.write_text("hello world\n", encoding="utf-8")
    diff = tmp_path / "ok.diff"
    diff.write_text(
        "--- a/SKILL.md\n"
        "+++ b/SKILL.md\n"
        "@@ -1,1 +1,1 @@\n"
        "-hello world\n"
        "+hello uteki\n",
        encoding="utf-8",
    )
    ok, reason = await git_apply_check(diff, tmp_path)
    assert ok, f"expected clean apply, got: {reason}"


@pytest.mark.asyncio
async def test_git_apply_check_rejects_mismatched_context(tmp_path: Path) -> None:
    """If the target file doesn't contain the expected lines, apply fails."""
    target = tmp_path / "SKILL.md"
    target.write_text("totally different content\n", encoding="utf-8")
    diff = tmp_path / "bad.diff"
    diff.write_text(
        "--- a/SKILL.md\n"
        "+++ b/SKILL.md\n"
        "@@ -1,1 +1,1 @@\n"
        "-hello world\n"
        "+hello uteki\n",
        encoding="utf-8",
    )
    ok, reason = await git_apply_check(diff, tmp_path)
    assert not ok
    assert reason  # git provides a real error message


# ── validate_cc_outputs (composite) ─────────────────────────────────


@pytest.mark.asyncio
async def test_validate_cc_outputs_happy_path_empty_patch(tmp_path: Path) -> None:
    """Critique present + non-empty + empty patch = OK (mock-mode shape)."""
    critique = tmp_path / "critique.md"
    critique.write_text(
        "# Critique\n\n### Finding #1\nLine reference here.\n",
        encoding="utf-8",
    )
    patch = tmp_path / "patch.diff"
    patch.write_text("", encoding="utf-8")
    report = await validate_cc_outputs(
        critique_path=critique, patch_path=patch, apply_base_dir=tmp_path
    )
    assert report.ok, f"unexpected reasons: {report.reasons}"
    assert report.reasons == []
    assert report.stats["critique_finding_count"] == 1
    assert report.stats["patch_lines_total"] == 0
    assert report.stats["patch_applies"] is True


@pytest.mark.asyncio
async def test_validate_cc_outputs_missing_critique(tmp_path: Path) -> None:
    patch = tmp_path / "patch.diff"
    patch.write_text("", encoding="utf-8")
    report = await validate_cc_outputs(
        critique_path=tmp_path / "nope.md",
        patch_path=patch,
        apply_base_dir=tmp_path,
    )
    assert not report.ok
    assert any("critique.md missing" in r for r in report.reasons)


@pytest.mark.asyncio
async def test_validate_cc_outputs_empty_critique(tmp_path: Path) -> None:
    critique = tmp_path / "critique.md"
    critique.write_text("", encoding="utf-8")
    patch = tmp_path / "patch.diff"
    patch.write_text("", encoding="utf-8")
    report = await validate_cc_outputs(
        critique_path=critique, patch_path=patch, apply_base_dir=tmp_path
    )
    assert not report.ok
    assert any("critique.md empty" in r for r in report.reasons)


@pytest.mark.asyncio
async def test_validate_cc_outputs_patch_over_cap(tmp_path: Path) -> None:
    critique = tmp_path / "critique.md"
    critique.write_text("# c\n### Finding #1\nok", encoding="utf-8")
    # Build a synthetic diff over the line cap.
    target = tmp_path / "SKILL.md"
    target.write_text("\n".join(f"line {i}" for i in range(200)) + "\n", encoding="utf-8")
    big_diff_lines = ["--- a/SKILL.md", "+++ b/SKILL.md", f"@@ -1,{MAX_PATCH_LINES + 10} +1,{MAX_PATCH_LINES + 10} @@"]
    for i in range(MAX_PATCH_LINES + 5):
        big_diff_lines.append(f"-line {i}")
        big_diff_lines.append(f"+line {i} edited")
    patch = tmp_path / "patch.diff"
    patch.write_text("\n".join(big_diff_lines) + "\n", encoding="utf-8")
    report = await validate_cc_outputs(
        critique_path=critique, patch_path=patch, apply_base_dir=tmp_path
    )
    assert not report.ok
    assert any("exceeds cap" in r for r in report.reasons)


@pytest.mark.asyncio
async def test_validate_cc_outputs_patch_without_headers(tmp_path: Path) -> None:
    """Non-empty patch that's not actually a unified diff."""
    critique = tmp_path / "critique.md"
    critique.write_text("# c\n### Finding #1\nok", encoding="utf-8")
    patch = tmp_path / "patch.diff"
    patch.write_text("this is just prose, not a diff at all\n", encoding="utf-8")
    report = await validate_cc_outputs(
        critique_path=critique, patch_path=patch, apply_base_dir=tmp_path
    )
    assert not report.ok
    # Expect both "no hunks" and "no file header" to fire — they accumulate.
    joined = " | ".join(report.reasons)
    assert "hunk" in joined
    assert "file header" in joined


@pytest.mark.asyncio
async def test_validate_cc_outputs_patch_unappliable(tmp_path: Path) -> None:
    """Structurally-valid diff but the target doesn't match → apply fails."""
    critique = tmp_path / "critique.md"
    critique.write_text("# c\n### Finding #1\nok", encoding="utf-8")
    target = tmp_path / "SKILL.md"
    target.write_text("actual content that won't match the diff\n", encoding="utf-8")
    patch = tmp_path / "patch.diff"
    patch.write_text(
        "--- a/SKILL.md\n+++ b/SKILL.md\n@@ -1,1 +1,1 @@\n-expected nonsense\n+replacement\n",
        encoding="utf-8",
    )
    report = await validate_cc_outputs(
        critique_path=critique, patch_path=patch, apply_base_dir=tmp_path
    )
    assert not report.ok
    assert any("git apply --check failed" in r for r in report.reasons)
    assert report.stats["patch_applies"] is False
