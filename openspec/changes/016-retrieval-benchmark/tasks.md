# 016 · Tasks

3 PRs, each independently mergeable. PR α-γ together = "the minimum viable benchmark"
the user signed off on (排序 B, ~3-4 working days). No live web in benchmark
mode; no PnL in scoring; case status is draft until human review.

E2E gate: each PR ends with `./scripts/e2e.sh` 88+/88+ green.

---

## PR α — Schema + Corpus + SEC fetch script (~1 day)

> Foundation. No agent execution yet, no scorers yet. Just the data spine.

- [ ] **Tα1** `eval/benchmark/case_schema.py` — Pydantic models
    - `Capability` enum (5 values)
    - `BenchmarkCase` model (the YAML schema)
    - `CaseStatus` enum (draft, approved)
    - validation helpers
- [ ] **Tα2** `eval/benchmark/corpus.py`
    - `Document` dataclass (id, observed_at, body, frontmatter, sha256)
    - `CorpusSnapshot.load(snapshot_id, root) -> CorpusSnapshot`
    - `CorpusSnapshot.verify_integrity()` — hash-check every doc against manifest
    - `CorpusSnapshot.view_at(as_of_date) -> FilteredCorpus` — observed_at <= as_of only
    - All public methods refuse to operate if manifest is missing or mismatched
- [ ] **Tα3** `eval/benchmark/case_loader.py`
    - `load_cases(case_dir) -> list[BenchmarkCase]`
    - validates: capability enum, must_retrieve docs exist in snapshot, status enum
    - separately tracks `draft/` and `approved/`
- [ ] **Tα4** `scripts/fetch-sec-into-corpus.py` — already partly drafted Day 1
    - `python fetch-sec-into-corpus.py GOOGL --filings 10-Q,10-K,8-K --since 2024-07 --until 2024-12 --snapshot 2024q4-googl-capex`
    - Uses SEC EDGAR public API (no key); UTEKI_SEC_USER_AGENT honored
    - Writes doc files + updates manifest.json atomically
    - Idempotent: re-running with same args doesn't duplicate
- [ ] **Tα5** First snapshot on disk: `data/eval-benchmark/snapshots/2024q4-googl-capex/`
    - GOOGL 2024-Q2 + Q3 10-Qs (so Q3 is in scope, Q4 8-K can be a future_trap)
    - GOOGL 2025-Q1 8-K (the future trap)
    - Press releases if accessible
- [ ] **Tα6** Unit tests: `tests/unit/test_benchmark_corpus.py`
    - hash verify fails when a doc is edited
    - as_of filter excludes documents correctly
    - case loader rejects schema violations
- [ ] **Tα7** `./scripts/e2e.sh` green → commit + push

---

## PR β — Five deterministic scorers (~1 day)

> The CI-gate-eligible scorers. Pure Python, no LLM dependency.

- [ ] **Tβ1** `eval/benchmark/scorers/deterministic.py`
    - `score_lookahead_leakage(answer, citations, case, snapshot) -> int`
    - `score_numeric_exact(answer, case) -> bool | None`
    - `score_abstention_honesty(answer, case) -> Literal["honest", "fabricated", "n/a"]`
    - `score_planted_recall(citations, case) -> float`
    - `score_contradiction_recall(answer, citations, case) -> float`
- [ ] **Tβ2** Unit tests: `tests/unit/test_benchmark_scorers_deterministic.py`
    - Fixture-driven: one fixture file per scorer, multiple cases each
    - Cover obvious passes + obvious failures + edge cases (e.g. agent cites both a valid doc AND a future-leaked doc on same answer)
- [ ] **Tβ3** Document scoring contract in `eval/benchmark/scorers/__init__.py`
    - Each scorer's signature, what it returns, its CI gate behavior
- [ ] **Tβ4** `./scripts/e2e.sh` green → commit + push

---

## PR γ — Harness + CLI + Remaining 4 cases (~1.5 days)

> End-to-end. Run one case → see one report.json. Then run 5.

- [ ] **Tγ1** `eval/benchmark/runner.py`
    - `BenchmarkRunner.run_case(case, agent, snapshot) -> CaseResult`
    - Wires the as_of-filtered corpus into stubbed `web_search`/`news_search` tools
    - Live tool providers raise on call inside benchmark mode
    - Captures: final_answer, citations[], retrieved_doc_ids[], duration_ms
- [ ] **Tγ2** Tool stubs:
    - `BenchmarkWebSearch(filtered_corpus)` — keyword-match against corpus
    - `BenchmarkNewsSearch` — same but with news source filter
    - `BenchmarkWebExtract` — 404 on URLs not in corpus
- [ ] **Tγ3** `eval/benchmark/harness_cli.py`
    - `benchmark-run --case-set draft|approved --agent X --snapshot Y --out report.json`
    - Computes diff vs baseline (if present) and exits non-zero on regression
- [ ] **Tγ4** `scripts/benchmark-run.sh` — thin shell wrapper
- [ ] **Tγ5** Author remaining 4 cases (all `status: draft`):
    - planted_contradiction · GOOGL 2024 Q4 segment commentary discrepancy
    - unanswerable · GOOGL Cloud China revenue (SEC doesn't disclose)
    - future_trap · 2025-Q1 8-K placed in snapshot with as_of=2024-12-31
    - historical_situation · GOOGL pre-antitrust ruling 2024
- [ ] **Tγ6** E2E: `tests/e2e/test_26_benchmark_chain.py`
    - run the 5 draft cases end-to-end with a mocked agent
    - assert deterministic scores are sane
    - assert hash-verify rejects a tampered snapshot
- [ ] **Tγ7** `./scripts/e2e.sh` green → commit + push

---

## Deferred (NOT in 016 PR α-γ)

- ❌ `scorers/judged.py` — Faithfulness judge, deferred to user's Claude Code skill
- ❌ Regression harvest CLI (`scripts/benchmark-harvest.sh`)
- ❌ GitHub Actions workflow yaml — gate logic is in the CLI exit codes; CI wiring is its own commit
- ❌ FRED / Fed fetch scripts (Q1 of 016 only needs SEC)
- ❌ News article import script — needed for cases that use news; defer until first such case
- ❌ Beyond 5 cases — grow via regression harvest from real failures

---

## Why each scope cut

- **5 cases not 30-50**: per the guide, "质量和对抗性覆盖胜过数量". 5 hand-crafted cases catch egregious regression with 1/10 the maintenance.
- **No judge scorer**: user said the Q2 skill will own this. Deterministic scorers cover ~80% of regression modes anyway.
- **No CI yaml**: gates work via exit codes; how to wire those into Cloud Build / GitHub Actions is environment-specific and shouldn't block code.
- **SEC-only sources for first cases**: SEC EDGAR is the simplest immutable source we can fully automate. News imports come once we have a case that demands them.

---

## Time total

| PR | Estimate |
|---|---|
| α schema + corpus + SEC fetch | 1 day |
| β deterministic scorers | 1 day |
| γ harness + remaining cases + e2e | 1.5 days |
| **Total** | **~3.5 working days** |

Matches the 排序 B commitment.

---

## After 016 completes

- 015 PR β (structural metrics) — the user's "Q2 大投入"
- 015 PR γ (BenchmarkRunner for A/B compare across prompt versions)
- 015 PR δ (Screen 3 A/B Compare UI)
- 016 PR δ — when Q2 skill lands, add faithfulness scorer
- 016 PR ε — regression harvest, news imports, more cases
