# design/proposals-archive/

Real, manually-driven instances of the self-evolution loop described in
[`../02-self-evolution-loop.md`](../02-self-evolution-loop.md).

Each subdirectory is a **proposal** — a complete record of one round of
"external reviewer (Claude Code) → human approval → code/prompt changes
→ A/B verification" — captured so the future automated infrastructure
(`data/evolution/proposals/<P-id>/`) has a real shape to match.

These are tracked in git (unlike `data/evolution/proposals/` which is
runtime state and gitignored). They serve three purposes:

1. **Audit trail** for changes that touched prompts/rubrics, not code logic
2. **Reference shape** for the automated proposal-store implementation
3. **Honest case studies** — what real iteration looked like, including
   the parts where pure-prompt fixes didn't work and a code change was
   needed instead

## Current samples

| Proposal | Skill | Driver | What it surfaced |
|---|---|---|---|
| [`2026-05-26-001-research-scratchpad/`](./2026-05-26-001-research-scratchpad/) | `research_pipeline` | manual `/uteki-review` | scratchpad-in-deliverable, false-positive verifiers, judges grading wrong target |

## When a sample becomes "real automated"

When `data/evolution/proposals/<P-id>/` gets generated programmatically
(per the spec in `design/02`), the tracked archive here can stop growing.
Active proposals would live in `data/`, and only the **canonical first
sample** (the one we hand-drove) stays here as historical reference.
