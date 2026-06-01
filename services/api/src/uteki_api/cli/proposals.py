"""proposals — G1 review CLI for the self-evolution loop (M1.5).

The operator-facing entry point for the loop documented in
``design/02-self-evolution-loop.md``. Reads ``data/evolution/proposals/``
directly (same on-disk truth the API writes), so review works whether or
not the FastAPI process is running.

Subcommands::

    proposals list      [--status pending_review] [--skill X] [--limit N]
    proposals show      <P-id>
    proposals accept    <P-id> [--reason "..."]
    proposals reject    <P-id> [--reason "..."]
    proposals defer     <P-id> [--reason "..."]
    proposals discard   <P-id> [--reason "..."]

``list`` (with no args, or no subcommand at all) is the default — the
"3 proposals pending your review" view from the design demo.

Decisions are full state transitions persisted by the same ProposalStore
the API uses, so the audit trail is unified across CLI + HTTP origins.
The 'by' field of each transition includes the OS user (``$USER``) so a
shared host's audit log is interpretable.
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

from uteki_api.evolution.proposals.models import Proposal, ProposalStatus
from uteki_api.evolution.proposals.store import ProposalStore


def _discover_default_root() -> Path:
    """Find services/api/data/evolution/proposals/ relative to this file.

    We deliberately don't reuse the import-time ``default_proposal_store``
    singleton — its root is resolved against the cwd at module-import
    time, which for the CLI is wherever the operator launched the
    wrapper from. Walking up from ``__file__`` gives a stable answer.
    """
    pkg_root = Path(__file__).resolve()
    # .../services/api/src/uteki_api/cli/proposals.py
    #     ^^^^^^^^^^^^^^^                          ^^
    # parents[2] = uteki_api  ; parents[4] = services/api
    services_api = pkg_root.parents[4]
    return services_api / "data" / "evolution" / "proposals"

# ── tiny color helpers (no external deps) ────────────────────────────


def _supports_color() -> bool:
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("UTEKI_CLI_NO_COLOR"):
        return False
    return sys.stdout.isatty()


_COLORS = {
    "reset": "\x1b[0m",
    "dim": "\x1b[2m",
    "bold": "\x1b[1m",
    "red": "\x1b[31m",
    "green": "\x1b[32m",
    "yellow": "\x1b[33m",
    "blue": "\x1b[34m",
    "magenta": "\x1b[35m",
    "cyan": "\x1b[36m",
}


def _c(name: str, text: str) -> str:
    if not _supports_color():
        return text
    return f"{_COLORS[name]}{text}{_COLORS['reset']}"


_STATUS_COLOR = {
    "pending_review": "yellow",
    "invalidated": "red",
    "apply_failed": "red",
    "rejected": "dim",
    "discarded": "dim",
    "deferred": "dim",
    "adopted": "green",
    "rolled_back": "magenta",
    "inconclusive": "magenta",
}


def _status_pretty(s: str) -> str:
    color = _STATUS_COLOR.get(s, "cyan")
    return _c(color, s)


# ── rendering helpers ───────────────────────────────────────────────


def _proposal_dir(store: ProposalStore, proposal_id: str) -> Path:
    # ProposalStore exposes private _dir but it's the canonical "where do
    # the side-files live" — the CLI uses it intentionally rather than
    # re-deriving the path from store._root + id.
    return store._dir(proposal_id)  # noqa: SLF001


def _load_validation(proposal_dir: Path) -> dict[str, Any] | None:
    path = proposal_dir / "validation.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _critique_excerpt(proposal_dir: Path, *, max_findings: int = 4) -> list[str]:
    """Return up to ``max_findings`` finding titles from critique.md.

    Returns the literal ``### `` heading lines without the marker. Empty
    list if critique is missing or has no level-3 headings."""
    critique_path = proposal_dir / "cc_run" / "critique.md"
    if not critique_path.exists():
        return []
    excerpts: list[str] = []
    for line in critique_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            excerpts.append(line[4:].strip())
            if len(excerpts) >= max_findings:
                break
    return excerpts


def _format_age(ts: float) -> str:
    import time as _time
    delta = max(0, int(_time.time() - ts))
    if delta < 60:
        return f"{delta}s ago"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return f"{delta // 86400}d ago"


def _render_list(items: list[Proposal], store: ProposalStore) -> str:
    if not items:
        return _c("dim", "No proposals match.")
    lines: list[str] = []
    # Build the header with padded column titles, then bold the whole row.
    header_raw = (
        f"{'ID':<14} {'STATUS':<18} {'SKILL':<22} {'AGE':<10} {'FINDINGS':<10} PATCH +/-"
    )
    lines.append(_c("bold", header_raw))
    lines.append(_c("dim", "─" * 90))
    for p in items:
        pdir = _proposal_dir(store, p.proposal_id)
        v = _load_validation(pdir) or {}
        stats = v.get("stats", {})
        finding_count = stats.get("critique_finding_count", "—")
        patch_plus = stats.get("patch_lines_added", "—")
        patch_minus = stats.get("patch_lines_removed", "—")
        # Pad each cell against its visible width, then color the status cell
        # last so ANSI codes don't throw off alignment.
        status_padded = f"{p.status:<18}"
        lines.append(
            f"{p.proposal_id:<14} "
            f"{_status_pretty(status_padded)} "
            f"{p.source_skill:<22} "
            f"{_format_age(p.updated_at):<10} "
            f"{str(finding_count):<10} "
            f"+{patch_plus}/-{patch_minus}"
        )
    return "\n".join(lines)


def _render_show(proposal: Proposal, store: ProposalStore) -> str:
    pdir = _proposal_dir(store, proposal.proposal_id)
    v = _load_validation(pdir) or {}
    findings = _critique_excerpt(pdir, max_findings=6)

    out: list[str] = []
    title = f"{proposal.proposal_id}  ·  {proposal.source_skill}"
    out.append(_c("bold", title))
    out.append(_c("dim", "─" * len(title)))
    out.append(f"Status         {_status_pretty(proposal.status)}")
    out.append(f"Source run     {proposal.source_run_id}")
    out.append(f"Owner          {proposal.source_user_id}")
    if proposal.snapshot_skill_signature:
        out.append(f"Snapshot sig   {proposal.snapshot_skill_signature}")
    out.append(f"Created        {_format_age(proposal.created_at)}")
    out.append(f"Updated        {_format_age(proposal.updated_at)}")

    out.append("")
    out.append(_c("bold", "Validation"))
    if not v:
        out.append(_c("dim", "  (no validation.json yet)"))
    else:
        ok = v.get("ok")
        out.append(f"  ok            {_c('green' if ok else 'red', str(ok))}")
        for r in v.get("reasons", []):
            out.append(_c("red", f"  · {r}"))
        stats = v.get("stats", {})
        out.append(
            f"  patch         +{stats.get('patch_lines_added', 0)}"
            f"/-{stats.get('patch_lines_removed', 0)}  "
            f"({stats.get('patch_file_count', 0)} files, "
            f"applies={stats.get('patch_applies', '?')})"
        )
        out.append(
            f"  critique      {stats.get('critique_bytes', 0)} bytes, "
            f"{stats.get('critique_finding_count', 0)} finding(s)"
        )

    out.append("")
    out.append(_c("bold", f"Findings (top {len(findings)})"))
    if not findings:
        out.append(_c("dim", "  (no level-3 headings in critique.md)"))
    for f in findings:
        out.append(f"  • {f}")

    out.append("")
    out.append(_c("bold", "Files"))
    candidates = [
        ("brief.md", pdir / "brief.md"),
        ("critique.md", pdir / "cc_run" / "critique.md"),
        ("patch.diff", pdir / "cc_run" / "patch.diff"),
        ("validation.json", pdir / "validation.json"),
    ]
    for label, path in candidates:
        if path.exists():
            out.append(f"  {label:<16} {path}")

    out.append("")
    out.append(_c("bold", f"Transition trail ({len(proposal.transitions)})"))
    for i, t in enumerate(proposal.transitions, 1):
        reason = f"  — {t.reason}" if t.reason else ""
        status_cell = _status_pretty(f"{t.to:<22}")
        by_cell = _c("dim", f"{t.by:<28}")
        out.append(f"  {i:>3}. {status_cell} {by_cell}{reason}")

    return "\n".join(out)


# ── subcommand handlers ─────────────────────────────────────────────


def _cmd_list(args: argparse.Namespace, store: ProposalStore) -> int:
    status_filter: ProposalStatus | None = args.status if args.status else None
    items = store.list(
        status=status_filter,
        source_skill=args.skill,
        limit=args.limit,
    )
    if status_filter is None and args.show_all is False:
        # Default ergonomic: hide terminal noise unless the user opts in.
        items = [p for p in items if not p.is_terminal]

    print(_render_list(items, store))

    if status_filter == "pending_review" or status_filter is None:
        pending = [p for p in items if p.status == "pending_review"]
        if pending:
            print()
            print(_c(
                "dim",
                f"{len(pending)} proposal(s) pending your review. "
                f"Use 'proposals show <P-id>' for details, "
                f"'proposals accept/reject <P-id> --reason \"...\"' to decide.",
            ))
    return 0


def _cmd_show(args: argparse.Namespace, store: ProposalStore) -> int:
    try:
        proposal = store.get(args.proposal_id)
    except KeyError:
        print(_c("red", f"unknown proposal: {args.proposal_id}"), file=sys.stderr)
        return 2
    print(_render_show(proposal, store))
    return 0


def _operator_by() -> str:
    # Tie CLI decisions to a stable operator id for the audit trail. Falls
    # back to a literal so the field is never blank.
    user = os.environ.get("UTEKI_OPERATOR") or getpass.getuser() or "operator"
    return f"cli:{user}"


def _cmd_decision(
    args: argparse.Namespace, store: ProposalStore, to_status: ProposalStatus
) -> int:
    try:
        proposal = store.get(args.proposal_id)
    except KeyError:
        print(_c("red", f"unknown proposal: {args.proposal_id}"), file=sys.stderr)
        return 2

    if proposal.status != "pending_review":
        print(
            _c(
                "red",
                f"refusing {to_status}: {args.proposal_id} is {proposal.status}, "
                "expected pending_review",
            ),
            file=sys.stderr,
        )
        return 3

    try:
        updated = store.transition(
            args.proposal_id, to_status, by=_operator_by(), reason=args.reason or ""
        )
    except ValueError as e:
        print(_c("red", str(e)), file=sys.stderr)
        return 4

    print(
        f"{args.proposal_id}: {_c('bold', 'pending_review')} → "
        f"{_status_pretty(to_status)}"
    )
    if args.reason:
        print(_c("dim", f"  reason: {args.reason}"))
    print(_c("dim", f"  by:     {updated.transitions[-1].by}"))

    # accept triggers apply inline so the operator sees "applied OK" in
    # the same command — matches the design demo's "Applying patch...  OK"
    # line. Other decisions (reject/defer/discard) are terminal in M1.5.
    if to_status == "accepted" and not args.no_apply:
        also_ab = not getattr(args, "no_ab", False)
        return _run_apply(args.proposal_id, store, also_ab=also_ab)
    return 0


def _run_apply(
    proposal_id: str, store: ProposalStore, *, also_ab: bool = True
) -> int:
    """Drive apply_proposal inline. Optionally chain into ab_eval.

    Returns the worst exit code of (apply, ab_eval if attempted).
    """
    # Lazy-import to avoid pulling the apply graph (and its FastAPI-adjacent
    # singletons) into 'proposals list' / 'show' invocations.
    import asyncio as _asyncio

    from uteki_api.evolution.apply import apply_proposal

    print(_c("dim", "  applying patch..."))
    try:
        result = _asyncio.run(apply_proposal(proposal_id, store=store))
    except Exception as e:  # noqa: BLE001 — surface to the operator + log
        print(_c("red", f"  apply crashed: {e}"), file=sys.stderr)
        return 5

    if not result.ok:
        print(_c("red", f"  apply failed: {result.error}"), file=sys.stderr)
        return 6
    suffix = " (no-op — empty patch)" if result.patch_was_empty else ""
    print(
        _c("green", "  apply OK")
        + _c("dim", f"  version={result.new_version}  signature={result.applied_signature}{suffix}")
    )

    if also_ab:
        return _run_ab_eval(proposal_id, store)
    return 0


def _run_ab_eval(proposal_id: str, store: ProposalStore) -> int:
    """Drive run_ab_eval inline. Prints baseline/proposed pass-rates + delta.

    M1.7 demo text matches design/05 Phase 1's mockup:
        Running A/B (mock-llm, N cases)...
          baseline:  pass_rate=0.42
          proposed:  pass_rate=0.78  ↑ +36.0pp
    """
    import asyncio as _asyncio

    from uteki_api.core.config import settings as _settings
    from uteki_api.evolution.ab_eval import run_ab_eval

    mode = "mock-llm" if _settings.use_mock_llm else "real-llm"
    print(_c("dim", f"  running A/B ({mode}, full eval suite)..."))
    try:
        result = _asyncio.run(run_ab_eval(proposal_id, store=store))
    except ValueError as e:
        # ValueError = predictable contract violation (wrong status,
        # missing snapshot, double-run). Surface but don't crash.
        print(_c("red", f"  A/B refused: {e}"), file=sys.stderr)
        return 7
    except Exception as e:  # noqa: BLE001 — surface, don't crash CLI
        print(_c("red", f"  A/B crashed: {e}"), file=sys.stderr)
        return 8

    if not result.ok:
        print(_c("red", f"  A/B failed: {result.error}"), file=sys.stderr)
        return 9
    s = result.ab_summary
    delta_color = "green" if s["delta_pp"] >= 0 else "red"
    arrow = "↑" if s["delta_pp"] >= 0 else "↓"
    print(
        _c("dim", f"  baseline:  pass_rate={s['pass_rate_baseline']:.2f}")
    )
    print(
        _c("dim", f"  proposed:  pass_rate={s['pass_rate_proposed']:.2f}  ")
        + _c(delta_color, f"{arrow} {s['delta_pp']:+.1f}pp")
        + _c("dim", f"  ({s['cases_run']} cases)")
    )
    # Hint about G2 — M1.8 will plumb the operator decision verbs.
    print(_c(
        "dim",
        "  next: review with 'proposals show <P-id>' then "
        "'proposals adopt / rollback' (M1.8)"
    ))
    return 0


# ── argparse wiring ─────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="proposals",
        description="G1 review CLI for the self-evolution loop.",
    )
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help=(
            "Override the proposals root directory "
            "(default: services/api/data/evolution/proposals, "
            "resolved relative to CWD)."
        ),
    )

    sub = p.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="List proposals (default: non-terminal).")
    p_list.add_argument(
        "--status",
        choices=[
            "triggered", "snapshotting", "briefing", "spawning", "generating",
            "validating", "invalidated", "pending_review", "accepted",
            "rejected", "deferred", "edit_then_apply", "discarded",
            "applying", "apply_failed", "a_b_eval", "adopted", "rolled_back",
            "inconclusive",
        ],
        default=None,
    )
    p_list.add_argument("--skill", default=None, help="Filter by source skill.")
    p_list.add_argument("--limit", type=int, default=50)
    p_list.add_argument(
        "--all",
        dest="show_all",
        action="store_true",
        help="Include terminal-status proposals (rejected/adopted/etc).",
    )

    p_show = sub.add_parser("show", help="Show full detail of one proposal.")
    p_show.add_argument("proposal_id")

    for verb, status in (
        ("accept", "accepted"),
        ("reject", "rejected"),
        ("defer", "deferred"),
        ("discard", "discarded"),
    ):
        p_act = sub.add_parser(verb, help=f"Transition a pending_review proposal to {status}.")
        p_act.add_argument("proposal_id")
        p_act.add_argument("--reason", "-r", default="", help="Audit-log reason text.")
        # accept fires apply automatically; --no-apply leaves the proposal
        # parked at 'accepted' so the operator can hand-edit patch.diff,
        # then run `proposals apply` (or re-run accept without the flag).
        p_act.add_argument(
            "--no-apply",
            action="store_true",
            help="(accept only) Don't auto-apply; leave proposal at 'accepted'.",
        )
        p_act.add_argument(
            "--no-ab",
            action="store_true",
            help="(accept only) Apply but skip the auto A/B eval afterwards.",
        )
        p_act.set_defaults(_decision_status=status, no_apply=False, no_ab=False)

    p_apply = sub.add_parser(
        "apply",
        help="Apply an already-accepted proposal (e.g. after editing patch.diff).",
    )
    p_apply.add_argument("proposal_id")
    p_apply.add_argument(
        "--no-ab",
        action="store_true",
        help="Skip the auto A/B eval after apply succeeds.",
    )

    p_ab = sub.add_parser(
        "ab-eval",
        help=(
            "Run A/B eval against an a_b_eval proposal (re-run after a "
            "failed earlier attempt; refuses if ab_summary already exists)."
        ),
    )
    p_ab.add_argument("proposal_id")

    for verb in ("adopt", "rollback", "inconclusive"):
        p_g2 = sub.add_parser(
            verb,
            help=f"G2 terminal decision: transition a_b_eval proposal to {verb}.",
        )
        p_g2.add_argument("proposal_id")
        p_g2.add_argument(
            "--reason", "-r", default="", help="Audit-log reason text."
        )
        p_g2.set_defaults(_g2_verb=verb)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    # Ensure the SQLite tables EvalRunner needs exist. The API's lifespan
    # normally bootstraps this, but the CLI may run when the API hasn't
    # touched the DB yet (or against a fresh checkout). Idempotent and
    # cheap (CREATE TABLE IF NOT EXISTS).
    try:
        from uteki_api.core.db import init_db
        init_db()
    except Exception:  # noqa: BLE001 — best-effort; ab-eval will surface real errors
        pass

    # Default 'no subcommand' to 'list' so the demo invocation
    # ``proposals`` and ``proposals list`` both work.
    if args.cmd is None:
        args.cmd = "list"
        # The list parser had defaults — replicate them since we didn't
        # actually go through it.
        args.status = None
        args.skill = None
        args.limit = 50
        args.show_all = False

    root = args.root if args.root is not None else _discover_default_root()
    store = ProposalStore(root)

    if args.cmd == "list":
        return _cmd_list(args, store)
    if args.cmd == "show":
        return _cmd_show(args, store)
    if args.cmd in {"accept", "reject", "defer", "discard"}:
        return _cmd_decision(args, store, args._decision_status)  # noqa: SLF001
    if args.cmd == "apply":
        try:
            proposal = store.get(args.proposal_id)
        except KeyError:
            print(_c("red", f"unknown proposal: {args.proposal_id}"), file=sys.stderr)
            return 2
        if proposal.status != "accepted":
            print(
                _c(
                    "red",
                    f"refusing apply: {args.proposal_id} is {proposal.status}, "
                    "expected accepted (use `accept` first, or `accept --no-apply` "
                    "then edit patch.diff and `apply`)",
                ),
                file=sys.stderr,
            )
            return 3
        return _run_apply(args.proposal_id, store, also_ab=not args.no_ab)
    if args.cmd == "ab-eval":
        try:
            proposal = store.get(args.proposal_id)
        except KeyError:
            print(_c("red", f"unknown proposal: {args.proposal_id}"), file=sys.stderr)
            return 2
        if proposal.status != "a_b_eval":
            print(
                _c(
                    "red",
                    f"refusing ab-eval: {args.proposal_id} is {proposal.status}, "
                    "expected a_b_eval (apply must have succeeded first)",
                ),
                file=sys.stderr,
            )
            return 3
        return _run_ab_eval(args.proposal_id, store)
    if args.cmd in {"adopt", "rollback", "inconclusive"}:
        return _run_g2(args, store)
    parser.print_help()
    return 1


def _run_g2(args: argparse.Namespace, store: ProposalStore) -> int:
    """Drive a G2 decision (adopt / rollback / inconclusive) inline."""
    import asyncio as _asyncio

    from uteki_api.evolution.g2 import (
        adopt_proposal,
        inconclusive_proposal,
        rollback_proposal,
    )

    verb: str = args._g2_verb  # noqa: SLF001
    try:
        proposal = store.get(args.proposal_id)
    except KeyError:
        print(_c("red", f"unknown proposal: {args.proposal_id}"), file=sys.stderr)
        return 2

    # Pre-flight the most common operator mistake — running G2 before A/B
    # has populated ab_summary. The async functions guard this too, but
    # exiting here with code 3 (wrong status) matches the rest of the CLI.
    if proposal.status != "a_b_eval":
        print(
            _c(
                "red",
                f"refusing {verb}: {args.proposal_id} is {proposal.status}, "
                "expected a_b_eval",
            ),
            file=sys.stderr,
        )
        return 3
    if not proposal.ab_summary:
        print(
            _c(
                "red",
                f"refusing {verb}: {args.proposal_id} has no ab_summary yet — "
                "run 'proposals ab-eval' first",
            ),
            file=sys.stderr,
        )
        return 3

    by = _operator_by()
    try:
        if verb == "adopt":
            result = _asyncio.run(
                adopt_proposal(args.proposal_id, by=by, reason=args.reason, store=store)
            )
        elif verb == "rollback":
            result = _asyncio.run(
                rollback_proposal(
                    args.proposal_id, by=by, reason=args.reason, store=store
                )
            )
        else:  # inconclusive
            result = _asyncio.run(
                inconclusive_proposal(
                    args.proposal_id, by=by, reason=args.reason, store=store
                )
            )
    except ValueError as e:
        print(_c("red", str(e)), file=sys.stderr)
        return 4
    except Exception as e:  # noqa: BLE001 — surface, don't crash
        print(_c("red", f"  {verb} crashed: {e}"), file=sys.stderr)
        return 10

    print(
        f"{args.proposal_id}: {_c('bold', 'a_b_eval')} → "
        f"{_status_pretty(result.final_status)}"
    )
    if args.reason:
        print(_c("dim", f"  reason: {args.reason}"))
    print(_c("dim", f"  by:     {by}"))
    if result.new_version:
        print(_c("dim", f"  new_version: {result.new_version}"))
    if result.live_signature:
        print(_c("dim", f"  live_signature: {result.live_signature}"))
    if verb == "rollback":
        print(_c("green", "  live SKILL.md reverted to baseline"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
