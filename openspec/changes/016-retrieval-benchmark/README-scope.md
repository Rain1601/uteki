# 016 · Scope boundary — pin this in your memory before touching the code

> If you find yourself measuring whether the agent's *judgment* was right, **STOP**.
> By design that is not in scope here.

---

## In scope (this benchmark measures these)

**Pipeline fidelity.** Did the agent's *information processing* work correctly?

- **Retrieval correctness** — did the agent surface the right documents from the corpus?
- **Contradiction handling** — when the corpus contains opposing views, did the agent show both sides?
- **Temporal honesty** — did the agent refuse to cite documents whose `observed_at > as_of_date`?
- **Numeric fidelity** — when the agent stated a number, did it match the source byte-for-byte?
- **Abstention honesty** — when the corpus genuinely doesn't contain the answer, did the agent say "not found" rather than invent one?

Each of these has an **objective oracle** (a person-written ground-truth file, or a content-hash on a source doc, or an explicit list of doc ids). Scoring is determinstic and fast. Suitable for CI gates.

---

## Out of scope (this benchmark does **not** measure these — do not build anything that does)

**Investment-judgment correctness.** Did the agent's BUY/AVOID call play out?

- ❌ Returns, hit rate, PnL, "did the recommended action beat SPY"
- ❌ Conviction calibration ("the agent was 0.8 confident and right 80% of the time")
- ❌ Sector / macro insight quality
- ❌ Writing style, persuasiveness, customer satisfaction signals

These are explicitly excluded because:

1. **Long latency.** A 90-day horizon turn cannot serve as a CI feedback loop. By the time you know if v4 was right, you've shipped v9.
2. **Strong noise.** TSLA going up 30% in 90 days might be Fed pivot, semi cycle, retail sentiment — none of which has anything to do with whether the agent's reasoning was correct.
3. **Not attributable.** You cannot decompose "agent was right" into (reasoning quality × market noise × luck). A benchmark that conflates these will reward the agent that happens to BUY in a bull market regardless of whether it found the right evidence.

**Worst failure mode if we ignored this:** an agent that learns to BUY everything in a bull market and AVOID everything in a bear market would get *high benchmark scores* on a PnL-gated benchmark, while its retrieval, citation, and honesty quality silently degrades. We would have built a metric that rewards the opposite of what we want.

---

## Where outcome / PnL signals *do* belong

- **PR ε backtest widget** (`/runs/[id]` right pane) — single-run UX display. Users see "my prediction → 30/90/180d outcome". Per-run only, never aggregated, never gates CI.
- **Trends dashboards** for human curiosity. Never used to block a merge.
- **Quarterly review** — long-cycle calibration, looked at by humans.

These are *observability*, not *benchmarks*. The distinction is whether the signal blocks a CI workflow. If it does → it's a benchmark → it must be in-scope above. If it doesn't → fine to build, but call it observability.

---

## The line you cannot cross

> **No PnL, hit-rate, or outcome-derived signal is ever permitted to enter the benchmark score or any CI gate.**

If a future contributor wires up "hit rate by skill version" → CI block, they have violated this contract. The contract holds because:

- 015 eval-workbench Mode A (LLM judge on prompt quality) — in scope of 015, not 016. Subjective signal, blocked from CI by 015's own design.
- 015 eval-workbench Mode C (PnL backtest) — **deliberately not built**. The original plan listed Screen 6 "hit rate by version"; that idea is canceled per this scope.
- 016 retrieval benchmark — what this directory specifies. Deterministic + bounded judge.

The benchmark and the observability dashboards can coexist. They must not be confused.
