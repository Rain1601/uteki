# 007 · Trace diagnosis

## Why

As runs become artifact-first and tool/source-heavy, users need a compact diagnosis artifact that answers: what happened, what failed, which tools were used, whether citations look grounded, and whether cost/usage was unusual.

## What changes

- Add a trace diagnosis builder.
- Have the harness write `trace-diagnosis.json` before `done`.
- Include event counts, failures, tool call/failure summaries, usage totals, artifact names, and citation/source-catalog status.

## Out of scope

- LLM-generated diagnosis narratives.
- UI visualization beyond artifact display.
- Cross-run diagnosis comparison.
