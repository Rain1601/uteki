# 016 · Retrieval Benchmark

## Problem

015 eval-workbench measures whether a **new prompt produces better output**. That's the right tool for prompt iteration, but it's the wrong tool for catching a different class of regression:

> **Agent's retrieval / citation / temporal-honesty pipeline silently broke.**

You change `web_search` to use `vertex_grounding`. Output reads well, judge gives v4 a +0.7 on actionability. 015 says "ship it". But silently, the agent now sometimes cites documents from 2026 to answer questions about 2024 because Gemini doesn't actually respect "as of" hints in queries. We have no automated way to catch this. The user reads a clean-looking report and walks away with future-leaked analysis.

Other failures in the same class:
- Agent invents a number that isn't in the source doc(s) it cited.
- Agent presents a one-sided view when the corpus has a high-credibility opposing source.
- Agent confidently answers when the corpus simply doesn't contain the fact (hallucination instead of "not found").
- Agent skips a 10-Q amendment because retrieval scored it lower, missing material restatement.

These are **pipeline failures**, not judgment failures. They have **objective oracles** — you can pin a ground-truth answer or expected citation set per case. Unlike PnL, you can score in seconds and gate CI on it.

## Solution

A **sealed-corpus, hand-curated, content-hash-locked regression benchmark**. Mirrors what SWE-bench does for code: pre-known cases, oracle ground truth, deterministic scoring, CI gate.

```
                                  ┌──────────────────────────────────┐
   any change to retrieval /      │  scripts/benchmark-run.sh        │
   tools / source / chunk /       │  --case-set approved             │
   index / prompt-shape           │  --agent company_research_pipeline│
        ──────────────────►       └──────────────┬───────────────────┘
                                                 │
                          ┌──────────────────────▼──────────────────────┐
                          │  benchmark/runner.py                        │
                          │  for each case (5 → 30):                    │
                          │    inject as_of_date into harness           │
                          │    swap web_search/news_search for          │
                          │      corpus-bound stubs                     │
                          │    run agent, capture answer + citations   │
                          │    score deterministically + judge-bounded  │
                          └──────────────────────┬──────────────────────┘
                                                 │
                          ┌──────────────────────▼──────────────────────┐
                          │  report.json + DETERMINISTIC/JUDGED labels  │
                          │  CI gates:                                  │
                          │    lookahead_leakage > 0  → BLOCK           │
                          │    planted_recall regression → BLOCK        │
                          │    faithfulness regression → BLOCK          │
                          └─────────────────────────────────────────────┘
```

### Five capability types — each case is one of

1. **planted_answer** — fact F lives in doc X; question targets F; expected = F + must_retrieve = [X]
2. **planted_contradiction** — pair of docs (A, B) disagreeing on the same claim; both must surface
3. **unanswerable** — fact genuinely absent from corpus; expected = NOT_IN_CORPUS; tests abstention honesty
4. **future_trap** — doc with `observed_at > as_of_date` placed in corpus that "perfectly" answers; agent must not use it
5. **historical_situation** — known-outcome event with `as_of_date` placed before the resolution; grading is on whether the agent found and weighted the available signals (process), **not** whether it predicted the outcome (result)

### Five deterministic scorers + one judge-bounded scorer

**DETERMINISTIC (CI gates, no LLM, fully trusted):**
- `lookahead_leakage` — any cited doc with `observed_at > as_of`? Zero tolerance.
- `numeric_exact` — every numeric_answer case: exact match.
- `abstention_honesty` — on NOT_IN_CORPUS cases: said "not found" or fabricated?
- `planted_recall` — fraction of must_retrieve actually retrieved.
- `contradiction_recall` — fraction of must_surface_contradiction actually surfaced.

**JUDGED (LLM judge + 10% human audit, marked as JUDGED):**
- `faithfulness/provenance` — split answer into atomic claims; verify each is supported by the cited doc.

This scorer is **deferred to the Claude Code skill** the user mentioned will write Q2's judge logic.

### Sealed corpus, not live search

The corpus is **hand-curated frozen files on disk** with `observed_at`/`published_at`/`source` frontmatter, locked by content hash. The benchmark harness intercepts the agent's `web_search` / `news_search` tools and re-points them at the corpus.

Why not "live search with date filter":
- Reproducibility: same case half a year from now must produce byte-identical scoring inputs. Live search APIs change.
- Tamper-proof: publisher CMS can backdate / republish news articles. SEC EDGAR is immutable, but Bloomberg/Reuters/Substack aren't.
- CI offline-friendly: benchmark must run without any external API key.

Where immutable sources exist (SEC EDGAR / FRED / Fed), the corpus is **populated from them** via one-time fetch scripts. The corpus stays sealed; the fetch script is not part of the runtime path.

## Boundary vs 015 eval-workbench

| | 015 eval-workbench | 016 retrieval benchmark |
|---|---|---|
| Question | Is v4 prompt's output *better* than v3's? | Did v4 break the retrieval pipeline? |
| Signal | LLM judge + human audit | Deterministic checks + bounded judge |
| Data source | Real prod runs | Sealed local corpus |
| Reproducibility | Cross-run noise expected (LLM stochastic) | Byte-identical per case |
| CI gate? | No (subjective signal can't block merges) | Yes (deterministic signal can) |
| Cadence | Run before shipping a new prompt | Run on every PR touching retrieval/tools |

015 and 016 are complementary, not competing.

## Non-goals

- ❌ Investment judgment accuracy (PnL, hit rate). See `README-scope.md`.
- ❌ 30-50 cases on day 1. Start with 5 (one per capability), grow as failures get harvested.
- ❌ Automated case generation. Drafts are written by humans, approved by humans. LLM-authored cases + LLM-authored oracle = circular validation, banned.
- ❌ Live web search inside benchmark mode. Vertex Grounding / Tavily / DDGS all hard-disabled.
- ❌ Faithfulness LLM judge in this PR series. Deferred to a Claude Code skill the user will write later.

## Costs

- Engineering: 3-4 days for the minimal version (PR α-γ below). One developer.
- Corpus storage: a few hundred KB per case, frozen on disk. Roughly 10-30 MB at maturity.
- Maintenance: corpus is write-once. Adding a case = adding ~5-8 docs. Hash-locked, so accidental edits fail loud.
- Runtime: 5-10 minutes per full benchmark run at 5 cases; scales linearly. Faithfulness judge would add ~1 min/case once enabled.
