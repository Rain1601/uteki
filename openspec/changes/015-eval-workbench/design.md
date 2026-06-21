# 015 · Design

## 信息架构 — 6 屏 + 1 个 widget

```
                   ┌───────────────────────┐
                   │   /eval-bench         │  Screen 1 · Overview
                   │   (套件登陆 + 改动队列) │
                   └─┬─────────────────────┘
                     │
       ┌─────────────┼─────────────┬──────────────┐
       │             │             │              │
       ▼             ▼             ▼              ▼
  /suites/[id]   /compare      /trends       /backtest
  Screen 2       Screen 3 ★    Screen 5       Screen 6
  套件详情       A/B 对照页     纵向监控       预测命中率
  edit query     **核心**       时间序列        SPY 相对收益


  /runs/[id]?view=metrics  ← Screen 4 · 单 run 度量解构
  (复用 /runs 详情页加 tab,不新建路由)


  prompt-change widget on /skills/[name]  ← 7 · 内嵌组件
  ("v3 → v4 unverified" 状态条 + 一键跑 bench 按钮)
```

★ 最高 ROI 屏 — 第一版 MVP 必须做。

---

## 数据模型 deltas

### 新表 1 · `benchmark_suite`(套件 — 一组 query 的命名集合)

```python
class BenchmarkSuite(SQLModel, table=True):
    __tablename__ = "benchmark_suite"

    id: str = Field(primary_key=True)                # short hex
    name: str                                        # "mega-cap baseline"
    description: str = ""
    skill_name: str                                  # e.g. "company_research_pipeline"
    queries: list[dict] = Field(default_factory=list, sa_type=JSON)
    # queries: [{"ticker": "GOOGL", "peers": ["MSFT","META"], "question": "..."}, ...]
    created_by: str                                  # user_id
    created_at: float = Field(default_factory=time.time)
    cron_schedule: str | None = None                 # "0 6 * * *" or None
```

主键 `id`,**不**按 user 分区(套件是 admin 全局资源)。

### 新表 2 · `benchmark_run`(一次 bench 执行的元数据)

```python
class BenchmarkRun(SQLModel, table=True):
    __tablename__ = "benchmark_run"

    id: str = Field(primary_key=True)
    suite_id: str = Field(foreign_key="benchmark_suite.id")
    mode: str                                        # "A_quality" | "B_smoke"
    skill_name: str
    skill_version_a: str                             # baseline (e.g. "v3")
    skill_version_b: str | None = None               # comparison (v4),smoke 单版本时 NULL
    n_per_query: int                                 # 3 (A) / 1 (B)
    temperature: float                               # prod default (A) / 0.0 (B)
    triggered_by: str                                # "user" | "cron" | "auto_hash"
    triggered_at: float = Field(default_factory=time.time)
    finished_at: float | None = None
    status: str = "queued"                           # queued|running|done|error
    run_ids: list[str] = Field(default_factory=list, sa_type=JSON)
    # 所有 fan out 的 child Run.id,N=3 时含 60 个,N=1 时含 10 个
    metrics_summary: dict = Field(default_factory=dict, sa_type=JSON)
    # 聚合后的指标矩阵,Screen 3 直接渲染
```

### 新表 3 · `prediction`(回测层的记账)

```python
class Prediction(SQLModel, table=True):
    __tablename__ = "prediction"

    run_id: str = Field(primary_key=True)
    user_id: str                                     # owner(允许 system uid for bench-triggered)
    skill_name: str
    skill_version: str
    ticker: str
    action: str                                      # BUY | WATCH | AVOID
    conviction: float                                # 0-1
    t0: float                                        # 预测时刻(epoch s)
    t0_price: float                                  # 当时收盘价(进表时拉)
    horizons_to_score: list[int] = Field(default=[30, 90, 180], sa_type=JSON)
    outcomes: dict = Field(default_factory=dict, sa_type=JSON)
    # outcomes: {"30d": {"price": 245.6, "stock_pct": +5.2, "spy_pct": +2.1, "hit": true},
    #            "90d": ..., "180d": ...}
```

主键 `run_id`(每条 run 最多一条 prediction —— action 是 verdict 字段)。**不**用 user_id 分区 —— 即使 bench-triggered 也用真实股票,跨用户聚合需要全局表。

### 复用既有 — 不动 schema

- `Run` 表 + `Run.auto_score` + `Run.score_breakdown`:**bench 跑出来的 child run 跟正常 prod run 走同一张表**,只是 `triggered_by="eval_bench"`
- `RunFeedback`:用户手动 👍/👎 仍然走 013 的表
- `JudgeDispatcher`:bench 跑完一条 run 仍然走同一条评分管线

---

## Metric Catalog(度量目录)

按 Q2 你的决定,4 层全要。每层落到一个明确的"计算位置":

### Layer 1 · Structural(纯 Python,任何 run 跑完都算)

| 指标 | 实现 |
|---|---|
| `gate_completeness` | 6 个 gate 文件 × (Key findings / Analysis / Gate conclusion) 三段都在 → 6/6 |
| `word_floor_adherence` | gate 字数在 prompt 声明的下限以上 → % |
| `sources_policy_compliance` | 每个 gate 必引来源类型出现率 → % |
| `hedge_phrase_count` | "需进一步关注" / "综合考虑" / "拭目以待" / "可能值得" / "仅供参考"  正则计数 |
| `banned_addon_count` | "执行摘要" / "免责声明" / "TL;DR" / "希望此分析" 正则计数 |
| `verdict_stance_clarity` | gate conclusion 含 PASS/NEUTRAL/FAIL 或 BUY/WATCH/AVOID 关键词 → bool |
| `verdict_trigger_present` | gate conclusion 含 "当 X 时" / "若 Y 则" → bool |

入口:新增 `eval/metrics/structural.py`,挂在 `JudgeDispatcher.score_run()` 调用链(013 PR β 已经的位置)。

### Layer 2 · LLM rubric judge(复用 013 PR β + 扩 axis)

| 指标 | 实现 |
|---|---|
| `judge_outcome_score` | 已有 — outcome judge 0-100 |
| `judge_information_density` | 新增 — "信息密度"轴 1-5 |
| `judge_argument_strength` | 新增 — "论证力度"轴 1-5 |
| `judge_actionability` | 新增 — "可操作性"轴 1-5 |
| `judge_internal_consistency` | 新增 — "6 gates 是否互相矛盾"1-5 |

入口:`eval/judges/outcome.py` 加 4 个新 axis prompt。跨家模型(Anthropic 评 DeepSeek 输出)避免 self-grading bias。

### Layer 3 · Human label(复用 013 RunFeedback)

- 👍 / 👎 / 🚩 已经有
- 新增:`baseline_label` ∈ {"success", "failure"} —— **专给 PR ε 的 20 条 baseline 用**
- 在 RunFeedback 表加一个 nullable `baseline_label` 列(SQLModel 兼容 ALTER)

### Layer 4 · Backtest(新增 — 最复杂)

| 指标 | 实现 |
|---|---|
| `prediction_outcome_30d` | finish_run 时进 Prediction 表,daily cron 扫到期 |
| `prediction_outcome_90d` | 同上 |
| `prediction_outcome_180d` | 同上 |
| `hit_rate_by_action` | aggregate(BUY/WATCH/AVOID hit rate) |
| `hit_rate_by_skill_version` | aggregate per (skill_name, skill_version) |
| `signal_strength` | hit × conviction(高 conviction 错的扣分更多) |

**hit 定义(D1 你拍的)**:
```
BUY:   stock_pct - spy_pct >= 0   → hit
AVOID: spy_pct - stock_pct >= 0   → hit
WATCH: 不计入分母也不计入分子
```

入口:
- `prediction/store.py` 新表 + CRUD
- `prediction/scoring_cron.py` 日 cron(`celery` / `apscheduler` / sample-style asyncio task)
- `tools/market_history.py` 新增 — yfinance 历史价拉取(单文件,~50 行)

---

## 触发器

### Mode B 触发(快、便宜)

- **手动**:Screen 1 的"Run smoke" 按钮
- **自动**:EvolutionStore 检测到 prompt hash 变化 → 在 Screen 1 显示"⚠ unverified"状态,**不强跑** —— 用户手动按按钮跑(这是 D2 你的"轻起步"选择)

### Mode A 触发(慢、贵)

- **手动**:Screen 1 / Screen 3 的"Run quality bench" 按钮
- **cron**:每周一 06:00 UTC 跑所有 active suite × current production version(单边 baseline,不需要 v_old vs v_new,纯回归监控)

### Backtest 触发

- **每次 finish_run 时**:如果 skill 是 company_research_pipeline 且 verdict.action 存在 → 写一行 Prediction
- **每日 06:30 UTC cron**:扫所有 t0 + 30/90/180 已到的 Prediction,拉历史价,更新 outcomes
- **触发清单**:每周/每月生成 hit rate by version 报告

---

## API 端点

```
GET   /api/admin/eval/suites              list_suites
POST  /api/admin/eval/suites              create_suite
PATCH /api/admin/eval/suites/{id}         update_queries
DELETE /api/admin/eval/suites/{id}        delete_suite

POST  /api/admin/eval/run                 trigger bench run
        body: {suite_id, mode, version_a, version_b?}

GET   /api/admin/eval/runs/{id}           bench run detail + matrix
GET   /api/admin/eval/runs?suite_id=X     bench run history

GET   /api/admin/eval/trends?metric=X     time series (Screen 5)
GET   /api/admin/eval/backtest            backtest aggregate (Screen 6)
GET   /api/admin/eval/predictions         per-prediction list
```

所有路由 `Depends(require_admin)`。

---

## UI Surface

### Screen 1 · `/eval-bench` (Overview + recent prompt changes)

详见 `ui-mocks/01-overview.md`(待写)。核心:**入口屏列出可触发的 bench + 最近 prompt 变更队列**。

### Screen 2 · `/eval-bench/suites/[id]` (Suite detail)

详见 `ui-mocks/02-suite-detail.md`(待写)。核心:**编辑 query 集 + 查看历史 bench run**。

### Screen 3 · `/eval-bench/compare` ★ A/B Compare

详见 `ui-mocks/03-ab-compare.md`(本批次先写)。核心:
- 选择 baseline suite + version_a + version_b
- 跑 / 拉缓存
- 渲染 5 维矩阵(结构 / 行为 / 引用 / judge / cost)
- per-query 钻取
- "Approve & ship" / "Reject" 决策按钮(反模式守则的人工卡口)

### Screen 4 · `/runs/[id]` (Run detail · 加 backtest widget)

**决策 R4(2026-06-22)**:backtest widget 不藏在 `?view=metrics` tab 后面,
直接放在 **`/runs/[id]` 主页右栏**,跟 013 现有的 `RunRatingPanel` 并列。

理由:
- 每个 admin 进 run 详情都想看 "自预测以来标的走了多少",不该多点一次
- /runs/[id] 主页变成 "预测内容 + 实际表现 + 人工标签" 三位一体
- 在概念上 backtest widget 跟 RunRatingPanel 同位(都是"对这条 run 的事后审视"),
  并列展示一致性更好

右栏布局(自上而下):
1. **Backtest widget**(015 PR ε 新加)— entry → now 实时 + 30/90/180d horizon
2. **RunRatingPanel**(013 既有)— 👍/👎/🚩 + auto_score reveal-after-label
3. **Structural metrics summary**(015 PR β,可选)— 7 个 structural 指标的 compact 显示

完整 mockup:`ui-mocks/demo/04-run-with-backtest.html`(已实装)。

**保留备选**:`/runs/[id]?view=metrics` tab 仍然有意义 — 展示**完整**的
structural + judge + bench context(主页右栏只展示 backtest summary)。
metrics tab 是"详情",主页右栏 widget 是"摘要"。

### Screen 5 · `/eval-bench/trends` (Longitudinal)

详见 `ui-mocks/05-trends.md`(待写)。核心:**时间序列图**(hedge rate / citation density / WATCH% / structural pass rate)。一条线一个 skill version。

### Screen 6 · `/eval-bench/backtest` (Backtest aggregate)

详见 `ui-mocks/06-backtest.md`(待写)。核心:**hit rate by action × by version** + per-prediction drill-down。

### Widget · `/skills/[name]` prompt-change 状态条

详见 `ui-mocks/07-skill-page-widget.md`(待写)。核心:在 skill 详情页顶部加一条:
```
⚠ v3 → v4 unverified
[Run smoke ~5min $2.5]  [Run bench ~50min $15]  [Mark verified manually]
```

---

## 关键 trade-offs

### T1 · 为什么不为每条 prediction 立刻拉历史价?

`yfinance.history` 单 ticker 单查询 0.5-1s。N 条 prediction × 3 horizons = 3N 次调用。每天 cron 批量拉 5min 内搞定,实时拉浪费 + 容易触 rate limit。

### T2 · 为什么 Prediction 不用 user_id 分区?

回测要按 skill_version aggregate 跨用户:"v3 在所有用户上的 BUY 命中率"。分区后 admin 跨用户 query 要 join。**跨用户聚合是 admin 操作,本来就不该 user 分区**。Run 数据本身仍然 user 分区,这里只是镜像 verdict 字段做 aggregate.

### T3 · 为什么 BenchmarkSuite 不分 user?

Suite 是 admin 全局资源(对 prompt 改动的客观验证集),不该有用户私有 suite。第一版 hard-coded 一个 "mega-cap baseline" 套件就够。第二版要私有 suite 时再加 user_id 列。

### T4 · Mode A N=3 怎么实现并发 fan-out

可以利用刚修复的 `SkillRegistry.create()`(commit 009a941)—— concurrent 跑 N 次同 query 不再撞 singleton state。直接 `asyncio.gather(*[run_one() for _ in range(N)])`。这是 015 能成立的**前提**,没有 009a941 这事根本做不了。

---

## 非目标(再次明确)

- ❌ 自动改 prompt:eval workbench 只读 prompt 文件,不写
- ❌ 给普通用户暴露:第一版只 admin,等 alpha 用户成熟再考虑
- ❌ 多 skill 一次性上:第一版只 company_research_pipeline,research / earnings 等 v2 再覆盖
- ❌ 复杂市场基准:hit 定义就是 vs SPY,不做 sector ETF / risk-adjusted
- ❌ inter-rater calibration:Phase 2,等真有第二个 labeler

---

## Resolved decisions

### R1 · mega-cap baseline 10 ticker(2026-06-21)

固定 10 个 US 大盘:**GOOGL / MSFT / NVDA / AAPL / META / AMZN / TSLA / AMD / AVGO / NFLX**。

NFLX 严格意义不是 mega-cap(2026-06 市值 ~$300B,卡在临界),但保留是因为:
- 跟其它 9 个互补(content + subscription 商业模式,跟硬件 / 广告 / 云不重叠)
- 给 fisher_qa Q1(市场空间)创造一个"竞争激烈、增长见顶"的样本

### R2 · LLM rubric judge 跨家(2026-06-21)

判官用 **anthropic/claude-sonnet-4-6** 评 **deepseek/deepseek-chat** 的输出。理由:
- Anthropic 在 [Demystifying Evals] 文章里明示 self-grading 偏差是已知坑
- 跨家虽然 API key 贵 5x,但 judge 调用相对少(每条 run 1 次,~$0.05),总成本 < 整体 LLM 预算的 10%

### R3 · Trends 图时间轴 — 日历轴 + 版本颜色分段(2026-06-21)

X 轴 = **日历日**,版本用**颜色分段** + **竖虚线标记转换处**。同时满足两个用例:
- 看横向位置 → 时间漂移监控
- 看颜色分段 → 版本归因
- 看竖虚线 → 改动事件标记

Recharts 实现:`LineChart` + 多 `Line`(按版本切片) + `ReferenceLine` 标版本转换日期。

**保留的备选方案**(若 R3 实际跑起来不顺,可降级)：

- **纯版本轴(per-version)**:每个版本一个数据点,完全忽略时间。**优点**:版本归因清晰,实现简单。**缺点**:看不到同一版本内部漂移(例如某天上游数据源 down 导致 metric 退化,版本轴看不到拐点)。
- **纯日历轴(per-day)**:每天一个均值点。**优点**:漂移监控直接。**缺点**:版本短命(几小时寿命的 hotfix)时归因失败,看不出哪次改动起作用。
- **双轴切换 toggle**:头部加 "calendar / version" 切换按钮。**优点**:不强制选择。**缺点**:用户每次进页面要做无意义选择,违反"默认正确"原则。

R3 的"日历 + 颜色 + 竖虚线"是综合最优,只在 Recharts 渲染 100+ 个数据点性能跑不动时降级为纯版本轴。

## Still-open questions(写代码前还需 align)

- [ ] 数据多到多少需要降到纯版本轴?(预估 6 个月 prod 数据 = ~180 天 × 10 ticker × 平均 3 run/天 = ~5400 点,Recharts 应该撑得住)
- [ ] LLM rubric 4 个新 axis 的 prompt 怎么写?(留给 PR β 实施时设计 + LLM iterate)
