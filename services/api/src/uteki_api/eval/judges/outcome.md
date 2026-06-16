---
name: outcome
applies_to: ["research", "company_research_pipeline"]
pass_threshold: 7
judge_model_preference:
  - aihubmix/claude-opus-4-5-20250929
  - aihubmix/claude-sonnet-4-5-20250929
  - openrouter/openai/gpt-5
  - deepseek/deepseek-reasoner
---

# Outcome rubric

Score 1-10 on whether the **agent's final delivery answers the user's
question well enough that the user can act on it**.

This is an outcome eval, not a process eval (per Anthropic's *demystifying
evals for AI agents*): don't penalise the agent for taking an unusual path,
calling tools you didn't expect, or skipping ones you did expect. Grade
what the user actually receives.

## What you see

- `user_input` — the question the user asked.
- `summary` — the agent's terminal text answer.
- `primary_artifact` — the deliverable file (memo, report, etc.) if any.

The trace, tool sequence, and intermediate thinking are **deliberately not
shown** — those are out of scope for this rubric.

## What you grade

1. **Direct answer** — does the deliverable actually answer the question?
   "I'll need more info" without a follow-up plan is a fail. A wrong answer
   delivered confidently is a fail.
2. **Decision-readiness** — can a human read this and act? A correct answer
   buried under three paragraphs of caveats counts as half-credit.
3. **Internal consistency** — do the numbers / claims agree with themselves?
   ("Revenue grew 20%" in section 2, "flat YoY" in section 4 = inconsistent.)
4. **Missing-context honesty** — if the agent didn't know something, did it
   say so, or did it bluff?

The deliverable's **citation quality** is graded by a separate rubric
(`cite_compliance.md`); don't double-count that here.

## Anchors

- **10** — Pristine. Directly answers the question, well-organised, no
  internal inconsistencies, calls out limitations honestly. A senior
  reviewer would forward this as-is.
- **8** — Solid answer. Decision-ready. Maybe one minor "could be tighter"
  ask. The user gets what they came for.
- **7** — Useful but rough. Answer is correct but takes effort to extract
  from the text. Some non-decision-driving slop.
- **5** — Partial. Half the question answered, or the answer is right but
  surrounded by enough noise that a busy user might miss it.
- **3** — Off-target. Answers a related question but not the actual ask. Or
  introduces material self-contradictions.
- **1** — Useless or actively misleading. Wrong answer delivered with
  confidence; user would be worse off than not asking.

## Escape hatch

If the run trace + artifacts don't give you enough information to judge
confidently — the artifact is empty, the summary is a generic boilerplate,
or the user's question is unparseable — score **5** and put the literal
string `INSUFFICIENT_EVIDENCE` at the start of your rationale.

Anthropic-style "give the LLM a way out": guessing is worse than abstaining.
Calibration will eventually weight `INSUFFICIENT_EVIDENCE` runs separately.
