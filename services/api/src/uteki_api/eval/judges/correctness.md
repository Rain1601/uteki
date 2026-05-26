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

## 评分对象：整份 artifact 文件作为单一交付物

把 artifact 文件作为单一交付物评分。**不要**从一堆混杂内容里挑出一
段看起来像 draft 的部分单独打分。

如果文件里包含：
- agent 的思考过程（"Let me try...", "Hmm, let me count..."）
- 字数估算 / 自评对照表
- 多个 draft 版本并存（"Let me draft:" 出现两次以上）
- 工作流叙述（"Step 1...", "Step 2..."）

→ 这本身就是**结构性缺陷**（违反 guardrails §5a "交付物只装成品"），
**评分必须 ≤ 4**。即使其中嵌着的"draft 段落"引用规范完美，整体文件
作为交付物不合格就是不合格。在 rationale 里明确指出"file contains
scratchpad/reasoning, not a clean deliverable"。

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
