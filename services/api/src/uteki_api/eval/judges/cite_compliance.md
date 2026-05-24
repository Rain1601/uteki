---
name: cite_compliance
applies_to: ["research", "earnings"]
pass_threshold: 8
judge_model_preference:
  - aihubmix/claude-sonnet-4-5-20250929
  - deepseek/deepseek-reasoner
---

# Cite-or-flag compliance rubric

Stricter sibling of `correctness`. Score 1-10 on whether the draft
**actually obeys the guardrails it was prepended with** (specifically the
"cite-or-flag" rule in `_shared/guardrails.md`).

Note: `pass_threshold = 8` here — this is a higher bar than `correctness`.
The Generator was given an explicit rule; obeying ≥ 80% of the time is the
minimum.

## Anchors

- **10** — Every numeric / quoted claim has an inline reference to its tool
  source (`[label](tool:name)` or similar). `[UNSOURCED]` markers appear
  only where the tool was tried and returned nothing — and the trace
  confirms that tool was called.
- **8** — One or two slips (e.g. an inline number without a citation
  appears once or twice), otherwise compliant.
- **6** — Compliant in form but evasive — uses qualitative phrasing
  ("PE 估值合理") to *avoid* having to cite anything specific.
- **4** — Multiple unmarked uncited numbers; cite-or-flag rule is
  observable as broken.
- **2** — Ignores the rule; numbers strewn through narrative without
  citations or `[UNSOURCED]` markers.
- **1** — Includes a closing "[UNSOURCED — 部分数据来自模型知识]" disclaimer,
  which is exactly the forbidden "publish with caveats" pattern called out
  in guardrails §2a.

## Hard fails (any one → cap at 4)

- A closing paragraph that admits "部分数据来自模型知识/需核实" — this is
  the explicit forbidden pattern in guardrails §2a.
- Citing a tool that the run trace does not show being called.
- Mixing real numbers with memorized numbers without distinction.

## What's OK

- `[UNSOURCED]` next to a missing data point that the available tools
  legitimately could not provide (e.g. asking about an unlisted private
  company, or a date in the future).
- Omitting a sentence rather than writing "[UNSOURCED]" everywhere.
