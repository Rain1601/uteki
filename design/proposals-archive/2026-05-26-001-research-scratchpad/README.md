# Proposal 2026-05-26-001 · research-pipeline scratchpad defect

> Status: **adopted** (manual driver, 4 sub-iterations)
> Driver: Rain1601 (operator role); reviewer: Claude Opus 4.7 (CC, external)
> Target skill: `research_pipeline` (planner + research + evaluator + judges)

## TL;DR

`research_pipeline` was producing markdown deliverables that were **80%
agent scratchpad** ("我来拉取数据...", "Let me count chars...") with the
actual research note buried inside. Uteki's internal `EvaluatorSkill`
graded these **9/10 on correctness** because:

1. Its `correctness` and `cite_compliance` rubrics implicitly assumed
   "a clean draft exists somewhere within the file" and graded that
   subset, not the whole artifact.
2. Its `C1` verifier regex matched English stop words ("to", "need",
   "start") as if they were stock tickers — 1187 false-positives.
3. Its `C6` regex (`^.{500,800}$` for length check) was unmatchable on
   multi-line markdown but no one noticed.

External review by Claude Code found these gaps. Operator approved the
proposed fixes. **Four sub-iterations later**, the same prompt produced
a clean deliverable scored `9/9` for legitimate reasons and the
evaluator returned `approve` on the first pass.

## Why this matters

This was the **first real-world walk** of the self-evolution loop
described in `design/02-self-evolution-loop.md`, with a human playing
the G1+G2 decision-gate role manually. Two important findings:

1. **Pure prompt tightening has diminishing returns.** Three rounds of
   strengthening the "don't write scratchpad" rule in guardrails didn't
   move the needle on DeepSeek-chat's behavioral default to narrate
   before acting. The fix that actually worked was a **deterministic
   post-processor at the seam** (`_strip_preamble()` in artifact store).
2. **Real proposals iterate.** The clean linear flow in design/02
   (one critique → apply → A/B → adopt) is the happy path. In reality
   we ran 4 critique/apply/verify cycles before convergence. The
   automation needs to model this — either as one proposal with
   multiple sub-iterations, or as a chain of related proposals.

## Files in this directory

| File | What it is |
|---|---|
| [`critique.md`](./critique.md) | The full `/uteki-review` output from CC after Run 1 — TL;DR + 5 specific findings + proposed diff + metadata. Verbatim. |
| [`outcomes.md`](./outcomes.md) | Run 1 → Run 7 quantitative comparison (sizes, scores, decisions). The proof. |
| [`diffs/01-guardrails.diff`](./diffs/01-guardrails.diff) | New `_shared/guardrails.md` §5a — "交付物只装成品" |
| [`diffs/02-planner.diff`](./diffs/02-planner.diff) | Planner SKILL.md — fixed C1 regex, removed negative-example latch hazard, reinforced "MUST include 5 criteria" |
| [`diffs/03-judges.diff`](./diffs/03-judges.diff) | `correctness.md` + `cite_compliance.md` — leading "score the ENTIRE file as the deliverable" rule |
| [`diffs/04-artifact-strip.diff`](./diffs/04-artifact-strip.diff) | `LocalFileArtifactStore.write()` — deterministic strip of pre-`#` preamble on markdown writes. The fix that actually closed it. |

## Timeline (real-LLM runs, ~$2 total, 2026-05-26)

| Run | trigger | apply | verdict | what changed for the next iteration |
|---|---|---|---|---|
| 1 | initial | (baseline) | revise (5/6, wrong reason) | CC writes critique with 5 findings |
| 2 | iter | guardrails §5a v1 + planner regex + judge rubrics | revise (5/6, real reasons) | judges now catch scratchpad; scratchpad still present |
| 3 | iter | guardrails §5a v2 (stronger words) | revise (still scratchpad) | pure prompt approach hits ceiling |
| 4 | iter | artifact_store strip (post-processor) | (api not restarted, false data) | restart needed |
| 5 | iter | (same, with restart) | (intermittent / cache effects) | retry |
| 6 | iter | (restart picked up strip) | approve (false — planner regressed contract) | strip works! but planner dropped C4+C5 |
| 7 | iter | planner SKILL.md — removed bad regex from warning, reinforced required criteria | **approve (5/5, real)** | converged |

## What the operator (you) actually did

This is genuinely a 4-step human-in-the-loop flow:

```
Run 1 critique by CC → [操作员: "方案A"] → apply round 1 → Run 2
                                                        ↓
                                              [操作员: "A"] → apply round 2 → Run 3
                                                                            ↓
                                                                 [操作员: "B"] → strip + Run 6
                                                                                ↓
                                                                  [操作员: 隐含 continue] → planner fix → Run 7
```

Five decision points, one approval per round. No automation existed
yet — every "apply" was Claude Code (the same external reviewer)
making the edits, then the operator deciding whether the result
was good enough to stop.

## What's still imperfect

After convergence:

- **The agent still says "我来..." in its event stream**. The strip
  removes it from disk but the live SSE stream and `run-trace.json`
  still contain it. Real evaluator sees clean file; client streaming
  sees scratchpad. Acceptable for now (UI can filter).
- **C6 (字数) verifier was dropped entirely** rather than being made
  to work right. Future work: add a `text_length` verifier type.
- **Iteration was manual.** The automated proposal-store + automatic
  trigger pipeline described in design/02 was NOT exercised — only
  the substantive loop logic was.

## Cross-references

- Design spec: [`../../02-self-evolution-loop.md`](../../02-self-evolution-loop.md)
- The slash command that drove this: [`../../../.claude/commands/uteki-review.md`](../../../.claude/commands/uteki-review.md)
- Platform overview at the time of this run: [`../../00-agent-platform.md`](../../00-agent-platform.md)
- Commits that landed the changes:
  - `c44e990` fix(mcp): httpx error translation (operational, not part of critique)
  - `6520ddb` fix(artifacts): strip preamble — diffs/04
  - `9c8ee72` fix(skills): guardrails + planner + judges — diffs/01-03
