---
name: style
applies_to: ["research", "earnings"]
pass_threshold: 7
judge_model_preference:
  - aihubmix/claude-sonnet-4-5-20250929
  - deepseek/deepseek-reasoner
---

# Style rubric — anti "AI slop"

Score 1-10 on whether the draft reads like **a senior investment-research
associate's note**, not generic LLM filler.

Inspiration: Anthropic's harness paper observation that a single phrase
like "museum quality" in the criteria can push a generator far up the
quality curve. This rubric encodes the same standard.

## Anchors

- **10** — Tight, specific, opinionated. Every paragraph adds new
  information. Numbers in tables, narrative around them. No throat-clearing.
- **8** — Mostly tight; one or two filler sentences. Structure is clear.
- **7** — Readable, structured, no obvious filler. Acceptable to ship as a
  draft for senior review.
- **5** — Noticeably formulaic. Repeats the question back. "首先...", "其次...",
  "总而言之..." Generic risk disclaimers. Padding paragraphs.
- **3** — Heavy AI signatures: "作为 AI 我无法...", "需要注意的是...",
  excessive bullet hedging, every section ends with "建议关注...".
- **1** — Pure boilerplate. Could be about any company. Numbers absent or
  in narrative form ("营收约几百亿" instead of a table).

## Specific signals to penalize

- **Throat-clearing openings** ("我将逐步分析..." / "好的，让我..." / "I'll
  begin by...")
- **Repeating the user's question** in the first paragraph
- **Hedge-heavy risk sections** that say nothing specific (every section
  says "需谨慎、关注政策变化、市场波动等")
- **List-of-three syndrome** — every concept gets exactly 3 bullets even
  when 1 or 5 would be more honest
- **Closing summary paragraph** that just restates the headers ("综上所述，
  公司在 X / Y / Z 三方面均有...")
- **English-Chinese mixing** beyond convention (ticker / standard acronyms
  OK; mixing whole sentences not OK)

## Positive signals

- Number tables instead of inline numbers
- Specific company / event names instead of categories
- Bolded short takeaways at section heads
- Explicit "but" / "however" sentences that surface tension
- Asymmetric structure when the underlying analysis is asymmetric
