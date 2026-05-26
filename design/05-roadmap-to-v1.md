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
| 1.1 | `data/evolution/proposals/<id>/` 目录 + meta.json 状态机 | `cat meta.json` 显示 `status: triggered` |
| 1.2 | Trigger 入口 `POST /api/admin/review/<run_id>` | curl 调用返回 P-id，目录被创建 |
| 1.3 | Spawn CC 子进程 + 收 critique.md + patches | 一个真实 P-2026-* 目录出现 cc_run/ 完整产物 |
| 1.4 | Validate diff 能否 apply + rubric YAML 有效 | `validation.json` 写入 `{ok: true, reasons: []}` |
| 1.5 | G1 CLI review UI（demo 见上） | `./scripts/proposals review` 列出 pending |
| 1.6 | Apply pipeline（git diff apply + reload + EvolutionStore record） | `proposals adopt P-xxx` → EvolutionStore.list("research") 显示新 version |
| 1.7 | A/B eval 自动跑（EvalRunner pre/post） | `decisions/006-ab_eval_done.json` 有 baseline + proposed pass_rate |
| 1.8 | G2 决策 + Rollback | `proposals rollback P-xxx` → 前一版本恢复 |
| 1.9 | Run.status 重塑 | API 返回新字段：`harness_status`, `evaluator_decision`, `overall_assessment` |
| 1.10 | Quality definition 统一 schema | sprint-contract + judges 引用同一份 criteria.json |
| 1.11 | drift_monitor 自动 trigger | 故意写一个 pass_rate=0.4 的 run → 6 小时后 proposal 自动生成 |
| 1.12 | 跨 skill smoke：3 个不同 skill 走完整闭环 | proposals-archive 下出现 3 份真实自动 proposal |

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

**真实数据需要？** ✅ 这就是数据集成阶段。

### 标靶 demo

跑完 Phase 2，**研究的产出长这样**（不是 mock 数据，是真实数据驱动）：

```markdown
# 中国半导体设备板块 — 精简研究框架

## 一、市场规模与增长（2023-2025）

中国半导体设备 2024 年市场规模 **¥1,847 亿** [^1]，YoY +27%，国产化率
**24.3%**（2024 Q4）[^2]。SEMI 预测 2025 年全球设备市场 $123.5B [^3]，
中国占比稳定在 30-32% 区间。

## 二、主要本土玩家

| 公司 | 代码 | 2024 营收 | YoY | PE-TTM | 数据日期 |
|------|------|----------|-----|--------|---------|
| 北方华创 | 002371.SZ | ¥221.79亿 [^4] | +33.7% | 41.2x [^4] | 2025-03-31 |
| 中微公司 | 688012.SH | ¥62.7亿 [^4]  | +27.8% | 78.5x [^4] | 2025-03-31 |
| ...

## 数据来源

[^1]: tushare:industry_revenue, query='半导体设备', period='2024', fetched 2026-05-27
[^2]: 国家工信部, 2024 Q4 半导体设备国产化率报告 (web_extract:moe.gov.cn/...)
[^3]: SEMI, 2025 World Fab Forecast (web_extract:semi.org/...)
[^4]: tushare:financials, ticker='002371.SZ', as_of='2025-03-31'
```

**对比 Phase 1 阶段的 mock 数据**：

| 项目 | Phase 1 (mock) | Phase 2 (real) |
|---|---|---|
| 北方华创 PE | 59.5x（固定字符串）| 41.2x（tushare 实时） |
| 市场规模 | "[UNSOURCED] 亿元" | "¥1,847 亿" 带源 |
| 数据日期 | 永远是 "2025" 字符串 | 真实 fetched_at timestamp |
| 引用 | "tool:market_quote" 无来源 | 具体 query + as_of |
| **CC critique 能 review 的内容** | 仅格式 | 数据准确性 + 推理合理性 |

### 🚨 必须先决定的 5 个数据问题

| Q | 决策 | 默认建议 |
|---|---|---|
| Q1 | A 股 / 港股数据：tushare pro 标准版（¥2000/年）还是 akshare（免费但不稳）？ | **tushare pro** |
| Q2 | 全球行情：yfinance（免费）够吗？ | **够**，需代理 |
| Q3 | 中文财经新闻：自建抓 wallstreetcn / 财联社 还是采购？ | **自建抓** |
| Q4 | 月度数据预算上限 | **$50/月**（Tavily $30 + 其余年付摊销）|
| Q5 | 美股深度（SEC 全文 + 10 年历史）必要？ | **暂不**，v1 中国为主 |

按默认选项：**总成本 ~$50/月 + ¥2000 年付**。

### 任务列表

| # | Task | 验收点 |
|---|---|---|
| 2.1 | 数据源决策（Q1-Q5）+ 测试账号 | tushare API 能拉到 002371.SZ |
| 2.2 | `market_quote` 接 tushare + yfinance | 真实股价返回 |
| 2.3 | `kline` 接同上 + 缓存（日线 24h，分钟线 5min） | curl 拉到当日真实 K 线 |
| 2.4 | `financials` 接 tushare（详尽）+ yfinance（简版） | 北方华创 2024 营收 = ¥221.79亿 |
| 2.5 | `news_search` 接 newsapi + 自建中文抓取 | 拉到 2026 年关于半导体的真实新闻 |
| 2.6 | `report_analysis` 接巨潮 + SEC EDGAR + pypdf 解析 | 能抓 002371.SZ 2024 年报全文 |
| 2.7 | `web_search` 接 Tavily | 真实搜索结果 + 摘要 |
| 2.8 | `web_extract` 用 httpx + readability-lxml | URL → clean markdown |
| 2.9 | Tool result trust signals | `ToolResult` 新增 `{provenance, fetched_at, freshness, confidence}` |
| 2.10 | Per-user 配额追踪 + 月度费用累积 | `/api/users/me/usage` 返回当月 cost + per-tool 调用数 |
| 2.11 | 真实数据 + Phase 1 跑全闭环 | 3 个真实数据 case 自动 evolved → 看到 critique 提及"数据陈旧"等真实问题 |

### Gate

**Demo 输出标准**：跑 research_pipeline("半导体设备板块研究框架") →
final-research.md 包含至少 5 个真实数字 + 5 个 `[^N]` 形式的源引用 +
每个引用能 click 追溯到具体工具调用 + judge score correctness ≥ 8 +
**Phase 1 的 self-evolution loop 现在 review 的是数据质量，不是格式**。

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
| Q1-Q5 数据源 | Phase 2 开始前（Week 4）| 默认见 Phase 2 | 月成本 + 数据质量 |
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
