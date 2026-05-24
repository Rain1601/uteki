---
name: correctness
applies_to: ["research", "earnings"]
pass_threshold: 7
judge_model_preference:
  - aihubmix/claude-sonnet-4-5-20250929
  - deepseek/deepseek-reasoner
---

# Correctness rubric

Score 1-10 on whether the **numerical claims and direct quotes** in the
draft are supported by `tool_result` content visible in the run trace.

## Anchors

- **10** — Every number cites a tool (`market_quote` / `financials` / `news_search`
  / etc.) or is explicitly marked `[UNSOURCED]`. No fabrication anywhere.
- **8** — 90%+ of numbers sourced; 1-2 minor (non-decision-driving) gaps,
  e.g. round-off in narrative.
- **7** — Most numbers sourced; ≤ 2 unsourced numbers but none load-bearing.
- **5** — Several unsourced numbers; some appear plausibly memorized.
- **4** — Over half of numerical claims unsourced and not marked.
- **2** — Mostly fabricated; tool calls were made but their results were
  ignored in favor of memorized values.
- **1** — Fabricates numbers with confidence; mentions tools that were never
  called.

## What counts as "sourced"

- A price/multiple/percentage that appears in a `tool_result.summary` or
  `tool_result.data` payload for that ticker.
- A quoted text snippet that appears verbatim or near-verbatim in a tool
  result, user-pasted material, or cited URL.
- An `[UNSOURCED]` marker placed inline at the position where the number
  would otherwise sit.

## What does NOT count

- "Common knowledge" prices, multiples, or market shares without tool
  evidence — these are training-data fabrications and must be penalized.
- Vague qualitative claims ("growing fast", "industry-leading") — these are
  out of scope for this rubric (covered by `style`).
- Round numbers that *happen* to match a tool result coincidentally —
  require the tool result to be visibly in the trace.
