---
name: coverage
applies_to: ["research", "earnings"]
pass_threshold: 7
judge_model_preference:
  - deepseek/deepseek-reasoner
  - aihubmix/claude-sonnet-4-5-20250929
---

# Coverage rubric

Score 1-10 on whether the draft **covers the dimensions the user (or the
sprint contract) asked for**.

Look at the user's original prompt and the sprint contract's `scope` field.
For each requested dimension (e.g. "valuation", "competitive landscape",
"risks"), check whether the draft addresses it substantively — not just
mentions the word.

## Anchors

- **10** — Every requested dimension has a dedicated section or paragraph,
  each with at least one specific data point or named example.
- **8** — All dimensions present; one or two thinly covered (single
  sentence).
- **7** — All dimensions present; depth uneven but no missing area.
- **5** — One major dimension missing OR covered only by hand-waving.
- **3** — Multiple dimensions missing; output reads as a partial answer.
- **1** — Most of the requested scope absent; output addresses a different
  question.

## What counts as "covered"

- A named header (`## 估值` / `## Valuation`) followed by at least one
  number or specific company / event.
- A clearly-labeled paragraph that addresses the dimension by name.

## What does NOT count

- A passing mention in a list ("涉及估值、风险、催化剂…") without follow-up.
- A dimension that's "implied" by tangential content.
- A "see appendix" pointer when no appendix exists.
