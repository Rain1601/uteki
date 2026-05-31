"""Self-evolution pipeline driver — spawn Claude Code as external reviewer.

Drives a proposal from ``triggered`` → ``pending_review`` (or ``invalidated``
on validation failure). The on-disk layout matches design/02-self-evolution-
loop.md §VII exactly:

    data/evolution/proposals/P-2026-NNN/
    ├── meta.json                # written by ProposalStore each transition
    ├── trigger.json
    ├── decisions/               # NNN-<status>.json per transition
    ├── snapshot/                # ← M1.3 writes
    │   ├── skill/SKILL.md       # source skill prompt at trigger time
    │   └── run_artifacts/*      # artifacts of the run being reviewed
    ├── brief.md                 # ← M1.3 writes (input to CC)
    └── cc_run/                  # ← M1.3 writes (CC's output)
        ├── invocation.json
        ├── stdout.log
        ├── transcript.jsonl     # real mode: streamed CC events; mock: synthetic
        ├── critique.md
        └── patch.diff

Mock vs real:

- ``UTEKI_USE_MOCK_CC=true`` (default, follows ``UTEKI_USE_MOCK_LLM``):
  Synthesize a canned critique referencing the snapshotted artifacts and a
  trivial no-op patch. Skips the subprocess so tests stay hermetic.
- ``UTEKI_USE_MOCK_CC=false``: spawn ``claude -p <brief> --output-format
  stream-json --allowed-tools "Read Grep Glob Edit Write" --cwd <proposal_dir>``
  with a hard timeout. CC writes critique.md + patch.diff into cc_run/ via
  its Write tool.

Both paths land the same files on disk; downstream M1.4-M1.6 don't care which
generated them.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from uteki_api.artifacts import default_artifact_store
from uteki_api.core.config import settings
from uteki_api.evolution.proposals import default_proposal_store
from uteki_api.runs import default_run_store
from uteki_api.skills.loader import compute_signature, load_skill_prompt

if TYPE_CHECKING:
    from uteki_api.artifacts.store import ArtifactStore
    from uteki_api.evolution.proposals.store import ProposalStore
    from uteki_api.runs.store import RunStore

logger = logging.getLogger(__name__)


@dataclass
class CCRunResult:
    """What ``run_cc_review`` returns. Files referenced are absolute paths."""

    proposal_id: str
    cc_dir: Path
    critique_path: Path | None
    patch_path: Path | None
    invocation: dict[str, Any]
    duration_s: float
    ok: bool
    error: str | None = None
    final_status: str = "pending_review"


# ──────────────────────────────────────────────────────────────────────
# Public entry point


async def run_cc_review(
    proposal_id: str,
    *,
    store: ProposalStore | None = None,
    run_store: RunStore | None = None,
    artifact_store: ArtifactStore | None = None,
    skill_root: Path | None = None,
    use_mock: bool | None = None,
    timeout_s: float | None = None,
) -> CCRunResult:
    """Drive a proposal from ``triggered`` to ``pending_review`` (or
    ``invalidated`` if CC's output fails sanity checks).

    All four collaborators (proposal store, run store, artifact store,
    skill root) default to the process-wide singletons; the override
    arguments exist for tests that want isolation.

    On any unexpected exception we mark the proposal ``invalidated`` so
    the run isn't stuck in a non-terminal phase indefinitely — and we
    re-raise the exception. The caller (background task) logs it.
    """
    pstore = store or default_proposal_store
    rstore = run_store or default_run_store
    astore = artifact_store or default_artifact_store
    sroot = skill_root or _default_skill_root()
    mock = settings.use_mock_cc if use_mock is None else use_mock
    timeout = settings.cc_timeout_seconds if timeout_s is None else timeout_s

    started = time.time()
    proposal = pstore.get(proposal_id)
    if proposal.status != "triggered":
        raise ValueError(
            f"cc_runner: proposal {proposal_id} is {proposal.status}, expected triggered"
        )

    proposal_dir = pstore._dir(proposal_id)  # noqa: SLF001 — same package

    try:
        # ── snapshot ─────────────────────────────────────────────────
        pstore.transition(proposal_id, "snapshotting", by="system:cc_runner")
        snapshot_dir = proposal_dir / "snapshot"
        skill_signature = await _snapshot(
            snapshot_dir,
            source_skill=proposal.source_skill,
            source_run_id=proposal.source_run_id,
            source_user_id=proposal.source_user_id,
            skill_root=sroot,
            artifact_store=astore,
            run_store=rstore,
        )
        # Record the skill signature on the proposal so apply phase can
        # detect "skill changed under us" between snapshot and apply.
        proposal = pstore.get(proposal_id)
        proposal.snapshot_skill_signature = skill_signature
        pstore._persist(proposal)  # noqa: SLF001

        # ── briefing ─────────────────────────────────────────────────
        pstore.transition(proposal_id, "briefing", by="system:cc_runner")
        brief_path = proposal_dir / "brief.md"
        _write_brief(
            brief_path,
            proposal_id=proposal_id,
            source_skill=proposal.source_skill,
            source_run_id=proposal.source_run_id,
        )

        # ── spawning ─────────────────────────────────────────────────
        pstore.transition(
            proposal_id,
            "spawning",
            by="system:cc_runner",
            extra={"mode": "mock" if mock else "real"},
        )
        cc_dir = proposal_dir / "cc_run"
        cc_dir.mkdir(parents=True, exist_ok=True)

        # ── generating ───────────────────────────────────────────────
        pstore.transition(proposal_id, "generating", by="system:cc_runner")
        if mock:
            invocation = await _spawn_mock(
                proposal_dir=proposal_dir,
                cc_dir=cc_dir,
                source_skill=proposal.source_skill,
            )
        else:
            invocation = await _spawn_real(
                proposal_dir=proposal_dir,
                cc_dir=cc_dir,
                brief_path=brief_path,
                timeout_s=timeout,
            )

        # ── validating ───────────────────────────────────────────────
        pstore.transition(proposal_id, "validating", by="system:cc_runner")
        critique_path = cc_dir / "critique.md"
        patch_path = cc_dir / "patch.diff"
        bad = _validate_outputs(critique_path, patch_path)
        if bad:
            pstore.transition(
                proposal_id,
                "invalidated",
                by="system:cc_runner",
                reason=bad,
                extra={"invocation": invocation},
            )
            return CCRunResult(
                proposal_id=proposal_id,
                cc_dir=cc_dir,
                critique_path=critique_path if critique_path.exists() else None,
                patch_path=patch_path if patch_path.exists() else None,
                invocation=invocation,
                duration_s=time.time() - started,
                ok=False,
                error=bad,
                final_status="invalidated",
            )

        # ── pending_review ───────────────────────────────────────────
        pstore.transition(
            proposal_id,
            "pending_review",
            by="system:cc_runner",
            extra={
                "invocation": invocation,
                "critique_bytes": critique_path.stat().st_size,
                "patch_bytes": patch_path.stat().st_size,
            },
        )
        return CCRunResult(
            proposal_id=proposal_id,
            cc_dir=cc_dir,
            critique_path=critique_path,
            patch_path=patch_path,
            invocation=invocation,
            duration_s=time.time() - started,
            ok=True,
            final_status="pending_review",
        )

    except Exception as e:  # noqa: BLE001 — final safety net
        # Don't leave the proposal stranded in a non-terminal status. If
        # the current status is already terminal, ProposalStore will refuse
        # the transition and the original exception still propagates.
        with contextlib.suppress(ValueError):
            pstore.transition(
                proposal_id,
                "invalidated",
                by="system:cc_runner",
                reason=f"unexpected error: {e}",
            )
        logger.exception("cc_runner failed for %s", proposal_id)
        raise


# ──────────────────────────────────────────────────────────────────────
# Phase implementations


def _default_skill_root() -> Path:
    """Where SKILL.md files live in the source tree.

    Resolved relative to this file rather than process cwd so the runner
    works regardless of where uvicorn / pytest were launched from.
    """
    return Path(__file__).resolve().parent.parent / "skills"


async def _snapshot(
    snapshot_dir: Path,
    *,
    source_skill: str,
    source_run_id: str,
    source_user_id: str,
    skill_root: Path,
    artifact_store: ArtifactStore,
    run_store: RunStore,
) -> str:
    """Freeze the skill prompt + run artifacts under snapshot/.

    Returns the skill prompt signature at snapshot time — recorded on the
    proposal so the apply phase can detect "skill changed under us".
    """
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    # 1. Skill prompt — copy SKILL.md + references (read via the same
    # loader the harness uses, so what's snapshotted is what the run saw).
    skill_dir_src = skill_root / source_skill
    skill_dir_dst = snapshot_dir / "skill"
    skill_dir_dst.mkdir(parents=True, exist_ok=True)
    if skill_dir_src.exists():
        # Copy the on-disk skill folder verbatim (SKILL.md + references/).
        # Use copytree dirs_exist_ok so re-snapshot doesn't crash.
        if skill_dir_dst.exists():
            shutil.rmtree(skill_dir_dst)
        shutil.copytree(skill_dir_src, skill_dir_dst)
    else:
        # Skill might live under a pipeline directory or be in-memory only;
        # write whatever load_skill_prompt sees so the snapshot isn't empty.
        try:
            prompt_text, _refs = load_skill_prompt(source_skill)
            (skill_dir_dst / "SKILL.md").write_text(prompt_text, encoding="utf-8")
        except FileNotFoundError:
            (skill_dir_dst / "SKILL.md").write_text(
                f"# (no SKILL.md found for {source_skill})\n", encoding="utf-8"
            )

    try:
        prompt_text, _refs = load_skill_prompt(source_skill)
        skill_signature = compute_signature(prompt_text)
    except FileNotFoundError:
        skill_signature = "unknown"

    # 2. Run artifacts — copy every artifact the run wrote, so CC has the
    # exact text it should critique.
    artifacts_dst = snapshot_dir / "run_artifacts"
    artifacts_dst.mkdir(parents=True, exist_ok=True)
    arts = await artifact_store.list(source_run_id, user_id=source_user_id)
    for art in arts:
        try:
            content = await artifact_store.read(
                source_run_id, art.name, user_id=source_user_id
            )
        except (FileNotFoundError, OSError):
            continue
        # Preserve original name; arts come from a single run dir so no
        # collisions, but normalize just in case.
        safe_name = art.name.replace("/", "_")
        if isinstance(content, bytes):
            (artifacts_dst / safe_name).write_bytes(content)
        else:
            (artifacts_dst / safe_name).write_text(str(content), encoding="utf-8")

    # 3. Run metadata sidecar — gives CC context that isn't in artifacts.
    try:
        run = await run_store.get(source_run_id, source_user_id)
        (snapshot_dir / "run_meta.json").write_text(
            json.dumps(
                {
                    "id": run.id,
                    "skill": run.skill,
                    "skill_version": run.skill_version,
                    "status": run.status,
                    "summary": run.summary,
                    "user_input": run.user_input,
                    "tags": list(run.tags),
                    "usage_summary": run.usage_summary.model_dump(),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except (KeyError, AttributeError):
        pass

    return skill_signature


_BRIEF_TEMPLATE = """# Task: review uteki run {source_run_id}

You are reviewing a single ``{source_skill}`` run that uteki's drift / quality
monitor (or an operator) flagged for external review. uteki's internal
evaluator already scored this run, but it lives inside the same agent loop
and shares prompt heritage with the generator — your job is to give the
**outside view**.

## What's in this workdir

- ``snapshot/skill/SKILL.md`` — the prompt that drove the run.
- ``snapshot/skill/references/*`` (if any) — additional prompt material.
- ``snapshot/run_artifacts/*`` — every artifact the run wrote
  (final-report.md, sources.json, trace-diagnosis.json, etc).
- ``snapshot/run_meta.json`` — run id, status, summary, token usage.
- ``brief.md`` — this file.

## Output you must produce (exactly these paths)

- ``cc_run/critique.md`` — at least 3 specific findings. Each finding MUST
  cite a line number or quoted excerpt from ``snapshot/run_artifacts/*``.
  No vague criticism.
- ``cc_run/patch.diff`` — unified diff against ``snapshot/skill/SKILL.md``
  proposing a minimal prompt change. Empty file is OK if no prompt change
  is warranted; in that case explain why in critique.md.

## Constraints

- Do not invent acceptance criteria not in ``snapshot/skill/`` or the
  uteki spec.
- Cite a specific artifact location for every claim.
- Total SKILL.md change ≤ 30 lines.
- Preserve the skill's brand voice.
- You may NOT modify files outside ``cc_run/``.

## Context

- proposal_id: {proposal_id}
- source_skill: {source_skill}
- source_run_id: {source_run_id}
"""


def _write_brief(
    path: Path,
    *,
    proposal_id: str,
    source_skill: str,
    source_run_id: str,
) -> None:
    path.write_text(
        _BRIEF_TEMPLATE.format(
            proposal_id=proposal_id,
            source_skill=source_skill,
            source_run_id=source_run_id,
        ),
        encoding="utf-8",
    )


async def _spawn_real(
    *,
    proposal_dir: Path,
    cc_dir: Path,
    brief_path: Path,
    timeout_s: float,
) -> dict[str, Any]:
    """Spawn the ``claude`` CLI in non-interactive mode.

    Returns the invocation record (command, args, exit code, model, duration).
    Streams stream-json events to ``cc_run/transcript.jsonl`` and the raw
    stdout to ``cc_run/stdout.log`` for forensics.
    """
    brief = brief_path.read_text(encoding="utf-8")
    cli = settings.cc_cli_path
    args = [
        cli,
        "-p",
        brief,
        "--output-format",
        "stream-json",
        "--allowedTools",
        "Read Grep Glob Edit Write",
        "--model",
        settings.cc_model,
    ]
    invocation: dict[str, Any] = {
        "cli": cli,
        "model": settings.cc_model,
        "args": args[1:],  # don't repeat the binary path
        "cwd": str(proposal_dir),
        "started_at": time.time(),
    }
    stdout_log = cc_dir / "stdout.log"
    transcript = cc_dir / "transcript.jsonl"
    stderr_log = cc_dir / "stderr.log"

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(proposal_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError as e:
        invocation["error"] = f"claude CLI not found at {cli!r}: {e}"
        invocation["exit_code"] = -1
        (cc_dir / "invocation.json").write_text(
            json.dumps(invocation, indent=2, default=str), encoding="utf-8"
        )
        return invocation

    stdout_buf: list[bytes] = []
    stderr_buf: list[bytes] = []

    async def _drain(stream: asyncio.StreamReader, buf: list[bytes], stream_to: Path | None) -> None:
        while True:
            line = await stream.readline()
            if not line:
                break
            buf.append(line)
            if stream_to is not None:
                with stream_to.open("ab") as f:
                    f.write(line)

    try:
        await asyncio.wait_for(
            asyncio.gather(
                _drain(proc.stdout, stdout_buf, transcript),  # type: ignore[arg-type]
                _drain(proc.stderr, stderr_buf, stderr_log),  # type: ignore[arg-type]
                proc.wait(),
            ),
            timeout=timeout_s,
        )
    except TimeoutError:
        proc.kill()
        invocation["error"] = f"timeout after {timeout_s}s"

    invocation["exit_code"] = proc.returncode
    invocation["ended_at"] = time.time()
    invocation["duration_s"] = round(
        invocation["ended_at"] - invocation["started_at"], 3
    )
    stdout_log.write_bytes(b"".join(stdout_buf))
    (cc_dir / "invocation.json").write_text(
        json.dumps(invocation, indent=2, default=str), encoding="utf-8"
    )
    return invocation


async def _spawn_mock(
    *,
    proposal_dir: Path,
    cc_dir: Path,
    source_skill: str,
) -> dict[str, Any]:
    """Synthesize canned critique + patch so the E2E suite doesn't depend on
    a CC install. The shape matches real mode bit-for-bit so downstream
    consumers (validation, G1 UI) can't tell the difference."""
    started = time.time()

    # Read what the snapshot actually contains so the canned critique
    # references real artifact names — that way T12 can assert the
    # critique mentions a known artifact and we don't accidentally drift.
    artifacts_dir = proposal_dir / "snapshot" / "run_artifacts"
    sample_names = sorted(p.name for p in artifacts_dir.iterdir())[:3] if artifacts_dir.exists() else []

    critique = _MOCK_CRITIQUE_TEMPLATE.format(
        source_skill=source_skill,
        sample_artifact=(sample_names[0] if sample_names else "final-report.md"),
        artifact_list=("\n".join(f"- {n}" for n in sample_names) or "- (no artifacts captured)"),
    )
    (cc_dir / "critique.md").write_text(critique, encoding="utf-8")

    # Mock patch is a no-op trailing-newline diff so validation has a
    # syntactically valid unified diff to inspect, but applying it doesn't
    # actually change SKILL.md. M1.4 will exercise apply.
    patch = _MOCK_PATCH_TEMPLATE.format(source_skill=source_skill)
    (cc_dir / "patch.diff").write_text(patch, encoding="utf-8")

    # Single synthetic transcript event so M1.5's review UI has something
    # to render in the "CC reasoning" panel even in mock mode.
    transcript = cc_dir / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "type": "mock",
                "ts": started,
                "message": f"mock cc_runner synthesized critique for {source_skill}",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    invocation = {
        "cli": "mock",
        "model": "mock-cc",
        "args": [],
        "cwd": str(proposal_dir),
        "started_at": started,
        "ended_at": time.time(),
        "duration_s": round(time.time() - started, 3),
        "exit_code": 0,
        "mode": "mock",
    }
    (cc_dir / "invocation.json").write_text(
        json.dumps(invocation, indent=2, default=str), encoding="utf-8"
    )
    return invocation


_MOCK_CRITIQUE_TEMPLATE = """# Mock CC critique — {source_skill}

> Generated by ``cc_runner`` in mock mode (UTEKI_USE_MOCK_CC=true). Real
> mode synthesizes this file by spawning the Claude Code CLI against the
> snapshot/ directory. The shape is identical to real-mode output so
> downstream consumers (validation, G1 review UI) don't branch.

## Snapshot inventory

The following artifacts were captured for review:

{artifact_list}

## Findings

### Finding #1: Mock — sample evidence reference
- Sample artifact ``{sample_artifact}`` was captured in the snapshot.
  Real-mode CC would cite specific line numbers and quoted excerpts.

### Finding #2: Mock — no behavior change suggested
- Mock mode does not propose substantive prompt changes. ``patch.diff``
  contains only a trailing-whitespace edit so the file is a valid
  unified diff.

### Finding #3: Mock — placeholder for governance
- Wiring this proposal through G1 review still exercises the full
  decision audit trail even though the proposed change is a no-op.

## Recommendation

Defer or discard in mock mode; the patch is deliberately content-free.
"""

_MOCK_PATCH_TEMPLATE = """--- a/snapshot/skill/SKILL.md
+++ b/snapshot/skill/SKILL.md
@@ -1,1 +1,1 @@
-# {source_skill} (mock)
+# {source_skill} (mock — touched by cc_runner)
"""


# ──────────────────────────────────────────────────────────────────────
# Validation


def _validate_outputs(critique_path: Path, patch_path: Path) -> str | None:
    """Return a reason string if CC's output looks unusable; ``None`` if OK.

    Mock-mode output always passes; real-mode CC can produce garbage when
    the run is degenerate or the CLI errors out, so the checks below are
    minimal "is there a file at all" guards. M1.4 layers diff/markdown
    semantic validation on top.
    """
    if not critique_path.exists():
        return "critique.md missing"
    if critique_path.stat().st_size == 0:
        return "critique.md empty"
    if not patch_path.exists():
        return "patch.diff missing"
    # Empty patch is allowed (CC may decide no change is warranted) —
    # only block on the missing-file case.
    return None
