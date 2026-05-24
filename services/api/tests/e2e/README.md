# E2E core flow suite

The 5 chains that, if all green, demonstrate the M1-M7 + M4 platform
behaves as designed. Each chain prints a structured trace so a failure
is interpretable without re-running with a debugger.

## Run

```bash
./scripts/e2e.sh                 # all chains
./scripts/e2e.sh -k auth         # only T1
./scripts/e2e.sh -k pipeline -x  # T4 only, stop on first fail
```

Mock LLM is the default (`UTEKI_USE_MOCK_LLM=true`); no provider keys
needed. Set `UTEKI_USE_MOCK_LLM=false` plus a provider env to do a
real-LLM smoke run of T3/T4 (slow + costs money).

## Chains

| # | File | What it proves |
|---|---|---|
| T1 | `test_01_auth_chain.py` | register → /me → refresh rotation → family-burn → logout (cookie clear) + 4 contract assertions (no email enumeration, generic invalid-token, kind protection, dup→409) |
| T2 | `test_02_isolation.py` | Cross-user 404 on every surface (run/events/artifacts/eval-history) + filesystem partition + same-session_id memory isolation |
| T3 | `test_03_research_chain.py` | The product flow: SSE parse → event contract → run persists → usage rolled up → summary materialised |
| T4 | `test_04_pipeline_chain.py` | File-based agent communication: planner+research+evaluator leave behind {plan.md, sprint-contract.json, research.md, eval-report.json}; wire-events match disk listing |
| T5 | `test_05_eval_chain.py` | `/api/eval/run` writes EvalRecords under the caller's partition; `/eval/history` is caller-scoped; `drift_monitor` reads `"system"` partition only |

## Observability

`conftest.Reporter` prints each chain step:

```
┌──────────────────────────────────────────────────────────────────────
│ E2E · test_research_chain_end_to_end
├──────────────────────────────────────────────────────────────────────
│ ▶ POST /api/agent/chat (SSE, mock LLM)
│     HTTP status = 200
│     content-type = text/event-stream; charset=utf-8
│     event count = 14
│       · run_start  {'agent': 'research', 'session_id': 'e2e-session-1'}
│       · plan       {'steps': [...]}
│       · step_start {'title': 'Scope the ask'}
│       ...
│ ▶ event contract
│   ✓ first is run_start
│   ✓ last is done
│   ✓ saw plan
│   ...
└── pass · test_research_chain_end_to_end
```

Run with `-x` to stop on first failure during iteration. Run without
to get the full picture (multiple chains' traces side-by-side).

## Iteration loop

1. Make a change.
2. `./scripts/e2e.sh -x` — fast feedback, stops at the first broken chain.
3. Read the failing chain's trace — `▶` and `·` lines show what
   happened before the assertion fired, so the diagnosis comes from
   the trace, not from re-running with prints.
4. Fix + commit + re-run.

## Why TestClient + in-proc store

In-process FastAPI TestClient + shared singletons means tests run in
~3-4 seconds and don't need port wrangling, DB containers, or Docker.
The contracts being verified (HTTP shape, store partition, SSE frame
format, artifact disk layout) are observable from in-proc just as
faithfully as from a real uvicorn process. Real-server tests would
add cost without adding signal.
