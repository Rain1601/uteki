# Screen 3 · A/B Compare — 完整 mockup

> 这是整个 eval workbench 的核心屏。其它屏要么导引到这里,要么从这里下钻。
> 任何 prompt 变更走到 ship 之前**必须**先在这屏看完矩阵 + 点 Approve。

---

## 路由与入参

```
/eval-bench/compare?suite=<id>&va=<version_a>&vb=<version_b>
/eval-bench/runs/<bench_run_id>     ← 同一组件,带 bench_run_id 直接展示
```

- 不带参数 → 进 "selector" 状态(选 suite + 版本)
- 带 `suite/va/vb` → 拉缓存,如缓存命中 → 直接渲染;无缓存 → 提示 "Run now (~50min · $15)"
- 带 `bench_run_id` → 已完成 / 跑动中,直接展示对应 BenchmarkRun

---

## State 矩阵

| State | 描述 | 渲染 |
|---|---|---|
| `empty` | 还没选 suite | Suite selector + 引导文案 |
| `selector` | 选了 suite,但 va/vb 没选 | Version dropdown(从 EvolutionStore 拉所有版本) |
| `cached` | va vs vb 之前跑过 → 缓存命中 | 直接渲染矩阵(标 "cached · 6h ago") |
| `idle_uncached` | va vs vb 没跑过 → 需要触发 | 显示 "Run now (~50min · $15)" 按钮 |
| `running` | bench_run 正在跑 | Progress bar (0/60 → 60/60) + cancel 按钮 + ETA |
| `done` | 跑完 | 完整矩阵 + per-query 表 + 决策按钮 |
| `error` | bench_run 失败 | error 详情 + retry |

---

## 完整 mockup · `done` state

```
╔══════════════════════════════════════════════════════════════════════════╗
║  ← Back to /eval-bench                                                   ║
║  ─────────────────────────────────────────────────────────────────────   ║
║                                                                          ║
║  A/B COMPARE · mega-cap baseline                                         ║
║                                                                          ║
║  Skill:    company_research_pipeline                                     ║
║  Baseline: v3 (signed off 2026-06-15)                                    ║
║  Candidate: v4 (current draft, hash a3c7…)                               ║
║  Mode A · Quality bench · N=3 median · T=prod default                    ║
║  Run at:   2026-06-21 22:30 UTC · 52min · $14.85 · 60 child runs        ║
║                                                                          ║
║  [ View raw runs ]  [ Re-run ]                                           ║
║                                                                          ║
║  ════════════════════════════════════════════════════════════════════    ║
║                                                                          ║
║  ┌────────────────────────────────────────────────────────────────────┐  ║
║  │  DIMENSION                v3 (n=30)   v4 (n=30)    Δ        verdict│  ║
║  ├────────────────────────────────────────────────────────────────────┤  ║
║  │                                                                    │  ║
║  │  STRUCTURAL                                                        │  ║
║  │   gate completeness        8.7 / 10    9.8 / 10    +12.6%   ⬆ pass │  ║
║  │   word floor adherence     62%         95%         +33pp    ⬆ pass │  ║
║  │   sources policy coverage  71%         92%         +21pp    ⬆ pass │  ║
║  │                                                                    │  ║
║  │  BEHAVIORAL                                                        │  ║
║  │   hedge phrases / run      2.4         0.3         -88%     ⬆ pass │  ║
║  │   banned addons / run      1.1         0.0         -100%    ⬆ pass │  ║
║  │   WATCH default rate       60%         35%         -25pp    ⬆ pass │  ║
║  │   verdict trigger present  20%         70%         +50pp    ⬆ pass │  ║
║  │                                                                    │  ║
║  │  CITATION                                                          │  ║
║  │   density per gate         22.5        42.3        +88%     ⬆ pass │  ║
║  │   tier-1 src share         54%         61%         +7pp     ⬆ pass │  ║
║  │   [src:none] rate          18%         12%         -6pp     ⬆ pass │  ║
║  │                                                                    │  ║
║  │  LLM RUBRIC                                                        │  ║
║  │   information density      3.4 / 5     4.1 / 5     +0.7     ⬆ pass │  ║
║  │   argument strength        3.1 / 5     3.9 / 5     +0.8     ⬆ pass │  ║
║  │   actionability            2.9 / 5     4.0 / 5     +1.1     ⬆ pass │  ║
║  │   internal consistency     3.8 / 5     4.2 / 5     +0.4     ⬆ pass │  ║
║  │                                                                    │  ║
║  │  COST                                                              │  ║
║  │   tokens / run             18.4K       23.1K       +26%     ⬇ regr │  ║
║  │   $ / run                  $0.18       $0.23       +28%     ⬇ regr │  ║
║  │   wall_time / run          184s        236s        +28%     ⬇ regr │  ║
║  │                                                                    │  ║
║  │  BACKTEST (carry-over)                                             │  ║
║  │   30d hit rate            55% (n=20)  [pending]    -       ─ wait  │  ║
║  │   180d hit rate           62% (n=8)   [pending]    -       ─ wait  │  ║
║  │                                                                    │  ║
║  └────────────────────────────────────────────────────────────────────┘  ║
║                                                                          ║
║  ════════════════════════════════════════════════════════════════════    ║
║                                                                          ║
║  PER-QUERY VERDICTS                            [click row to drill]      ║
║                                                                          ║
║  ┌────────────────────────────────────────────────────────────────────┐  ║
║  │  Ticker  Question                v3 action / conv  v4 action / conv│  ║
║  ├────────────────────────────────────────────────────────────────────┤  ║
║  │  GOOGL   long-term value        WATCH 0.45         WATCH 0.55  ─   │  ║
║  │  NVDA    long-term value        WATCH 0.40         BUY 0.80   ⬆⬆  │  ║
║  │  TSLA    long-term value        WATCH 0.30         WATCH 0.30  ─   │  ║
║  │  AAPL    long-term value        BUY 0.65          BUY 0.70    ⬆   │  ║
║  │  MSFT    long-term value        BUY 0.60          BUY 0.65    ⬆   │  ║
║  │  META    long-term value        WATCH 0.50         BUY 0.65   ⬆⬆  │  ║
║  │  AMZN    long-term value        WATCH 0.45         WATCH 0.55  ─   │  ║
║  │  AMD     long-term value        WATCH 0.35         WATCH 0.45  ─   │  ║
║  │  AVGO    long-term value        BUY 0.55          BUY 0.65    ⬆   │  ║
║  │  NFLX    long-term value        AVOID 0.50         AVOID 0.65 ⬆   │  ║
║  └────────────────────────────────────────────────────────────────────┘  ║
║                                                                          ║
║   stability: 28 / 30 queries deterministic (same action across N=3)      ║
║   unstable:  2 / 30 — AAPL (v4 BUY×2 / WATCH×1), AMD (v3 unstable)      ║
║                                                                          ║
║  ════════════════════════════════════════════════════════════════════    ║
║                                                                          ║
║  SUMMARY                                                                 ║
║                                                                          ║
║  ✓ 13 / 13 quality dimensions improved or held                          ║
║  ✓ 0 hedge regressions                                                  ║
║  ⚠ Cost regression +28% — driven by longer Analysis sections            ║
║                          (acceptable: word floors are the cause)        ║
║  ─ Backtest data carry-over from v3, v4 not yet matured                 ║
║                                                                          ║
║  ════════════════════════════════════════════════════════════════════    ║
║                                                                          ║
║  DECISION                                                                ║
║                                                                          ║
║  ┌────────────────────────────────────────┐                             ║
║  │ [ ✓ Approve v4 → ship to prod ]        │  ← writes metrics_summary  ║
║  └────────────────────────────────────────┘     .approved_by = you      ║
║                                                  + skill version bump   ║
║                                                                          ║
║  ┌────────────────────────────────────────┐                             ║
║  │ [ ✗ Reject · keep v3 ]                 │  ← writes .rejected_by      ║
║  └────────────────────────────────────────┘     + reason text field     ║
║                                                                          ║
║  ┌────────────────────────────────────────┐                             ║
║  │ [ ⟳ Hold · re-run with seed 42 ]       │  ← N=3 不够稳,加 seed      ║
║  └────────────────────────────────────────┘     再跑一遍                ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Mockup · `running` state

```
╔══════════════════════════════════════════════════════════════════════════╗
║  ← Back to /eval-bench                                                   ║
║                                                                          ║
║  A/B COMPARE · mega-cap baseline                                         ║
║  Mode A · v3 vs v4 · N=3                                                 ║
║                                                                          ║
║  Status:  RUNNING                                                        ║
║                                                                          ║
║  ┌────────────────────────────────────────────────────────┐             ║
║  │ ▓▓▓▓▓▓▓▓▓▓▓▓░░░░░░░░░░░░░░░░░░░░░░░░░░░░  37 / 60     │             ║
║  └────────────────────────────────────────────────────────┘             ║
║                                                                          ║
║  Elapsed:  18m 24s                                                       ║
║  ETA:      ~30m remaining                                                ║
║                                                                          ║
║  Per-query progress:                                                     ║
║    GOOGL    v3 ▓▓▓ 3/3  v4 ▓▓▓ 3/3   ✓                                  ║
║    NVDA     v3 ▓▓▓ 3/3  v4 ▓▓░ 2/3                                      ║
║    TSLA     v3 ▓▓▓ 3/3  v4 ▓░░ 1/3                                      ║
║    AAPL     v3 ▓▓░ 2/3  v4 ░░░ 0/3                                      ║
║    MSFT     v3 ▓░░ 1/3  v4 ░░░ 0/3                                      ║
║    META     v3 ░░░ 0/3  v4 ░░░ 0/3                                      ║
║    ... 4 more pending                                                    ║
║                                                                          ║
║  Live cost so far:  $9.25                                                ║
║                                                                          ║
║  [ Cancel run ]    (cancellation refunds in-flight tokens proportionally)║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Mockup · `idle_uncached` state

```
╔══════════════════════════════════════════════════════════════════════════╗
║  ← Back to /eval-bench                                                   ║
║                                                                          ║
║  A/B COMPARE                                                             ║
║                                                                          ║
║  Suite:    [ mega-cap baseline ▼ ]   10 queries                          ║
║  Baseline: [ v3 ▼ ]                                                      ║
║  Candidate:[ v4 (current draft) ▼ ]                                      ║
║                                                                          ║
║  ⓘ No cached bench run for this (suite, v3, v4) tuple.                  ║
║                                                                          ║
║  Estimated cost & time:                                                  ║
║    Mode A · 10 queries × 2 versions × 3 runs = 60 runs                   ║
║    Wall time: ~50min (parallel 5)                                        ║
║    Cost:      ~$15.00 (deepseek/deepseek-chat at $0.25/run)             ║
║                                                                          ║
║  ┌────────────────────────────────────────────────┐                     ║
║  │ [ ▶ Run quality bench now ]                    │                     ║
║  └────────────────────────────────────────────────┘                     ║
║                                                                          ║
║  Or: [ Run Format smoke first ]  (~5min · $2.5 · checks parser)         ║
║                                                                          ║
║  ─────────────────────────────────────────────────                       ║
║                                                                          ║
║  Existing bench runs for this suite:                                     ║
║    • v2 → v3   approved 2026-06-15   ratio v3/v2 = +18% judge          ║
║    • v1 → v2   approved 2026-05-21   ratio v2/v1 = +9% judge           ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## Drill-down · 点 NVDA 行钻入

```
╔══════════════════════════════════════════════════════════════════════════╗
║  ← Back to compare                                                       ║
║                                                                          ║
║  NVDA · v3 vs v4  ·  median run from each side                          ║
║                                                                          ║
║  ┌──────────────────────────────┬──────────────────────────────┐        ║
║  │ v3 verdict                   │ v4 verdict                   │        ║
║  │  action: WATCH · conv 0.40   │  action: BUY · conv 0.80    │        ║
║  │  one_sentence: NVDA 业务质量  │  one_sentence: NVDA 在 AI    │        ║
║  │  良好但估值偏高,综合考虑后    │  加速计算赛道拥有最宽护城河,  │        ║
║  │  暂时观望... [src:none]       │  当前 32.3 倍 PE 已反映乐观  │        ║
║  │                              │  预期...通过 4% 初始仓位 +   │        ║
║  │                              │  严格风险预算管理。[src:21]   │        ║
║  ├──────────────────────────────┼──────────────────────────────┤        ║
║  │ gate-02-fisher_qa            │ gate-02-fisher_qa            │        ║
║  │  total: 72 / 150              │  total: 108 / 150            │        ║
║  │  Q4: score=0 "缺乏数据支撑"    │  Q4: score=5 (174字详细分析) │        ║
║  │  Q7: score=0                  │  Q7: score=6                 │        ║
║  │  Q14: score=0                 │  Q14: score=5                │        ║
║  │  ...                         │  ...                         │        ║
║  ├──────────────────────────────┼──────────────────────────────┤        ║
║  │ gate-04-management           │ gate-04-management           │        ║
║  │  Gate conclusion:            │  Gate conclusion:            │        ║
║  │  "综合判断需进一步关注"        │  "管理层综合评分 8.5/10,    │        ║
║  │  (no trigger)                │  当 CEO 黄仁勋在无明确继任    │        ║
║  │                              │  者情况下宣布退休,或内部人    │        ║
║  │                              │  卖出规模持续超总持股 10%,    │        ║
║  │                              │  应下调至 NEUTRAL。本维度    │        ║
║  │                              │  评级 PASS"                  │        ║
║  └──────────────────────────────┴──────────────────────────────┘        ║
║                                                                          ║
║  [ See full v3 run → ]  [ See full v4 run → ]                           ║
║                                                                          ║
║  Hedge highlight diff:                                                   ║
║    v3 contains 3 hedge phrases (highlighted in red)                      ║
║    v4 contains 0 hedge phrases                                           ║
║                                                                          ║
║  [ ← back to matrix ]                                                    ║
║                                                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
```

---

## 决策按钮的实际行为

### `[ ✓ Approve v4 → ship to prod ]`

1. 弹 confirm 对话框:**"This will mark v4 as the production version. Continue?"**
2. PATCH `/api/admin/eval/runs/<bench_run_id>/decision` body `{decision: "approve", note?: ""}`
3. 后端做两件事:
   - 写 `BenchmarkRun.metrics_summary["approved_by"] = user_id` / `approved_at = now`
   - **不**自动 deploy / 不动 prompt(反模式守则) —— 只是登记决定
4. 用户看到 toast:**"v4 approved. Don't forget to deploy when ready."**

### `[ ✗ Reject · keep v3 ]`

1. 弹 textarea:**"Why reject? (required, will be saved)"**
2. PATCH `.../decision` body `{decision: "reject", note: "..."}`
3. 同样**不自动改 prompt**,只记录决策 + 理由
4. 如果用户要回滚 prompt,需要自己 `git revert`

### `[ ⟳ Hold · re-run with seed 42 ]`

1. 触发同样 mode/suite/va/vb 但 `random_seed=42`(只对 deepseek 起作用,API 支持)
2. 新建一个 BenchmarkRun row,带 `parent_run_id = current`
3. 跑完后侧边栏出现"View seed-42 re-run"
4. 用户对比两次跑的结果,如果稳定 → approve;不稳定 → reject

---

## 设计原则在这屏的体现

- **不藏数字**:13 个 quality dimensions 全显示,没分页/折叠
- **决策注脚**:三个按钮下方各有一行说明实际效果("writes metrics_summary..." / "not auto-deploy")
- **stability 显式标**:N=3 同 query 跑出不同 action 时,显式 "unstable" 标记 → 用户能看到 noise
- **cost regression 不隐藏**:即使其它 dimension 全绿,cost +28% 也用 ⬇ regr 标出,让用户**自己**决定要不要接受
- **backtest 显式说"等"**:不假装有数据,30/180d hit rate 标 [pending] + ─ wait

---

## 还没拍的细节(留给 PR δ 实现时)

- [ ] 矩阵每行能否点击展开 "show methodology"?(例如点 hedge_phrase_count → 弹小框列出我们认的 6 个正则)
- [ ] 钻取 drill-down 是同页 expand 还是新路由?(我倾向同页 expand 保持 URL deeplink 稳)
- [ ] N=3 的另外 2 个 run artifact 已删,如果用户想 forensic 怎么办?(目前只能看 RunStore 的 auto_score 不能看原文)
- [ ] "approved but not yet shipped" 的状态怎么表达 — Screen 1 应该有一个 "queued for ship" 区块?
