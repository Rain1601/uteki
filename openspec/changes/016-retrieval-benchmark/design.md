# 016 · Design

## Architecture

```
                          ┌─────────────────────────────────────────────┐
                          │  Source population (offline, one-shot)      │
                          │                                             │
   SEC EDGAR ◄────────────┤  scripts/fetch-sec-into-corpus.py           │
   FRED      ◄────────────┤  scripts/fetch-fred-into-corpus.py  (later) │
   News (manual)  ───────►│  scripts/import-news-into-corpus.py (later) │
                          │                                             │
                          │  All write to data/eval-benchmark/snapshots │
                          └──────────────────────┬──────────────────────┘
                                                 │
                          ┌──────────────────────▼──────────────────────┐
                          │  Sealed corpus on disk                      │
                          │  data/eval-benchmark/snapshots/<id>/        │
                          │    docs/<doc_id>.md   (frontmatter + body)  │
                          │    manifest.json      (sha256 per doc)      │
                          │                                             │
                          │  IMMUTABLE — any byte change → hash fail    │
                          └──────────────────────┬──────────────────────┘
                                                 │
                          ┌──────────────────────▼──────────────────────┐
                          │  Cases on disk                              │
                          │  data/eval-benchmark/cases/                 │
                          │    draft/<case_id>.yaml   (status: draft)   │
                          │    approved/<case_id>.yaml (after review)   │
                          └──────────────────────┬──────────────────────┘
                                                 │
                          ┌──────────────────────▼──────────────────────┐
                          │  eval/benchmark/                            │
                          │    corpus.py        load + filter + verify  │
                          │    case_schema.py   Pydantic spec           │
                          │    case_loader.py   YAML walk + validate    │
                          │    runner.py        execute case            │
                          │    scorers/                                 │
                          │      deterministic.py  (5 scorers)          │
                          │      judged.py    (deferred to Q2 skill)    │
                          │    harness_cli.py   CLI entrypoint          │
                          └─────────────────────────────────────────────┘
```

## Data model

### Snapshot (the sealed corpus)

A directory with two file types:

**`docs/<doc_id>.md`** — frontmatter + plain markdown body

```markdown
---
id: googl-2024-q3-10q
observed_at: 2024-10-29
published_at: 2024-10-29
source: sec_edgar
source_url: https://www.sec.gov/Archives/edgar/data/.../filing.htm
ticker: GOOGL
stance: NA  # long | short | neutral | NA
filing_type: 10-Q
fetched_at: 2026-06-22T15:30:00Z
fetched_by: scripts/fetch-sec-into-corpus.py
---

# Alphabet Inc. Form 10-Q · Q3 2024

[body text — extracted plain content of the filing]
```

**`manifest.json`** — content hashes:

```json
{
  "snapshot_id": "2024q4-googl-capex",
  "created_at": "2026-06-22T15:30:00Z",
  "documents": {
    "googl-2024-q3-10q": {
      "path": "docs/googl-2024-q3-10q.md",
      "sha256": "abc123...",
      "observed_at": "2024-10-29",
      "source": "sec_edgar"
    }
  }
}
```

Why both frontmatter and manifest:
- Frontmatter travels with the doc (easy to grep, easy to read)
- Manifest gives single source of truth for "this snapshot's contents" — what `verify_integrity()` checks against
- When the agent retrieves a doc, the response includes the frontmatter so the agent sees `observed_at`

### Case YAML

```yaml
case_id: planted_answer_001_googl_2024_q4_capex
capability: planted_answer  # one of 5 enum values
query: "What did Alphabet say about its planned 2024 capital expenditure during the Q3 2024 earnings call?"
as_of_date: 2024-12-01
corpus_snapshot: 2024q4-googl-capex

expected_answer: |
  Alphabet management stated that 2024 capital expenditures
  would be approximately $51 billion, with each quarter at or
  above the Q1 2024 level of $12 billion.
numeric_answer: 51_000_000_000  # optional, when there's a single canonical number

must_retrieve:
  - googl-2024-q3-10q
  - googl-2024-q3-earnings-press-release

must_surface_contradiction: []  # planted_answer cases don't have contradictions
must_not_use: []                 # planted_answer cases don't have future traps

status: draft  # only "approved" cases run in CI
authored_by: claude-opus-4-7  # informational
authored_at: 2026-06-22
review_notes: |
  Quoting page X paragraph Y of the 10-Q. Numeric answer pulled
  verbatim from the press release.
```

Schema validation refuses any case where:
- `capability` ∉ enum
- `status` ∉ {draft, approved}
- `must_retrieve` doc_ids not in snapshot
- `expected_answer == NOT_IN_CORPUS` but `numeric_answer != null`
- `corpus_snapshot` directory missing or hash-mismatched

## Five case types — design notes

### 1 · planted_answer

The simplest. Fact F is stated in doc X. Question targets F. Ground truth:

- `expected_answer`: the fact
- `numeric_answer`: if F is a number, the exact number
- `must_retrieve`: [X] (plus close cousins if the agent should ideally pull both 10-Q and press release for the same data point)

Scorers fire: numeric_exact (if applicable), planted_recall.

### 2 · planted_contradiction

Pair of docs (A, B) say opposite things about claim C. Question targets C. Ground truth:

- `expected_answer`: free-form, e.g. "The picture is mixed: doc A says X, doc B says Y"
- `must_retrieve`: [A, B] (both must be in the call set)
- `must_surface_contradiction`: [A, B] (more strict — both must be visible in the agent's *answer*, not just retrieved silently)

This catches the failure mode: "agent picks side A, ignores B even though it retrieved both". Real risk because LLMs prefer coherent narrative over conflicted analysis.

Scorers fire: planted_recall, contradiction_recall.

### 3 · unanswerable

Fact genuinely absent from corpus. Tests **abstention honesty**.

- `expected_answer: NOT_IN_CORPUS`
- `must_retrieve`: [] (anything goes — agent may search, must find nothing)
- Agent should answer "the corpus does not contain..." rather than invent.

Scoring is binary: `abstention_honesty ∈ {"honest", "fabricated", "n/a"}`. Fabrication rate per run is tracked separately as a key health metric.

### 4 · future_trap

A doc with `observed_at > as_of_date` is placed in the snapshot that, if used, would "perfectly" answer the question. The harness's as_of filter should hide it from the agent. If the agent cites it anyway, the filter has a bug or the agent reached around it (e.g., via cached knowledge).

- `must_not_use`: [the trap doc]
- `expected_answer`: what a 2024-Q4 analyst would have said given pre-cutoff data
- `must_retrieve`: typically a couple pre-cutoff docs

Scoring: `lookahead_leakage`. Zero tolerance. CI red.

### 5 · historical_situation

Known-outcome real event (e.g., MSFT-Activision FTC ruling, GOOGL antitrust decision). `as_of_date` is placed strategically *before* the outcome.

- `expected_answer`: a measured analyst-grade summary of what was *known then*, not what happened next
- `must_retrieve`: the docs that contained the actual signals available pre-event
- `must_surface_contradiction`: optionally, both sides of the pre-event debate

This is the most subtle type. We are NOT grading "did the agent predict the outcome". We are grading "did the agent find the available signals at the time, and weight them coherently". The same case answer would be correct whether the event eventually went one way or the other.

The temptation to grade outcome is real. Reviewers must resist. This case type exists to test process; outcome scoring is forbidden per `README-scope.md`.

Scorers fire: planted_recall, contradiction_recall, faithfulness (via judge when available).

## Five deterministic scorers (CI gate eligible)

### `lookahead_leakage`

For every citation the agent included in its answer:
- Look up that doc's `observed_at` in the manifest
- If `observed_at > as_of_date`, count as a leak

**Score**: integer leak count. **Gate**: any value > 0 → CI red. Zero tolerance.

### `numeric_exact`

For cases with `numeric_answer != null`:
- Parse the agent's answer for the numeric value the case expects
- Exact match (with tolerance for unit suffixes like "$51B" vs "51_000_000_000")

**Score**: bool. **Gate**: 100% match required on numeric cases.

### `abstention_honesty`

For cases with `expected_answer == NOT_IN_CORPUS`:
- Check whether agent's answer contains a fabricated specific claim
- Honest = says "not found" / "corpus doesn't contain"
- Fabricated = invents a specific number/event/person

**Score**: enum ∈ {honest, fabricated, n/a}. **Gate**: fabrication rate ≤ 0 on previously-honest cases (regression).

### `planted_recall`

For each case's `must_retrieve` list:
- Did the agent's retrieved doc ids include all of them?
- (Note: "retrieved" means listed in citations, not just visited internally)

**Score**: float ∈ [0, 1]. **Gate**: per-case threshold + no regression vs main branch.

### `contradiction_recall`

For each case's `must_surface_contradiction` list:
- Did the agent's *answer text* show evidence of both sides?
- Detection heuristic: check that both doc ids appear as citations AND that contrast language ("however", "on the other hand", "conversely") appears in the answer

**Score**: float ∈ [0, 1]. **Gate**: no regression vs main.

### Judged: `faithfulness/provenance` (DEFERRED to Q2 skill)

Not implemented in 016 PR α-γ. The user mentioned a Claude Code skill will own this.

When implemented:
- Atomize the answer into sub-claims
- For each sub-claim, check that the cited doc actually supports it
- Output: `unsupported_pct ∈ [0, 1]`
- Use cross-family LLM (Anthropic judging DeepSeek output to avoid self-grading bias)
- Sample 10% for human audit each run

## Harness

```
benchmark_run(case_set, agent, snapshot):
  load corpus (verify hashes)
  load cases (validate schemas)
  for each case in case_set:
    apply as_of filter on corpus → filtered_corpus
    install stub web_search / news_search tools pointing at filtered_corpus
    instantiate agent via SkillRegistry.create(name)
      (uses 015 PR α's concurrency fix — fresh instance per case)
    inject as_of into system_prompt + every tool call
    capture: final_answer, citations[], retrieved_doc_ids[]
    score (deterministic; judge if enabled)
  emit report.json with per-case + aggregate
  diff vs previous report → CI gate decisions
```

### Stubbed tools in benchmark mode

When `benchmark_mode=True`:
- `web_search` → `BenchmarkWebSearch(filtered_corpus)` — returns matches from corpus only
- `news_search` → same
- `web_extract` → `BenchmarkWebExtract(filtered_corpus)` — fails on any URL not in corpus
- Live providers (vertex_grounding, ddgs, tavily) — `raise RuntimeError("live search disabled in benchmark mode")`

The agent does not know it's in benchmark mode. Tool signatures unchanged, only implementations swapped.

### System prompt injection

Prepend to system_prompt:

```
⚠️ AS-OF MODE — Today's date is {as_of_date}. You are a research analyst
working AS IF you were on {as_of_date}. You do NOT have any knowledge of
events, prices, news, or developments after {as_of_date}. If you remember
future events from training, ignore them. All search tools return
pre-filtered results.
```

This is soft; the hard guarantee is the corpus filter at the tool layer. The prompt helps the LLM cooperate.

## CI integration

### Gates

```
lookahead_leakage > 0                          → BLOCK
fabrication rate increased vs main             → BLOCK
planted_recall dropped vs main (per case)      → BLOCK
contradiction_recall dropped vs main           → BLOCK
numeric_exact failed on previously-passing case → BLOCK
```

### Report format

`report.json`:

```json
{
  "run_id": "bench-2026-06-22-1530",
  "case_set": "approved",
  "agent": "company_research_pipeline",
  "agent_version": "v4",
  "case_count": 5,
  "deterministic": {
    "lookahead_leakage": 0,
    "numeric_exact_pass_rate": 1.0,
    "abstention_honesty": {"honest": 1, "fabricated": 0, "n/a": 4},
    "planted_recall_mean": 0.92,
    "contradiction_recall_mean": 0.80
  },
  "judged": null,
  "per_case": [ ... ],
  "vs_main": {
    "lookahead_leakage": "+0",
    "planted_recall_mean": "+0.04",
    "regressions": []
  }
}
```

The diff-vs-main path needs a stored baseline report. Where to keep it: separate `data/eval-benchmark/baseline.json`, regenerated when a PR with intentional retrieval improvement merges.

## What this PR series does NOT build

- The faithfulness LLM judge — deferred to user's Q2 Claude Code skill
- Live network of judges + voting — deferred
- Regression harvest CLI — useful, but Day 5+
- GitHub Actions workflow yaml — gate logic ready, but CI wiring needs your environment setup decisions
- 30-50 cases — start with 5, grow when you find real failures

## Trade-offs explicitly accepted

- **Corpus is offline.** Can't catch failures that only occur on live API quirks (rate limits, partial responses). Acceptable: those failures are integration concerns, not pipeline-quality concerns.
- **5 cases is small.** A determined adversary could craft an agent that passes all 5 while failing 100 unseen cases. Mitigation: regression-harvest from prod failures grows the set organically.
- **Deterministic scorers are blunt.** `planted_recall` doesn't understand "the agent retrieved a synonymous doc". Mitigation: be permissive in `must_retrieve` — list all acceptable equivalent docs.
- **Judge is deferred.** Until the Q2 skill lands, we have no faithfulness signal. Mitigation: deterministic scorers cover the most common regression modes. Faithfulness catches more subtle hallucination, which judge will add later.
