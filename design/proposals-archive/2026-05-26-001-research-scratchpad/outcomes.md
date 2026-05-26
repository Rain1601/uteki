# Outcomes — quantitative comparison Run 1 → Run 7

Same prompt, same skill (`research_pipeline`), same model stack
(DeepSeek-chat for planner+research, AiHubmix Claude Sonnet 4.5 for
judges), 7 runs over ~2 hours. Each run was a real-LLM call.

## Headline numbers

| Metric | Run 1 (baseline) | Run 7 (converged) | Δ |
|---|---|---|---|
| `final-research.md` size | 15,151 B (scratchpad dump) | **3,393 B** (clean) | -78% |
| First line of artifact | `"I need to start by..."` | `"# 中国半导体设备板块"` | structural fix |
| C1 regex matches | 1,187 (sample: "to", "need", "start") | **9** (sample: "SH", "SZ", "SH") | -99% (all real) |
| C1 false-positive count | 1187 (all of them) | 0 | full clean |
| judge-correctness | 9/10 (graded wrong subset) | **9/10** (graded whole file) | same score, real meaning |
| judge-cite_compliance | 8/10 (same) | **9/10** | +1 |
| Number of criteria in contract | 6 (incl buggy C6) | 5 (no buggy ones) | clean |
| Evaluator decision | revise (wrong reason: buggy C6) | **approve** (5/5 real passes) | converged |
| Pipeline iterations | 1 (Generator + Evaluator round) | 1 (no iteration needed) | one-shot pass |

## Per-run summary

| Run | id | size | C1 fp | corr | cite | decision | meaning |
|---|---|---|---|---|---|---|---|
| 1 | fe448bf59604 | 15151 | 1187 | 9 | 8 | revise | baseline; judges blind to structural defect |
| 2 | 66af55f3e826 | 4497 | 0 | 3 | 3 | revise | scratchpad ↓; judges harshened; still scratchpad |
| 3 | 47faa6d45cca | 4011 | 0 | 3 | 1 | revise | tighter prompt; judges caught §2a violations; still scratchpad |
| 4 | (n/a — api restart issue) |
| 5 | 948dde2a7580 | 4011 | — | — | — | (stale) | post-strip code not loaded yet |
| 6 | 0ee8d7d0cd80 | 3172 | 32 | — | — | approve (false!) | strip works, but planner regressed contract (dropped C4/C5) |
| 7 | f01c9f77c422 | 3393 | 9 (real) | 9 | 9 | **approve** | converged |

## What got fixed at each step

| Round | Diff applied | What it solved | What it didn't |
|---|---|---|---|
| 1→2 | guardrails §5a + planner regex + 2 rubric whole-file | judges no longer blind to scratchpad; C1 no longer trivially passing on English words | scratchpad still appears in file |
| 2→3 | guardrails §5a v2 (first-char rule + forbidden examples) | judges caught more (§2a violations on `[UNSOURCED — caveats]`) | scratchpad still appears (worse — model added phantom `##` heading too) |
| 3→6 | artifact_store `_strip_preamble()` post-processor | **scratchpad eliminated from disk** | planner regressed contract (dropped C4+C5, regenerated buggy regex from negative example in warning) |
| 6→7 | planner SKILL.md: removed bad regex from warning + reinforced "MUST include 5" | clean contract, all 5 criteria run, fixed regex used | nothing left to fix |

## What the strip post-processor did

Concrete first 5 lines of Run 6's `final-research.md` (after strip):

```
# 中国半导体设备板块 — 精简研究框架

## 市场规模与增长

中国半导体设备市场是全球第二大单一市场，2023 年规模约 **300-350 亿美元**...
```

Same file without the strip would have been:

```
我来先并行拉取几家主要本土半导体设备公司的行情与财务数据，同时搜索近期行业新闻。
这些都是非半导体标的，让我用正确代码拉取半导体设备公司行情。工具返回的是 mock 数据。
让我尝试用已知的中国半导体设备 ticker 直接拉取行情和财务数据。...

# 中国半导体设备板块 — 精简研究框架
...
```

The post-processor dropped 3 lines / ~150 bytes before the first `#`,
matched via regex `[^#]# ` (non-# char immediately before "# ", which
catches both newline-anchored and inline-squashed preamble).

## Cost

- Total: ~$2 across 7 real-LLM runs (DeepSeek $0.08-0.09/run for
  planner+research, AiHubmix Claude Sonnet ~$0.05/run for 2 judges)
- CC reviewer time (me): all within this single CC session, no
  additional spend
- Operator (human): ~5 decision points, ~10 minutes total clock time
  spread across the 2-hour session

## Take-aways for the automated proposal store

1. **Iteration is normal.** Real proposals took 4 cycles. Don't model
   the loop as one-shot apply.
2. **Pure prompt fixes have a ceiling.** When the model is in
   compliance-theater mode (declares obedience while violating), more
   prompt is unlikely to help. Code fixes at the seam (post-processor,
   verifier-runtime) are the lever.
3. **Negative examples can backfire.** The planner copied a bad regex
   from a "don't do this" warning. Abstract the rule instead of
   showing the pattern.
4. **"approve" alone isn't a signal — read the verdict.** Run 6
   approved with broken inputs. Run 7 approved cleanly. The state
   machine should record verdict provenance, not just status.
5. **Judges need explicit scope.** Run 1's judges hallucinated a
   "draft segment" inside a scratchpad-filled file. The rubric must
   say "score the whole artifact as the deliverable" up front.
