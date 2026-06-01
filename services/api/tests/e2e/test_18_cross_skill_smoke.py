"""T18 — cross-skill smoke (M1.12).

Verifies the self-evolution loop is skill-agnostic by walking the full
pipeline (create → cc_runner → accept → apply → ab_eval → adopt) for
three different skills (``research``, ``earnings``, ``planner``) and
asserting each lands at ``adopted`` with its own EvolutionStore version.

This closes Phase 1's task 1.12 acceptance: "3 个不同 skill 走完整闭环".

Why these three:
- ``research`` — leaf skill, the canonical test target since M1.1.
- ``earnings`` — different leaf skill with its own SKILL.md + references.
- ``planner`` — leaf skill with no DEFAULT_TOOLS, simpler signature.

Pipeline skills (``research_pipeline``, ``company_research_pipeline``)
are out of scope: they need fanout from sub-skills and ab_eval doesn't
make sense at the pipeline level for a single mock-llm run. Leaf skills
are enough to prove the contract isn't research-specific.

Mock-llm mode keeps the test hermetic and < 30s:
- ``cc_runner`` synthesizes empty patch (M1.3 mock backend)
- ``apply`` is a trivial no-op success on empty patch
- ``ab_eval`` swaps + runs EvalRunner against the project's real eval
  cases (which target research) — for non-research skills the swap is
  a no-op as far as those cases see, but the pipeline still walks and
  ab_summary lands populated, which is what 'smoke' tests.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from .conftest import Reporter
from .test_15_ab_eval import _accept, _apply_only


async def _seed_for_skill(root: Path, skill: str, label: str) -> str:
    """Seed a fresh pending_review proposal targeting ``skill``.

    Mirrors _seed_with_snapshot from T15 but parameterised on skill so
    each test iteration gets its own SKILL.md snapshot (apply needs a
    baseline to copy from)."""
    from uteki_api.evolution.apply import _default_skill_root
    from uteki_api.evolution.proposals.store import ProposalStore
    from uteki_api.runs import Run, default_run_store
    from uteki_api.schemas.events import AgentEvent

    rid = f"t18-{skill}-{label}"

    # Run record — needed by apply (to know which skill to mutate) and
    # by the artifact store (snapshot/run_artifacts/ copy is keyed off
    # the run id).
    await default_run_store.create(
        Run(
            id=rid, user_id=label, skill=skill, triggered_by="user",
            started_at=time.time(),
        )
    )
    await default_run_store.append_event(
        rid, AgentEvent(type="delta", run_id=rid, data={"text": "seed"})
    )
    await default_run_store.finish(rid, "ok", f"t18 {skill}")

    # _seed_pending defaults to skill='research'; we need the proposal
    # to target the right skill. Inline that helper with the skill
    # parameter substituted.
    from uteki_api.artifacts import default_artifact_store
    store = ProposalStore(root)
    proposal = store.create(
        source_run_id=rid,
        source_skill=skill,
        source_user_id=label,
        triggered_by="system:t18",
        trigger_reason="cross-skill smoke",
    )
    # Walk through the cc_runner-style transitions so the proposal looks
    # like what the real cc_runner would leave behind.
    for s in (
        "snapshotting", "briefing", "spawning", "generating",
        "validating", "pending_review",
    ):
        store.transition(proposal.proposal_id, s, by="system:cc_runner")  # type: ignore[arg-type]

    # Sidecars: critique + validation, plus the baseline snapshot apply
    # needs and the artifact apply will reference.
    pdir = root / proposal.proposal_id
    (pdir / "cc_run").mkdir(parents=True, exist_ok=True)
    (pdir / "snapshot" / "skill").mkdir(parents=True, exist_ok=True)
    live_skill = _default_skill_root() / skill / "SKILL.md"
    (pdir / "snapshot" / "skill" / "SKILL.md").write_text(
        live_skill.read_text(encoding="utf-8"), encoding="utf-8",
    )
    (pdir / "cc_run" / "critique.md").write_text(
        f"# critique — {skill}\n\n"
        "### Finding #1: smoke finding A\n"
        "### Finding #2: smoke finding B\n",
        encoding="utf-8",
    )
    (pdir / "cc_run" / "patch.diff").write_text("", encoding="utf-8")
    import json as _json
    (pdir / "validation.json").write_text(_json.dumps({
        "ok": True, "reasons": [],
        "stats": {
            "critique_finding_count": 2,
            "patch_lines_added": 0, "patch_lines_removed": 0,
            "patch_lines_total": 0, "patch_file_count": 0,
            "patch_applies": True,
            "critique_bytes": 200, "patch_bytes": 0,
        },
        "checked_at": 0.0,
    }), encoding="utf-8")

    # Seed an artifact so the snapshot run_artifacts/ isn't empty.
    await default_artifact_store.write(
        run_id=rid, user_id=label, name="final-report.md",
        content=f"# {skill} smoke report\nLine X claims something.\n",
        kind="markdown", written_by=skill, description="t18 seed",
    )
    return proposal.proposal_id


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "skill_name",
    ["research", "earnings", "planner"],
    ids=["research", "earnings", "planner"],
)
async def test_full_loop_per_skill(
    client, tmp_path: Path, reporter: Reporter, skill_name: str
) -> None:
    """One full loop per skill in an isolated tmp dir."""
    from uteki_api.evolution.ab_eval import run_ab_eval
    from uteki_api.evolution.g2 import adopt_proposal
    from uteki_api.evolution.proposals.store import ProposalStore

    root = tmp_path / "proposals"

    reporter.section(f"seed pending_review for skill={skill_name}")
    p1 = await _seed_for_skill(root, skill_name, label="t18")
    reporter.kv("proposal_id", p1)

    reporter.section("G1 accept + apply")
    _accept(root, p1, by="cli:t18")
    await _apply_only(root, p1)
    final_after_apply = ProposalStore(root).get(p1)
    assert final_after_apply.status == "a_b_eval"
    assert final_after_apply.applied_skill_signature
    reporter.kv("applied_signature", final_after_apply.applied_skill_signature)

    reporter.section("A/B eval")
    ab_result = await run_ab_eval(p1, store=ProposalStore(root))
    assert ab_result.ok, f"ab_eval failed: {ab_result.error}"
    reporter.kv("ab.cases_run", ab_result.ab_summary["cases_run"])
    reporter.kv("ab.delta_pp", ab_result.ab_summary["delta_pp"])

    reporter.section("G2 adopt")
    adopt_result = await adopt_proposal(
        p1, by="cli:t18", reason="smoke adopt",
        store=ProposalStore(root),
    )
    assert adopt_result.ok
    final = ProposalStore(root).get(p1)
    reporter.kv("final status", final.status)
    assert final.status == "adopted"
    assert final.is_terminal

    reporter.section("transitions walked every milestone")
    walked = {t.to for t in final.transitions}
    for mile in ("triggered", "pending_review", "accepted",
                 "applying", "a_b_eval", "adopted"):
        assert mile in walked, f"{skill_name}: missing {mile} in {walked}"

    reporter.end()


@pytest.mark.asyncio
async def test_three_skills_independent_in_same_root(
    client, tmp_path: Path, reporter: Reporter
) -> None:
    """Walking the loop sequentially for 3 skills in one ProposalStore
    produces 3 distinct adopted proposals with 3 distinct SkillVersions
    in EvolutionStore — no cross-skill collision."""
    from uteki_api.evolution.ab_eval import run_ab_eval
    from uteki_api.evolution.apply import apply_proposal
    from uteki_api.evolution.g2 import adopt_proposal
    from uteki_api.evolution.proposals.store import ProposalStore
    from uteki_api.evolution.store import InMemoryEvolutionStore

    root = tmp_path / "proposals"
    fresh_evo = InMemoryEvolutionStore()
    adopted_pids: list[tuple[str, str, str]] = []  # (skill, P-id, version)

    skills = ["research", "earnings", "planner"]
    reporter.section(f"walk full loop for {len(skills)} skills sequentially")
    for skill in skills:
        pid = await _seed_for_skill(root, skill, label=skill)
        _accept(root, pid, by="cli:t18")
        apply_result = await apply_proposal(
            pid, store=ProposalStore(root), evolution_store=fresh_evo,
        )
        assert apply_result.ok, f"{skill} apply failed: {apply_result.error}"
        ab = await run_ab_eval(pid, store=ProposalStore(root))
        assert ab.ok, f"{skill} ab_eval failed: {ab.error}"
        g2 = await adopt_proposal(
            pid, by="cli:t18", reason=f"smoke {skill}",
            store=ProposalStore(root),
        )
        assert g2.ok
        adopted_pids.append((skill, pid, apply_result.new_version))
        reporter.event(f"{skill}", f"{pid} → adopted (version={apply_result.new_version})")

    reporter.section("3 distinct adopted proposals on disk")
    final_store = ProposalStore(root)
    statuses = [final_store.get(p).status for _, p, _ in adopted_pids]
    assert statuses == ["adopted", "adopted", "adopted"], (
        f"expected 3x adopted, got {statuses}"
    )
    assert len({p for _, p, _ in adopted_pids}) == 3, "proposal ids collided"

    reporter.section("EvolutionStore has independent version histories")
    for skill, _, version in adopted_pids:
        versions = await fresh_evo.list(skill)
        reporter.event(skill, f"{[v.version for v in versions]}")
        assert versions, f"{skill}: no SkillVersion recorded"
        # Each skill's latest version should equal the one apply assigned.
        assert versions[0].version == version, (
            f"{skill}: EvolutionStore latest={versions[0].version} != apply={version}"
        )
        # Provenance stamp points back at the originating proposal.
        owner_p = next(p for s, p, _ in adopted_pids if s == skill)
        assert versions[0].params.get("applied_from_proposal") == owner_p

    reporter.section("source_skill on disk matches the seed")
    for skill, pid, _ in adopted_pids:
        assert final_store.get(pid).source_skill == skill

    reporter.end()
