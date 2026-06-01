# 05 · Roadmap to v1 终态 — phases + 可见 demo

> Status: **live spec** (2026-05-27 onward). 跟实际进度对齐迭代。
> 用途：把"摊子开太大"问题约束成 5 个相互不阻塞的 phase，每个 phase
> 有具体可视化的"标靶 demo"——让"成功"长得有形，避免抽象空转。

## 一、为什么需要这份 spec

之前的状态：9 条工作面同时开着，每条都没完结。原因是我们用动词描述
任务（"自动化 self-evolution loop"、"接入真实工具"），但**动词不能
被验收**——验收需要看到具体产物。

这份 spec 的策略：每个 phase 用**一段可看可摸的 demo** 钉住目标，
然后从 demo 反推任务。Demo 数据可以 mock，但**形状必须确定**。

## 二、终态定义

**uteki v1** = 满足以下 6 项的最小集：

1. 多租户 production-deployable，10-50 用户日常使用
2. 5-10 个 leaf skill + 1-2 个 pipeline，**全部 backed by 真实数据**
3. Self-evolution loop **自动运行**（drift-triggered + 人审 G1/G2）
4. Web + iOS 至少一端可用
5. 可观察（cost / latency / pass_rate 跟踪 + 告警）
6. 7 个 tool 都有真实数据接入 + 配额管理

不在 v1 范围（明确推后）：

- Skill 市场 / 动态 skill 加载
- 私有化部署 / 自托管 LLM
- 团队 workspaces / 复杂 RBAC（自己用户够再说）

---

## Phase 1 · Self-evolution Loop 产品化（3 周）

**真实数据需要？** ❌ 不需要。

### 标靶 demo

跑完 Phase 1，**应该看到**这样一个完全自动生成的 proposal 目录：

```
data/evolution/proposals/P-2026-001/
├── meta.json
├── trigger.json
├── snapshot/
│   ├── run_artifacts/         (run R1 的完整 artifacts)
│   ├── skill/SKILL.md         (research v2 prompt 快照)
│   └── rubrics/               (cite_compliance.md 等 快照)
├── brief.md                   (喂给 CC 子进程的 prompt)
├── cc_run/
│   ├── invocation.json        ({"model": "opus-4-7", "started": "..."})
│   ├── transcript.jsonl       (CC 完整 tool_use 流)
│   ├── critique.md            (CC 写的 5 条 findings)
│   └── patch.diff             (建议改 SKILL.md 的 diff)
├── validation.json            (diff 能 apply？rubric YAML 有效？)
├── decisions/
│   ├── 001-triggered.json     ({"by":"system:drift_monitor","ts":"..."})
│   ├── 002-cc_review_done.json
│   ├── 003-pending_review.json
│   ├── 004-accepted.json      ({"by":"user:alice","reason":"clear finding"})
│   ├── 005-applied.json       ({"new_skill_version":"v3-proposed-aef1"})
│   ├── 006-ab_eval_done.json  ({"pass_rate_baseline":0.62,"pass_rate_proposed":0.78})
│   └── 007-adopted.json
└── post_apply/                (新 prompt 落盘 + version hash 记录)
```

以及——**操作员视角**长这样：

```
$ ./scripts/proposals review

3 proposals pending your review:

┌────────────────────────────────────────────────────────────────┐
│ P-2026-001  research v2 → v3-proposed                          │
│ Triggered: 2026-05-27 09:14 by system:drift_monitor            │
│ Source: 5 runs in last 24h, pass_rate=0.42 (down from 0.71)    │
│                                                                │
│ CC critique (4 findings):                                      │
│   • "sector overview" 5 处缺源 [^src]                          │
│   • cite_compliance 9 处用了模糊数字 vs 工具返回值              │
│   • 评估 LLM 5 段中 3 段不构成实际研究内容                     │
│   • [更多见 critique.md]                                       │
│                                                                │
│ Proposed diff: +18 lines / -3 lines on SKILL.md                │
│ Estimated A/B cost: $0.45 (12 cases x 3 runs)                  │
│                                                                │
│ [v] view critique.md   [d] view patch   [a] accept             │
│ [r] reject             [e] edit-then-apply   [skip]            │
└────────────────────────────────────────────────────────────────┘
> a
Reason for accept (optional): "matches pattern from P-2026-001 last week"
Applying patch...  OK
Running A/B (mock=false, 12 cases, 3 runs each)...
  baseline:  pass_rate=0.42  ($1.21 used)
  proposed:  pass_rate=0.78  ($1.34 used)  ↑ +36pp
Adopt?  [y/n] y
✓ adopted as research@v3-1c4e
✓ Slack notified
```

### 任务列表 + checkpoint

每个 task 是 1-2 天，每完成一个能演示一小段。

| # | Task | 验收点（手工 demo） |
|---|---|---|
| ✅ 1.1 | `data/evolution/proposals/<id>/` 目录 + meta.json 状态机 | T9 4/4 pass; status machine 18 个状态 + 终态保护; `POST /api/admin/review/<run_id>` 端到端 + 跨用户隔离 |
| ✅ 1.2 | Trigger 入口 `POST /api/admin/review/<run_id>` | (合并到 1.1 完成 — 不再单独算) |
| ✅ 1.3 | Spawn CC 子进程 + 收 critique.md + patches | T12 2/2 pass; `cc_runner` 走完 triggered → snapshotting → briefing → spawning → generating → validating → pending_review；snapshot/skill/SKILL.md + run_artifacts/* + brief.md + cc_run/{invocation,transcript,critique,patch} 全部落盘；`UTEKI_USE_MOCK_CC` 默认 mock，真 CLI 路径已就位；`POST /api/admin/proposals/<id>/run-cc` 后台跑 + idempotency 409 |
| ✅ 1.4 | Validate diff 能否 apply + rubric YAML 有效 | `validation.json` 写入 `{ok, reasons, stats}`；checks = critique 非空 + 至少结构性 finding + patch 是合法 unified diff + git apply --check 通过 + patch ≤ 60 +/- 行；坏 CC 输出 → invalidated；16 个 unit 测试 (`test_validators.py`) + T12 加 validation.json 断言 |
| ✅ 1.5 | G1 CLI review UI（demo 见上） | `./scripts/proposals` 渲染 list/show/accept/reject/defer/discard；finding 摘要 + validation 统计 + transition 链；操作员身份 `cli:$USER` 记审计；7 个 e2e (`test_13_proposals_cli.py`) 通过 subprocess 验证（含 `--root` 隔离 + 误状态 exit 3 + 未知 id exit 2） |
| ✅ 1.6 | Apply pipeline（git diff apply + reload + EvolutionStore record） | T14 5/5 pass; `evolution/apply.py`: accepted → applying → (a_b_eval \| apply_failed)；git apply -p1 inside live skill dir + 自动 path normalize (剥 `a/snapshot/skill/`)；post_apply/ 快照 + signature（M1.8 rollback 用）；EvolutionStore.record(SkillVersion) 带 parent + changelog + `params.applied_from_proposal`；skill cache_clear + system_prompt 热重载；`proposals accept` 默认 auto-apply，`--no-apply` 留给 edit-then-apply 流；`proposals apply <P-id>` 显式触发；端到端 demo trail 10 步 triggered → a_b_eval（操作员 1 句命令） |
| ✅ 1.7 | A/B eval 自动跑（EvalRunner pre/post） | T15 5/5 pass; `evolution/ab_eval.py`: 两遍跑 EvalRunner（proposed = 当前 live, baseline = snapshot 临时换上）；ab_summary 落到 Proposal + heartbeat transition 记录到 `decisions/<NNN>-a_b_eval.json`；schema = `{cases_run, pass_rate_baseline/proposed, delta_pp, latency_ms_*_mean, judge_score_*, ran_at, mode}`；CLI accept 默认 chain apply → ab_eval（`--no-ab` 跳过），`proposals ab-eval <P-id>` 显式触发；mock-llm smoke：4 cases / pass_rate 0.75 baseline=proposed / delta +0.0pp |
| ✅ 1.8 | G2 决策 + Rollback | T16 7/7 pass; `evolution/g2.py`: 三个 terminal verb — `adopt_proposal`/`rollback_proposal`/`inconclusive_proposal`，都要求 status=a_b_eval + ab_summary 已填；rollback 把 snapshot/skill/SKILL.md 写回 live、reload skill、记一个新 SkillVersion（`params.rolled_back_from=P-id` + `baseline_signature`），更新 `Proposal.applied_skill_signature` 为 baseline；adopt/inconclusive 是纯 transition（live 文件不动）；CLI 3 个 subcommand；闭环 demo：pending_review → adopted **12 步 transition / 2 句操作员命令** |
| 1.9 | Run.status 重塑 | API 返回新字段：`harness_status`, `evaluator_decision`, `overall_assessment` |
| 1.10 | Quality definition 统一 schema | sprint-contract + judges 引用同一份 criteria.json |
| ✅ 1.11 | drift_monitor 自动 trigger | T17 5/5 pass; `check_drift()` 升级：drift 检测到 → 找最近 EvalRecord.run_id → 查 Run 拿 skill → rate-limit（每 skill 最多 1 个 in-flight proposal）→ 创建 Proposal(triggered_by=system:drift_monitor) → inline 跑 cc_runner → 落到 pending_review；CLI `proposals drift-check` 手动触发；返回 `{alert, auto_triggered, auto_trigger_reason}` 给操作员可见；smoke：故意 today=0.40 vs week_ago=0.85 → 42pp drop → P-2026-001 自动出现 + cc_runner 走完到 pending_review |
| ✅ 1.12 | 跨 skill smoke：3 个不同 skill 走完整闭环 | T18 4/4 pass: parameterized 跑 research / earnings / planner 三个 leaf skill 各自走完整 create → cc_runner → accept → apply → ab_eval → adopt；外加 `test_three_skills_independent_in_same_root` 在同一个 ProposalStore 里依次跑 3 个 skill，验证 P-id 不冲突 + 每个 skill 独立的 EvolutionStore version 链 + provenance 互不污染 |

### Gate

**从一个 fresh checkout + UTEKI_AUTH_REQUIRED=false 启动**：
1. 跑一个故意低质量 research run（mock 注释里指定）
2. 等 6 小时（或手动 trigger drift_monitor.check_drift）
3. 看到 `data/evolution/proposals/P-2026-*/` 自动出现
4. `./scripts/proposals review` 看到 pending
5. accept → apply → A/B → adopt → version bump → eval pass_rate 提升

**无需任何人改一行代码**。

---

## Phase 2 · 真实工具接入（2-3 周）⚠ 需要数据决策

> **2026-05-27 决策**：v1 **US-only**。放弃 A 股市场，原因：数据质量与
> 一致性问题严重，做出来的研究质量上限低。集中火力做美股。

**真实数据需要？** ✅ 这就是数据集成阶段。

### 标靶 demo

跑完 Phase 2，**研究的产出长这样**（不是 mock 数据，是真实数据驱动）：

```markdown
# AI Infrastructure Semiconductors — Research Framework

## I. Market & growth (2023-2025)

AI accelerator market reached **$74B in 2024** [^1], up 142% YoY,
driven by hyperscaler capex doubling [^2]. Gartner projects **$157B
by 2027** at 28% CAGR [^3]. NVIDIA captured ~85% of data-center GPU
revenue in CY2024 [^4]; AMD MI300 ramping ($5.1B FY24 [^5]).

## II. Main public players

| Company | Ticker | FY24 Revenue | YoY | PE-TTM | Data as-of |
|---------|--------|-------------|-----|--------|------------|
| NVIDIA  | NVDA   | $130.5B [^6] | +114% | 48.2x [^6] | 2025-03-31 |
| AMD     | AMD    | $25.8B [^6]  | +14%  | 31.7x [^6] | 2025-03-31 |
| Broadcom | AVGO  | $51.6B [^6]  | +44%  | 38.4x [^6] | 2025-03-31 |
| TSMC    | TSM    | $90.0B [^6]  | +30%  | 22.1x [^6] | 2024-12-31 |
| ...

## Sources

[^1]: SEC EDGAR — NVDA 10-K FY24 (fetched 2026-05-27)
[^2]: web_extract: AWS/Azure/GCP Q4 earnings calls, capex commentary
[^3]: Gartner press release 2024-Q4 (web_extract:gartner.com/...)
[^4]: Mercury Research Q4 2024 GPU shipment data (news_search)
[^5]: SEC EDGAR — AMD 10-K FY24, segment disclosure
[^6]: yfinance ticker.info, fetched 2026-05-27 14:32 UTC
```

**对比 Phase 1 阶段的 mock 数据**：

| 项目 | Phase 1 (mock) | Phase 2 (real) |
|---|---|---|
| NVDA PE | "59.5x"（固定字符串）| 48.2x（yfinance 实时） |
| 市场规模 | "[UNSOURCED] 亿元" | "$74B in 2024 [^1]" 带源 |
| 数据日期 | 永远是 "2025" 字符串 | 真实 fetched_at timestamp |
| 引用 | "tool:market_quote" 无来源 | SEC EDGAR + yfinance + as_of |
| **CC critique 能 review 的内容** | 仅格式 | 数据准确性 + 推理合理性 |

### US-only 数据栈

放弃 A 股之后，数据源大幅简化。**4 个 provider，月成本 ~$44**：

| 工具组 | Provider | 覆盖 | 费用 | 备注 |
|---|---|---|---|---|
| **行情** (market_quote, kline) | **yfinance** | US + 全球主要市场，延迟 15min | $0 | rate-limited，但日常 retail 量够；prod 量大再换 polygon |
| **财报数据** (financials) | **FMP basic** | US 公司 income/balance/cashflow + ratios + insider | $14/月 | 全面 + REST + 适合 LLM tool 接口 |
| **法定文件** (report_analysis) | **SEC EDGAR** | 10-K / 10-Q / 8-K / S-1 全文 | $0 | 官方源 + 法律可信度满分 |
| **新闻 + 搜索** (news_search, web_search) | **Tavily** | LLM-optimized search，AP/Reuters/Bloomberg 等 | $30/月 | 直接返回 markdown + 引用 |
| **HTML 抓取** (web_extract) | 自建 (httpx + readability-lxml) | 任意 URL → clean markdown | $0 | 兜底 |

**总月度 $44**（Tavily $30 + FMP $14）。年 ~$528。

### 🚨 数据决策（4 个，去掉了 A 股相关的）

| Q | 决策 | 默认建议 | 影响 |
|---|---|---|---|
| Q1 | yfinance（免费）够还是直接上 polygon ($99/月)？ | **yfinance 起步**，量大或需要 real-time 再换 polygon | 成本 vs 数据新鲜度 |
| Q2 | FMP basic ($14/月) 还是 FMP premium ($50/月，含历史 30 年 + 全球）？ | **basic**，v1 不需要 30 年历史 | 财报深度 |
| Q3 | 新闻：Tavily 还是 newsapi.org ($449/月 business)？ | **Tavily**，LLM-optimized 直接好用 | 新闻质量 |
| Q4 | 月度数据预算上限 | **$50/月** | hard cap |

**默认全选**：4 决策都走默认 → **$44/月 + 无年付**。是最轻的可行解。

### 任务列表

| # | Task | 验收点 |
|---|---|---|
| 2.1 | 数据源决策（Q1-Q4）+ 测试 API key | yfinance 拉到 NVDA；FMP 拉到 AVGO income statement；Tavily 搜出近 30d 新闻 |
| 2.2 | `market_quote` 接 yfinance | curl 返回 NVDA 当日价格 + market_cap + PE |
| 2.3 | `kline` 接 yfinance + Redis 缓存（日线 24h，分钟线 5min） | curl 拉到 NVDA 30 日 K 线 |
| 2.4 | `financials` 接 FMP basic（income/balance/cashflow 三表 + ratios） | NVDA FY24 revenue=$130.5B，AMD FY24=$25.8B |
| 2.5 | `news_search` 接 Tavily | 拉到关于 "Blackwell shipping ramp" 的近 30d 新闻 |
| 2.6 | `report_analysis` 接 SEC EDGAR + pypdf 解析 10-K | 能抓 NVDA 2024 10-K 全文 + 解析风险因素章节 |
| 2.7 | `web_search` 接 Tavily（与 news_search 共享 API key） | 通用搜索返回 LLM-friendly markdown |
| 2.8 | `web_extract` 用 httpx + readability-lxml | 任意 URL → clean markdown |
| 2.9 | Tool result trust signals | `ToolResult` 新增 `{provenance, fetched_at, freshness, confidence}` |
| 2.10 | Per-user 配额追踪 + 月度费用累积 | `/api/users/me/usage` 返回当月 cost + per-tool 调用数 + per-data-provider 调用数 |
| 2.11 | 真实数据 + Phase 1 跑全闭环 | 3 个真实 US 数据 case 自动 evolved → critique 提及"数据陈旧"/"引用 SEC 文件却没引具体段落"等真实问题 |

### Gate

**Demo 输出标准**：跑 `research_pipeline("AI infrastructure semiconductors framework, focus NVDA AMD AVGO TSM, 500-800 words")` →
- final-research.md 包含 ≥ 5 个真实数字 + ≥ 5 个 `[^N]` 形式源引用
- 每个引用能追溯到具体 SEC filing URL / yfinance ticker + as_of timestamp
- judge_correctness ≥ 8, judge_cite_compliance ≥ 8
- **Phase 1 的 self-evolution loop 此时 review 的是数据准确性 + 引用规范，不再是格式**

**回归测试**：把同样问题给 mock 模式跑——Phase 1 的 review 应该指出"数据
缺失"作为最大问题（因为 mock 工具不返回真值）。这反过来验证了 evaluator
能识别"工具拿到了什么"vs"工具应该拿到什么"。

---

## Phase 3 · Operational Readiness（2 周）

**真实数据需要？** ❌

### 标靶 demo

部署后的 ops dashboard：

```
┌─── uteki ops · 2026-06-25 14:30 ──────────────────────────────┐
│                                                                │
│  Active runs:        3        7-day pass_rate:  0.78  ↗ +0.04 │
│  Today's spend:      $4.32    Month-to-date:     $87.50       │
│  Inflight users:     11       Slow runs (>2min): 0            │
│                                                                │
│  Recent alerts:                                                │
│  · 14:12  drift_monitor: research pass_rate 0.62 (-0.16)      │
│           → P-2026-014 auto-created                           │
│  · 13:45  cost: alice@test.com hit $5 cap (waiting)           │
│  · 12:01  recovery: 2 stale runs (>1hr running) reaped        │
│                                                                │
│  Pending proposals:  P-2026-014 (drift), P-2026-013 (manual)  │
│                                                                │
│  [press q to quit]                                            │
└────────────────────────────────────────────────────────────────┘
```

以及 Slack 里看到这样的告警：

```
🟡 uteki drift alert · 2026-06-25 14:12

skill: research
pass_rate dropped from 0.78 → 0.62 over last 24h
sample: 18 runs (12 cases × ~1.5 reps avg)

Auto-action: created P-2026-014, CC analyzing now
Operator queue: 2 (incl this one)

→ https://uteki.example.com/proposals/P-2026-014
```

### 任务列表

| # | Task | 验收点 |
|---|---|---|
| 3.1 | Memory 持久化（同 SqliteRunStore 模式）| 重启 API 后会话历史还在 |
| 3.2 | Run recovery: reaper 把 >2hr running 行扫成 interrupted | 手工 `kill -9` 然后重启，DB 行被标 interrupted |
| 3.3 | OpenTelemetry + Sentry 接入 | 一次 Run 在 Sentry 里能看到完整 trace |
| 3.4 | 用户级费用累积 + per-user cap | 设 $5 cap，用户跑超会被拒 |
| 3.5 | MCP service-account auth | UTEKI_AUTH_REQUIRED=true 下 MCP 仍能跑 |
| 3.6 | drift_monitor → Slack/钉钉 webhook | 故意造 drift，Slack 收到 alert |
| 3.7 | Docker compose（API + Postgres / SQLite + Redis 可选） | `docker compose up` 起来即可用 |
| 3.8 | Graceful shutdown | SIGTERM 后 inflight runs 完成才退出 |
| 3.9 | Prod deploy guide | 一个新手按 README 30 分钟部署成功 |
| 3.10 | 备份策略（SQLite → R2/S3 daily）| 备份 cron 跑了能在 S3 看到 ndjson |

### Gate

**在一台 EC2 t3.small + 一个域名上跑起来**：
1. 5 个外部 beta 用户连续用 1 周
2. 期间至少 1 次自动 drift alert 进了 Slack
3. 任意时刻 ops dashboard 能拉出来
4. 不需要任何手工干预

---

## Phase 4 · Mobile + Frontend 完善（3-4 周）

**真实数据需要？** ❌

### 标靶 demo

iOS 主屏（ASCII mockup）：

```
┌─────────────────────────────┐
│ ←   uteki     ⚙             │
├─────────────────────────────┤
│                              │
│   ◉ 中芯国际 Q3 评点         │
│      research_pipeline · ok  │
│      ¥0.31 · 2 min ago      │
│      ────────────────       │
│                              │
│   ◯ 半导体设备框架            │
│      research · running ▓░░  │
│      streaming...           │
│      ────────────────       │
│                              │
│   ◯ FOMC 6 月预期            │
│      qna · ok · ¥0.02       │
│                              │
│                              │
│   ┌─────────────────────┐   │
│   │  + 新研究            │   │
│   └─────────────────────┘   │
│                              │
└─────────────────────────────┘
```

Web 自我演化 dashboard：

```
┌──── uteki proposals · alice@test.com ──────────────────────────┐
│ Filter: [ pending ▼ ] [ all skills ▼ ]                        │
│                                                                 │
│ ┌─ P-2026-014 ─ research v2 → v3-proposed ──────────────────┐ │
│ │ drift-triggered  •  2 hours ago                            │ │
│ │ ────────────────────────────────────                       │ │
│ │ CC critique excerpt:                                       │ │
│ │   "sector overview 段缺 5 处数据源..."                     │ │
│ │                                                            │ │
│ │ Patch summary: +18/-3 lines                                │ │
│ │ A/B preview (4 cases × 1): 0.62 → 0.78 (+16pp)            │ │
│ │                                                            │ │
│ │ [Accept] [Reject] [Edit] [Defer]   [View full critique →] │ │
│ └────────────────────────────────────────────────────────────┘ │
│                                                                 │
│ ┌─ P-2026-013 ─ ...                                          │
└────────────────────────────────────────────────────────────────┘
```

### 任务列表

| # | Task | 验收点 |
|---|---|---|
| 4.1 | iOS shell (SwiftUI: SSO + list + chat + artifact viewer) | App store TestFlight build |
| 4.2 | iOS streaming via URLSession.AsyncBytes | 流式 deltas 实时显示 |
| 4.3 | iOS push notification when run completes | 后台收到通知 |
| 4.4 | Android Compose equivalent (4.1) | Play Store internal track |
| 4.5 | Android streaming + push | 同 iOS |
| 4.6 | Web 自我演化 dashboard | 路由 `/proposals` 工作 |
| 4.7 | Web drift_monitor 时间序列图表 | 路由 `/drift` 工作 |
| 4.8 | 跨端 deeplink | 手机点 Slack 通知 → 跳对应 P-id |

### Gate

从冷启动 iPhone → 装 TestFlight → 登录 → 看到运行历史 → 启动新研究 →
看到流式输出 → 跑完收到 push → 全程**不需要 desktop 配合**。

---

## Phase 5 · Ecosystem（持续推进，每周 1 项）

**真实数据需要？** 看具体任务

不阻塞 v1 上线，但作为持续投入。优先序：

| # | Task | 价值 | 工时 |
|---|---|---|---|
| 5.1 | Memory long-term: embedding + pgvector | 跨 session 学习的基础 | 5d |
| 5.2 | Multi-model parallel compare (#94) | 实证哪些模型更适合哪些 skill | 1d |
| 5.3 | LLM 自动路由（基于历史 cost/quality 选 model） | 平均降本 30%+ | 3d |
| 5.4 | Team workspaces | 当有 multi-org 用户时再做 | 3d |
| 5.5 | RBAC | 5.4 之后 | 3d |
| 5.6 | Post-processor hook chain 正式化 | 等第二个 use case | 1d |
| 5.7 | Skill SDK（用户上传 SKILL.md + 沙盒）| 增长策略，看用户量 | 5d+ |

---

## 三、时间表（指示性）

```
Week 1-3   Phase 1 — Self-evolution loop          (已经开始)
Week 4-6   Phase 2 — Real tools (数据决策 by W4)  ⚠ 数据接入
Week 7-8   Phase 3 — Operational
Week 9-12  Phase 4 — Mobile + frontend
Week 13+   Phase 5 — Ecosystem (持续)
```

**首个外部 beta 用户上线 = Week 8 末**。

---

## 四、关键决策点 / 风险登记

### 必须及时拍板的决策

| 决策 | 截止时间 | 默认 | 影响 |
|---|---|---|---|
| Q1-Q4 数据源（US-only） | Phase 2 开始前（Week 4）| yfinance + FMP basic + Tavily + 自建 web_extract → ~$44/月 | 月成本 + 数据新鲜度 |
| Mobile 优先 iOS or Android | Phase 4 开始前（Week 9）| iOS | 仅一个端先做 |
| Phase 5 哪一项优先 | Phase 5 开始前 | 5.1 (memory) | 长期方向 |

### 风险登记

| 风险 | 触发概率 | 缓解 |
|---|---|---|
| Phase 1 自我演化 critique 质量不足 | 中 | 已有 design/proposals-archive/2026-05-26-001 作为基线参考 |
| Phase 2 数据源 API 改版 / 反爬 | 中 | 多源备份 + caching + 失败 graceful fallback 到 mock |
| LLM cost 失控 | 中-高 | Phase 3 的 per-user cap + Phase 5.3 自动路由 |
| Mobile 体验差 / 流式不稳 | 低-中 | Phase 4 提前 spike + Phase 3 ops 准备 |
| 团队带宽不足，phase 拖期 | 中 | 每个 phase 独立，可暂停后续，不影响已上线部分 |

---

## 五、生命周期 & 维护

这份 spec 是 **live document**，每个 phase 完成时更新：

1. **每 phase 完成时**：把对应章节标为 `Status: ✓ shipped` 并附上 commit hash / proposal-id
2. **每周更新**："已经开始" / "已完成" 标记往下推
3. **当某个 task 发现需要更大改动**：单独开 openspec/changes/<NNN>，spec 这里只标 deferred + 链接
4. **真要 v1 上线时**：spec 转为只读，下一版本（v1.1）开新 spec

---

## 六、跟现有文档的关系

- `design/00-agent-platform.md` — 现状盘点（截图，本文是 forward-looking 计划）
- `design/02-self-evolution-loop.md` — Phase 1 的具体技术设计（本文是规划层）
- `design/proposals-archive/2026-05-26-001-research-scratchpad/` — Phase 1 demo 的活样本（手工版本）
- `openspec/changes/<NNN>/` — 每个 phase 真要落地时拆出来的具体 change proposals
- `CLAUDE.md` — 操作员级别的工作流（本文 phase 完成时它需要同步更新）
