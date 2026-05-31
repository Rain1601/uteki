"""Apply-phase driver for the self-evolution loop (M1.6).

Takes a proposal in ``accepted`` and walks it through:

    accepted → applying → a_b_eval     (success path)
    accepted → applying → apply_failed (terminal — operator must investigate)

What 'apply' physically does (per design/02 step ⑪):

1. Reads ``cc_run/patch.diff`` from the proposal directory.
2. If non-empty: ``git apply -p3 --directory=<live_skill_dir> --check``
   first, then for real. ``-p3`` strips the CC-written prefix ``a/snapshot/
   skill/`` so the patch addresses the live SKILL.md.
3. Captures the post-apply prompt + signature into ``post_apply/SKILL.md``
   + ``post_apply/signature`` so M1.8 rollback has a known good revert
   target (and a side-by-side diff for the operator).
4. Invalidates the prompt loader cache and refreshes the live skill's
   ``system_prompt`` so the next run uses the new prompt without an API
   restart (same path ``POST /api/admin/reload-skills`` uses).
5. Records a fresh ``SkillVersion`` in EvolutionStore — parent = the
   previous latest, changelog computed from the signature delta. The
   proposal_id is stamped onto the version's params so the evolution
   history points back at why the change happened.
6. Stamps ``Proposal.applied_skill_signature`` and transitions to
   ``a_b_eval`` (M1.7 picks it up; for now the proposal parks there
   ready for human inspection).

Empty patch is honored as the brief explicitly allows (``Empty file is OK
if no prompt change is warranted``). In that case the prompt + signature
don't change, but we still record a no-op SkillVersion so the audit trail
is uniform.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from uteki_api.evolution import (
    SkillVersion,
    compute_changelog,
    default_evolution_store,
)
from uteki_api.evolution.proposals import default_proposal_store
from uteki_api.skills import default_skills
from uteki_api.skills.loader import compute_signature, load_skill_prompt

if TYPE_CHECKING:
    from uteki_api.evolution.proposals.models import Proposal
    from uteki_api.evolution.proposals.store import ProposalStore
    from uteki_api.evolution.store import EvolutionStore

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ApplyResult:
    proposal_id: str
    ok: bool
    final_status: str  # "a_b_eval" or "apply_failed"
    new_version: str | None = None
    applied_signature: str | None = None
    error: str | None = None
    duration_s: float = 0.0
    patch_was_empty: bool = False


def _default_skill_root() -> Path:
    return Path(__file__).resolve().parent.parent / "skills"


def _skill_dir(skill_root: Path, skill_name: str) -> Path:
    return skill_root / skill_name


def _normalize_patch_paths(patch_text: str) -> str:
    """Strip the CC brief's ``a/snapshot/skill/`` and ``b/snapshot/skill/``
    prefixes so the resulting diff addresses files directly inside the live
    skill folder (``a/SKILL.md`` form). We pre-process the patch here rather
    than rely on ``git apply --directory`` because git apply's --directory
    flag exhibits surprising relative-to-cwd resolution semantics inside a
    git working tree and silently no-ops in some configurations.
    """
    import re as _re
    # Match both common shapes: with or without the a/b prefix.
    patterns = [
        (_re.compile(r"^--- a/snapshot/skill/", _re.MULTILINE), "--- a/"),
        (_re.compile(r"^\+\+\+ b/snapshot/skill/", _re.MULTILINE), "+++ b/"),
        (_re.compile(r"^--- snapshot/skill/", _re.MULTILINE), "--- "),
        (_re.compile(r"^\+\+\+ snapshot/skill/", _re.MULTILINE), "+++ "),
    ]
    out = patch_text
    for rx, repl in patterns:
        out = rx.sub(repl, out)
    return out


async def _git_apply(
    patch_path: Path,
    skill_dir: Path,
    *,
    check_only: bool,
) -> tuple[bool, str]:
    """Invoke ``git apply [-p1 --check] <normalized-patch>`` from inside
    ``skill_dir`` so file paths in the diff resolve directly against the
    live skill folder.

    The patch is read, normalized to drop the brief's ``a/snapshot/skill/``
    prefix, written to a sibling ``.diff.normalized`` file, and passed by
    absolute path. Running git from the skill dir avoids the
    --directory-vs-cwd subtleties we hit when patching files inside an
    existing git working tree.

    Returns (ok, stderr-or-empty). On structural issues (git missing,
    timeout, non-zero exit) returns ok=False with a descriptive reason.
    """
    if not patch_path.exists() or patch_path.stat().st_size == 0:
        return True, ""

    raw = patch_path.read_text(encoding="utf-8")
    normalized = _normalize_patch_paths(raw)
    normalized_path = patch_path.with_suffix(patch_path.suffix + ".normalized")
    normalized_path.write_text(normalized, encoding="utf-8")

    args = ["git", "apply"]
    if check_only:
        args.append("--check")
    args.extend(["-p1", "--unsafe-paths", str(normalized_path.resolve())])

    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            cwd=str(skill_dir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return False, "git binary not found; cannot apply patches"
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=20.0)
    except TimeoutError:
        proc.kill()
        return False, "git apply timed out after 20s"
    if proc.returncode == 0:
        return True, ""
    err = (
        stderr.decode("utf-8", errors="replace").strip()
        or stdout.decode("utf-8", errors="replace").strip()
        or f"git apply exit={proc.returncode}"
    )
    return False, err


def _next_version_id(prev_version: str | None) -> str:
    """Same vN counter the lifespan boot uses (main._next_version_id).

    Duplicated here so apply.py doesn't import main (which pulls in
    FastAPI + the whole app graph at import time)."""
    if not prev_version or not prev_version.startswith("v"):
        return "v1"
    try:
        n = int(prev_version[1:])
        return f"v{n + 1}"
    except ValueError:
        return "v1"


def _live_signature(skill_name: str) -> str:
    try:
        text, _refs = load_skill_prompt(skill_name)
    except FileNotFoundError:
        return "unknown"
    return compute_signature(text)


async def _record_skill_version(
    skill_name: str,
    *,
    evolution_store: EvolutionStore,
    proposal_id: str,
    parent_signature: str | None,
) -> SkillVersion:
    """Append a SkillVersion to the evolution store reflecting the post-
    apply prompt + signature, with the proposal stamped onto params for
    forensics."""
    skill = default_skills.get(skill_name)
    sig = skill.current_signature() or {}
    # current_signature() is what the in-memory skill reports — for skills
    # that don't implement it, fall back to (prompt, tool_names, model)
    # populated from the freshly-reloaded skill instance.
    prompt_text, _refs = load_skill_prompt(skill_name)
    sig = {
        "prompt": sig.get("prompt") or prompt_text,
        "tool_names": list(sig.get("tool_names") or getattr(skill, "DEFAULT_TOOLS", [])),
        "model": str(sig.get("model") or getattr(skill, "DEFAULT_MODEL", "") or ""),
        "params": {
            **(sig.get("params") or {}),
            # Stamp the apply provenance onto params so listing versions
            # immediately reveals "this version came from P-2026-XYZ".
            "applied_from_proposal": proposal_id,
            "parent_signature": parent_signature,
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


def _reload_skill_prompt(skill_name: str) -> None:
    """Mirror api/admin.reload_skills for a single skill.

    Reloads SKILL.md + references from disk, clears the loader cache,
    and rebinds ``skill.system_prompt`` / ``skill.refs`` so the live skill
    instance picks up the change without an API restart."""
    load_skill_prompt.cache_clear()
    try:
        skill = default_skills.get(skill_name)
    except KeyError:
        return  # skill isn't registered — nothing to reload
    if not hasattr(skill, "system_prompt"):
        return
    try:
        new_text, new_refs = load_skill_prompt(skill_name)
    except FileNotFoundError:
        return
    skill.system_prompt = new_text
    skill.refs = new_refs


def _capture_post_apply(skill_dir: Path, post_apply_dir: Path) -> None:
    """Freeze the post-apply SKILL.md + references for rollback (M1.8).

    Same layout as the snapshot/skill/ tree so a rollback can copytree
    snapshot/skill/ → post_apply/ → live just by swapping pointers.
    """
    post_apply_dir.mkdir(parents=True, exist_ok=True)
    if not skill_dir.exists():
        return
    dst = post_apply_dir / "skill"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(skill_dir, dst)


# ── Public entry point ─────────────────────────────────────────────


async def apply_proposal(
    proposal_id: str,
    *,
    store: ProposalStore | None = None,
    evolution_store: EvolutionStore | None = None,
    skill_root: Path | None = None,
) -> ApplyResult:
    """Drive a proposal from ``accepted`` → ``a_b_eval`` (or apply_failed).

    Refuses if the proposal isn't in ``accepted`` — apply is meant to be
    invoked exactly once, by the operator's G1 acceptance.

    On apply failure: writes the error reason onto the apply_failed
    transition extra, leaves the live SKILL.md untouched (git apply is
    atomic — failed checks don't half-write), and returns ok=False.

    On success: live SKILL.md updated, post_apply/ written, SkillVersion
    recorded, proposal at a_b_eval, ``applied_skill_signature`` stamped.
    """
    pstore = store or default_proposal_store
    estore = evolution_store or default_evolution_store
    sroot = skill_root or _default_skill_root()
    started = time.time()

    proposal: Proposal = pstore.get(proposal_id)
    if proposal.status != "accepted":
        raise ValueError(
            f"apply: proposal {proposal_id} is {proposal.status}, expected accepted"
        )

    proposal_dir = pstore._dir(proposal_id)  # noqa: SLF001
    patch_path = proposal_dir / "cc_run" / "patch.diff"
    skill_dir = _skill_dir(sroot, proposal.source_skill)

    # ── applying ─────────────────────────────────────────────────
    pstore.transition(proposal_id, "applying", by="system:apply")

    patch_text = patch_path.read_text(encoding="utf-8") if patch_path.exists() else ""
    patch_is_empty = not patch_text.strip()

    if not patch_is_empty:
        check_ok, check_err = await _git_apply(patch_path, skill_dir, check_only=True)
        if not check_ok:
            pstore.transition(
                proposal_id,
                "apply_failed",
                by="system:apply",
                reason=f"check failed: {check_err[:200]}",
            )
            return ApplyResult(
                proposal_id=proposal_id,
                ok=False,
                final_status="apply_failed",
                error=check_err,
                duration_s=time.time() - started,
                patch_was_empty=False,
            )
        apply_ok, apply_err = await _git_apply(
            patch_path, skill_dir, check_only=False
        )
        if not apply_ok:
            pstore.transition(
                proposal_id,
                "apply_failed",
                by="system:apply",
                reason=f"apply failed: {apply_err[:200]}",
            )
            return ApplyResult(
                proposal_id=proposal_id,
                ok=False,
                final_status="apply_failed",
                error=apply_err,
                duration_s=time.time() - started,
                patch_was_empty=False,
            )

    # ── post-apply housekeeping ─────────────────────────────────
    post_apply_dir = proposal_dir / "post_apply"
    _capture_post_apply(skill_dir, post_apply_dir)
    _reload_skill_prompt(proposal.source_skill)
    new_signature = _live_signature(proposal.source_skill)
    (post_apply_dir / "signature").write_text(new_signature, encoding="utf-8")

    version = await _record_skill_version(
        proposal.source_skill,
        evolution_store=estore,
        proposal_id=proposal_id,
        parent_signature=proposal.snapshot_skill_signature,
    )

    # Stamp the resulting signature onto the proposal so /show + audit
    # trail can answer "what signature did this proposal produce?"
    proposal = pstore.get(proposal_id)
    proposal.applied_skill_signature = new_signature
    pstore._persist(proposal)  # noqa: SLF001

    # ── a_b_eval ────────────────────────────────────────────────
    pstore.transition(
        proposal_id,
        "a_b_eval",
        by="system:apply",
        extra={
            "new_version": version.version,
            "applied_signature": new_signature,
            "patch_was_empty": patch_is_empty,
        },
    )
    logger.info(
        "applied %s: skill=%s version=%s sig=%s empty=%s",
        proposal_id,
        proposal.source_skill,
        version.version,
        new_signature,
        patch_is_empty,
    )
    return ApplyResult(
        proposal_id=proposal_id,
        ok=True,
        final_status="a_b_eval",
        new_version=version.version,
        applied_signature=new_signature,
        duration_s=time.time() - started,
        patch_was_empty=patch_is_empty,
    )


# Re-export the helpers tests want to poke at.
__all__ = [
    "ApplyResult",
    "apply_proposal",
]


# Helpers exposed for tests via attribute access (so monkeypatch can
# stub them out individually).
def _helpers_for_test() -> dict[str, Any]:
    return {
        "_git_apply": _git_apply,
        "_next_version_id": _next_version_id,
        "_live_signature": _live_signature,
        "_record_skill_version": _record_skill_version,
        "_reload_skill_prompt": _reload_skill_prompt,
        "_capture_post_apply": _capture_post_apply,
    }
