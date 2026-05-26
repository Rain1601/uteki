# 06 · Agent Flow Demo — 完整流程 + 关键节点说明

> 这份文档是 uteki agent 的**端到端运行图谱**——从用户问一句话到结
> 果落盘、到 self-evolution 闭环触发的所有节点都在这里，每个节点配
> "做什么 + 为什么这样设计而不是那样"。
>
> 看完这篇，你应该能在白板上把 uteki 的运行流画出来，并能回答任意
> 一个节点"为什么 X 而不是 Y"的问题。

## 一、Demo 场景设定（US-only）

用户 Alice（已注册，JWT 已签发）在 Web 端发起一次研究：

> **"Give me a research framework on AI infrastructure semiconductors
> (focus: NVDA, AMD, AVGO, TSM). Cover market size, competitive
> positioning, valuation, catalysts, risks. 500-800 words."**

预期产物：**`final-research.md` 含 NVDA/AMD/AVGO/TSM 的真实 PE、营收、
近期催化事件，每个数字都附 `[^N]` 形式可追溯的工具来源**。

---

## 二、Part A · 单次 Run 的 13 个节点（Happy Path）

```
                        Alice 浏览器                          Operator (Slack)
                            │                                       ▲
                       (1) POST /api/agent/start                     │
                            │       (Bearer JWT)                     │
                            ▼                                        │
                  ┌─────────────────────┐                            │
                  │  FastAPI route      │                            │
                  │  (2) auth gate      │ ← Depends(current_user)   │
                  │  (3) build harness  │ ← skill.recommended_limits│
                  └──────────┬──────────┘                            │
                             │                                        │
                             ▼                                        │
                  ┌─────────────────────┐                            │
                  │   AgentHarness      │ (4) first event yielded   │
                  │   (background task) │     → run_id back to Alice│
                  └──────────┬──────────┘                            │
                             │                                        │
                  (5) skill.run(messages)                              │
                             │                                        │
                             ▼                                        │
              ┌─────────────────────────────┐                        │
              │  ResearchPipeline           │                        │
              │  ┌───────────────────────┐  │                        │
              │  │ (6) Planner sub-skill │──→ plan.md, contract.json │
              │  └─────────┬─────────────┘  │                        │
              │            ▼                │                        │
              │  ┌───────────────────────┐  │                        │
              │  │ (7) Research sub      │  │ (8) tool calls         │
              │  │     skill + LLM       │──→ market_quote(NVDA),... │
              │  │     tool-use loop     │  │     ↑ harness        │
              │  └─────────┬─────────────┘  │     intercepts        │
              │            ▼                │                        │
              │     final-research.md       │                        │
              │     (9) strip preamble      │                        │
              │            │                │                        │
              │            ▼                │                        │
              │  ┌───────────────────────┐  │                        │
              │  │ (10) Evaluator skill  │  │                        │
              │  │  - verifiers          │──→ judge-correctness.json │
              │  │  - LLM judges         │──→ judge-cite.json        │
              │  │  - decision           │──→ eval-report.json       │
              │  └─────────┬─────────────┘  │                        │
              │            │                │                        │
              │   decision=approve? ───────┘                         │
              │   yes → done                                          │
              │   revise → loop back to (7) with suggestions          │
              └──────────────┬─────────────┘                          │
                             │                                        │
                             ▼                                        │
                  ┌─────────────────────┐                            │
                  │ harness final ops:  │                            │
                  │ (11) usage rollup   │                            │
                  │ (12) run_store.    │                            │
                  │      finish (SQLite)│                            │
                  └──────────┬──────────┘                            │
                             │                                        │
                  (13) done event yielded ─→ Alice 看到 SSE/polling 结果
                             │                                        │
                             ▼                                        │
                       artifacts on disk                              │
                       + Run row in SQLite                            │
                                                                     │
                  ── 后台异步 ──                                       │
                                                                     │
                  drift_monitor (cron, every 6h)                      │
                  统计最近 24h pass_rate                                │
                  如果 < 0.7 阈值                                       │
                              ────── Slack alert ──────────────────→ │
```

### Node-by-node 说明

#### (1) `POST /api/agent/start` · 用户入口

- **做什么**：Web 客户端发请求 `{messages, agent="research_pipeline", session_id}`
- **关键设计**：分了 `/chat` (SSE 同步流) 和 `/start` (fire-and-forget) 两个端点。MCP server / 长流程客户端走 `/start` 拿 run_id 然后 poll；浏览器流式 UI 走 `/chat`
- **不是这样**：~~一个统一的 SSE 端点然后客户端自己决定听不听完~~。原因：超时 / 客户端代码复杂度差太多

#### (2) Auth gate · `Depends(current_user)`

- **做什么**：从 `Authorization: Bearer <JWT>` 解出 user_id → 加载 User row → 验 status=active
- **关键设计**：**Auth 在路由层，不在 harness 层**。Harness 拿到 user_id 时已经是验证过的；harness 不需要知道任何 JWT/cookie 概念
- **不是这样**：~~让 harness 自己验 token~~。原因：auth 复杂度（OAuth, refresh rotation, family burn）应该完全隔离于 agent 逻辑

#### (3) Build harness · `_build_harness(agent, model, session_id, user_id)`

- **做什么**：从 `default_skills` 拿 skill 实例 → 读 `skill.recommended_limits()` → 构造 `AgentHarness(skill, limits, user_id, ...)`
- **关键设计**：**每个 request 一个 harness 实例**，不复用。每个 harness 持有自己的 user_id 绑定 + 自己的 budget counter
- **不是这样**：~~singleton harness 跨 request 共享~~。原因：budget 累积、user 隔离会一塌糊涂
- **关键设计**：`recommended_limits()` 是 skill 自己声明，让 ResearchPipeline 这种需要更宽预算的 skill 不用硬编码到 harness 里
- **不是这样**：~~所有 skill 用同一个 default limits~~。原因：pipeline 系列必然超 max_tool_calls=30，default 在它们上面就是 broken

#### (4) First event · run_start yielded

- **做什么**：harness 在 `run()` 第一个 yield 给出 `run_start` event（包含分配的 run_id）。`/start` 端点抓这个 event 然后 background task 接管后续
- **关键设计**：**run_id 在 yield 之前已经被分配并写入 run_store**——所以后续 polling 立即能读到这个 run（虽然 status=running、events=[]）
- **不是这样**：~~run_id 等 finish 时才分配~~。原因：MCP 客户端需要立即拿到 run_id 去 poll

#### (5) `skill.run(messages)` · 进入 skill 域

- **做什么**：harness 调用 `skill.run(messages)` 开始 async generator 迭代
- **关键设计**：**skill 是纯生成器，不做副作用**。它 yield AgentEvent，harness 解释这些 event 并执行
- **不是这样**：~~skill 直接调 tool / 写 file / 触发 LLM~~。原因：测试性、可观察性、budget 控制——所有这些都依赖 harness 在中间做拦截

#### (6) Planner sub-skill · 拆需求

- **做什么**：ResearchPipeline 第一步调 `_delegate("planner", messages, run_events)`。Planner 是个**纯结构化 LLM 调用**——读 user intent，输出 `plan.md` (markdown) + `sprint-contract.json` (criteria 机器格式)
- **关键设计**：**Planner 不调任何研究工具**，它只做"展开"。这强制了"先想清楚再动手"的分工
- **不是这样**：~~让 Research skill 自己拆需求自己研究~~。原因：失去 Planner→Generator→Evaluator 的独立分工，evaluator 没法对照 contract 评分
- **artifact 关键**：`sprint-contract.json` 是后续 Evaluator 的"考纲"，这是文件作为 agent 间通讯的核心实例
- **后果**：US-only 时，Planner SKILL.md 里的 C1 模板从 `\d{6}\.(SH|SZ)` 改为 `\b[A-Z]{1,5}\b`（NYSE/NASDAQ ticker），但这条 regex 又要小心英文词假阳性——见 design/02 P-2026-001 的教训

#### (7) Research sub-skill + LLM tool-use loop · 真正的研究阶段

- **做什么**：拿到 plan.md + sprint-contract.json 后，Research skill 用 LLM stream_chat_with_tools 跑工具使用循环
- **关键设计**：LLM 看到一份注入了 sprint-contract 的 system prompt——它知道 "C1 要求至少 3 个 ticker 出现"、"C4 要求每个数字有源"——然后**自己决定调哪些 tool**
- **关键设计**：harness 注入了 `_tool_executor` callback；LLM 想调 tool 时，stream_chat_with_tools 实际执行调用并把结果喂回 LLM。**Skill 不写 dispatch 代码**
- **不是这样**：~~hard-code 每个 skill 调哪些 tool~~。原因：失去 LLM 的判断价值；用户问 NVDA 时不该硬塞 financials(AAPL)
- **预算守护**：harness 在每个 tool_call / usage event 上累积，超过 `recommended_limits` 即终止——pipeline iteration 失控时安全网

#### (8) Tool calls · market_quote / financials / news_search / ...

- **做什么**：LLM 决定 `market_quote(NVDA)` → harness 拿到 tool_call event → `default_registry.get("market_quote").run(symbol="NVDA")` → 真实 API 调用（yfinance/Polygon/SEC）→ ToolResult 回喂
- **关键设计**：**Tool 是平面的 Python 类**，subclass `Tool`，实现 `run(**kwargs) -> ToolResult`。 LLM 看到的是 OpenAI 或 Anthropic spec 自动生成的 JSON schema
- **关键设计**：**Tool result 携带 trust signal**（Phase 2 要做）：`provenance` (yfinance vs polygon)、`fetched_at` (timestamp)、`freshness` (real-time vs cached 15min) 让 Evaluator 能区分"实时数据"和"6 小时前的"
- **不是这样**：~~所有 tool 返回扁平 dict 让 LLM 自己理解~~。原因：缺 metadata 时 LLM 没法说"这个数据是 15 分钟前的"

#### (9) Strip preamble · seam intervention

- **做什么**：`LocalFileArtifactStore.write()` 写 markdown 时自动 strip 第一个 `# ` 之前的内容
- **关键设计**：**deterministic 修正，不依赖 LLM 自律**。design/02 P-2026-001 的 4 个迭代证明了 pure prompt 改不动这种"compliance theater"
- **不是这样**：~~只在 prompt 里说"不要写元思考"~~。我们试了 3 轮强化，没用
- **不是这样**：~~让 skill 自己事后清理~~。原因：skill 的 LLM 不会回头修自己的 output

#### (10) Evaluator skill · 独立评估

- **做什么**：Pipeline 调 `_delegate("evaluator", ...)`。Evaluator 读 `sprint-contract.json` + `final-research.md` + `run-trace.json`，对每个 acceptance_criteria 跑 verifier：
  - `regex_in_text` (本地正则)
  - `tool_call_in_run` (扫 events)
  - `llm_judge_score` (调 LLM judge，使用 different model 比如 aihubmix/claude-sonnet-4-5)
- **关键设计**："**Evaluator 不评自己**"——它用一个跟 Generator 不同的 LLM（不同 provider + 不同 prompt 上下文）。今天我们用 deepseek 做 Research，aihubmix 做 judge
- **不是这样**：~~让同一个 model 既生成又评分~~。原因：训练分布重叠，自己看不到自己的 blind spot——design/02 P-2026-001 finding #4 是这个 anti-pattern 的真实证据

#### (10-loop) Pipeline 迭代 · revise → 重跑

- **做什么**：如果 Evaluator decision = "revise"，pipeline 把 suggestions append 到 messages，回到 (7)。最多 `contract.max_iterations` 轮
- **关键设计**：**suggestions 是文本形式 append 给 LLM**，不是结构化命令。让 LLM 用自然语言理解"上次哪里错了，这次怎么改"
- **不是这样**：~~让 evaluator 直接改 final-research.md~~。原因：evaluator 没法生成研究内容；它的角色是判官，不是作家

#### (11) Usage rollup · 累积 token / cost

- **做什么**：harness 在每个 `usage` event 累加 input/output/cache_read/cache_creation tokens；finish 时按 model 价目表计算 cost_usd
- **关键设计**：**预算检查实时跑**，每个 usage event 都检查 `max_input_tokens / max_output_tokens / max_cost_usd`。超限即触发 error event，run 终止
- **关键设计**：成本是 run 维度，按 user_id 汇总在 Phase 3 加（per-user cap）

#### (12) `run_store.finish` · 持久化

- **做什么**：SqliteRunStore 把整个 Run（包括 events JSON、tags、usage_summary）写入 `run` 表的一行
- **关键设计**：**events 在内存缓冲，finish 时一次性 flush**。原因：5000 events 各 INSERT 是 IO 灾难
- **代价**：mid-flight 跨进程看不到事件细节（只看到 `status=running, events=[]`）。MCP server polling 只关心 status 转换，可接受

#### (13) `done` event · 收尾

- **做什么**：yield 最终 `done` event，包含 steps + tools 计数。客户端的 SSE 流到此结束
- **关键设计**：done 后 harness 还会跑 `run_store.finish` 等 post-processing，但 **done event 不等待这些**。客户端看到 done 即可显示"完成"
- **不是这样**：~~等所有持久化完成才发 done~~。原因：finish 是 IO 慢操作，UI 体验差

---

## 三、Part B · Self-Evolution Loop 触发的 7 个节点

```
                    drift_monitor (cron 每 6h)
                            │
                  统计 skill='research' 最近 24h pass_rate
                            │
                  pass_rate 跌 >10pp ?
                            │   no → 静默
                            │   yes ↓
                  ┌─────────────────────────────┐
                  │ (E1) Trigger proposal       │
                  │     POST /api/admin/         │
                  │     review/<run_id>          │
                  └─────────────┬───────────────┘
                                │
                  ┌─────────────────────────────┐
                  │ (E2) Snapshot 当前世界       │
                  │  - run artifacts            │
                  │  - SKILL.md (hash 锁版本)   │
                  │  - 当前 spec.md             │
                  │  - 当前 judge rubrics        │
                  └─────────────┬───────────────┘
                                │
                  ┌─────────────────────────────┐
                  │ (E3) Spawn CC subprocess    │
                  │  brief = "review run X"     │
                  │  workdir = snapshot/        │
                  │  allowedTools =             │
                  │    Read,Grep,Edit,Write     │
                  │  (no Bash, no Agent,        │
                  │   no Web)                   │
                  └─────────────┬───────────────┘
                                │
                  CC 自主分析（读 artifacts +
                  对照 SKILL.md + specs）
                                │
                  ┌─────────────────────────────┐
                  │ (E4) CC 产出三件事            │
                  │  - critique.md (5+ findings) │
                  │  - patch.diff (SKILL.md)    │
                  │  - rubric.diff (optional)   │
                  └─────────────┬───────────────┘
                                │
                  ┌─────────────────────────────┐
                  │ (E5) Validate              │
                  │  - diff 能 apply?          │
                  │  - rubric YAML valid?      │
                  │  - critique 引用了具体行号? │
                  └─────────────┬───────────────┘
                                │
                  status → pending_review                           ┌─────────┐
                                │                                  │ G1: 操作员│
                                ├──── notify Slack ───────────────→│ 评审      │
                                │                                  └────┬────┘
                                ▼                                       │
                  ┌─────────────────────────────┐                       │
                  │ (E6) Apply patch            │←──── accept ─────────┘
                  │  - git apply diff           │
                  │  - load_skill_prompt.       │
                  │      cache_clear()          │
                  │  - EvolutionStore.record    │
                  │    (new version auto-       │
                  │     hashed)                 │
                  └─────────────┬───────────────┘
                                │
                  ┌─────────────────────────────┐
                  │ (E7) A/B eval                │
                  │  - EvalRunner.run_all        │
                  │    on canonical cases       │
                  │  - 同时跑 baseline (rollback) │
                  │    + proposed               │
                  │  - 计算 pass_rate Δ          │
                  └─────────────┬───────────────┘                       │
                                │                                       │
                                ├──── A/B 结果 + Slack ───────────────→ │
                                ▼                                       ▼
                                                                  ┌─────────┐
                                                                  │ G2: 操作员│
                                                                  │ 决定      │
                                                                  └────┬────┘
                                                                       │
                                            ┌──── adopt ────┬──── rollback
                                            │                │
                                            ▼                ▼
                                  status=adopted        reverse patch
                                                        EvolutionStore
                                                        records reverse
```

### Self-evolution node 说明

#### (E1) Trigger · drift_monitor 发现质量下降

- **做什么**：cron 每 6h 跑 `drift_monitor.check_drift()`，比较"今天 vs 7 天前"的 pass_rate。差 >10pp 即 trigger
- **关键设计**：**Drift 是 lagging signal**——必须有真实 runs 跑下来才能算 pass_rate。所以 drift 系统只在用户实际有日常 traffic 后起作用
- **关键设计**：**Rate limit**——每个 skill 7 天内最多 1 个 in-flight proposal。防止系统抖动导致 proposal 自循环

#### (E2) Snapshot · 冻结当前世界

- **做什么**：把当前 SKILL.md, spec.md, judge rubrics 全部拷贝到 `data/evolution/proposals/<P-id>/snapshot/`
- **关键设计**：**Snapshot 用 hash 锁版本**。如果 review 期间有人改了 SKILL.md，proposal 仍基于 snapshot 时刻的版本——避免 G1 评审中途底盘换了的灾难

#### (E3) Spawn CC subprocess · 隔离 + 权限限制

- **做什么**：`claude -p "<brief>"` 子进程，working dir = snapshot/
- **关键设计**：**沙盒**——`--allowedTools Read,Grep,Edit,Write`，**禁用** Bash + WebFetch + Agent。防止 CC 不小心 push 到 prod 仓库 / 调外部 API / 递归 spawn
- **不是这样**：~~CC 跑在 main worktree~~。原因：CC 直接 edit live SKILL.md = 跳过 G1 评审

#### (E4) CC 产出 critique + patches

- **做什么**：CC 读 snapshot，写 critique.md (≥3 specific findings)、patch.diff (≤20 行 SKILL.md 改动)、rubric.diff (可选)
- **关键设计**：**Critique 必须 cite 具体行号或 artifact 片段**——这是 prompt 里硬约束，避免空泛批评
- **关键设计**：**Patch 大小有上限**——防止 CC 借机重写整个 SKILL.md。每次只动一小块，operator 评审可承担

#### (E5) Validation · 机器先验

- **做什么**：run `git apply --check patch.diff`、`yaml.safe_load(rubric)`、grep critique 是否包含 `line \d+` / `file_path:line` 引用
- **关键设计**：**validation 是 hard gate**——失败的 proposal 自动进 `invalidated` 状态，但 NOT discarded。**这本身是数据**——CC 频繁产出 broken diff 说明 model 不够 / brief 不够好
- **后果**：观察 invalidated 比例，若 >20%，重新 evaluate brief.md 模板

#### (E6) Apply patch · 真改 SKILL.md

- **做什么**：`git apply` patch → `load_skill_prompt.cache_clear()` → EvolutionStore 自动 record new version（hash 变了）
- **关键设计**：**应用是文件系统级别**，不走 DB 操作。因为 SKILL.md 是 git 跟踪的，git 提供天然 audit trail
- **关键设计**：**EvolutionStore.record 是被动的**——只要 prompt hash 变了，下次 `current_signature()` 一调就自动 bump

#### (E7) A/B eval · 量化验证

- **做什么**：EvalRunner 跑 canonical cases 两次——baseline（patch 之前的 SKILL.md 版本）+ proposed。对比 pass_rate
- **关键设计**：**12 cases × 3 runs 取均值**——单 case 单跑 N=1，confidence 太低。Phase 1 MVP 阶段先 4 cases × 1 run 作为 "preview"，G2 决定时建议跑大样本
- **关键设计**：**A/B 跑全套 cases**，不只是触发 drift 的那一条。原因：改 prompt 可能改善 case A 但破坏 case B（cross-skill 影响）

---

## 四、Part C · 4 个跨节点不变量

这 4 件事在**每一个节点**都成立，是 agent 架构的"宪法"：

### I1. 多租户隔离

- 每个 Run/Artifact/EvalRecord 都带 user_id
- 每个 store.get/list/read 都以 user_id 过滤
- 跨用户访问 → 404（与"不存在"同形）
- demo 视角：Alice 跑 NVDA 研究产生的 artifact，Bob 怎么试都看不到。**即使 Bob 知道 run_id**

### I2. Budget enforcement

- 每个 run 都 bounded by HarnessLimits：6 项硬上限
- usage event 实时累加，超限即 terminate (error event + status=error)
- pipeline 通过 `recommended_limits` 扩大但仍硬上限
- demo 视角：Alice 触发一个失控的 run，最多烧到 `max_cost_usd = $1` 即停

### I3. Audit trail

- **代码改动**：git log
- **Prompt 改动**：git log (SKILL.md) + EvolutionStore 自动 record (hash bump)
- **Run 改动**：SqliteRunStore Row + events JSON
- **Proposal 改动**：`data/evolution/proposals/<id>/decisions/` ndjson 状态转移日志
- **用户决策（G1/G2）**：`decisions/*.json` 写明 user_id + ts + reason
- demo 视角：任何一次 prompt 调整都能从"为什么改"（critique.md）追溯到"谁批的"（G1 decision）到"改完什么效果"（A/B json）

### I4. Cost accounting

- 每个 Run 写 `usage_summary.cost_usd`
- 用户级累积：`/api/users/me/usage`（Phase 3 加）
- 平台级累积：drift_monitor 数据库 + Sentry breadcrumb
- demo 视角：月底能告诉 Alice "你用了 $13.50，主要花在 research_pipeline 上"

---

## 五、Part D · 几个最关键的设计决策（精选）

### D1. 为什么 skill 是纯 generator，副作用全在 harness

**答**：测试性 + 可观察性 + budget control 都依赖 harness 拦截。
**反例**：如果 skill 自己调 tool，那 (a) mock test 要 mock 整个 skill，(b) harness 没法做 budget check，(c) `_already_executed` 这种细节得每个 skill 自己处理。

### D2. 为什么 Planner 不调研究工具，只产 contract

**答**：分工 + 评估对照。Planner 产出的 contract 是 Evaluator 的"考纲"——同一份文件，两个 skill 读，构成评估的客观参照。
**反例**：Research skill 自己又拆需求又研究，evaluator 没东西对照，只能用 LLM 主观打分。

### D3. 为什么用文件做 agent 间通讯，不用内存

**答**：跨 session / 离线 inspect / 跨语言客户端 / 单元可测——四条全是 file-based 才有的好处。
**反例**：events 历史可以传 pipeline state，但 mobile 客户端读不到 events，只能读文件。

### D4. 为什么 Evaluator 用不同 model

**答**：evaluator-doesn't-judge-itself 原则（Anthropic harness 8 原则之 4）。同一个 model 既写又评，训练分布重叠，盲点是结构性的。
**实例**：design/02 P-2026-001 finding #4——同一个 deepseek 既写 scratchpad 又评分时给 9/10，换 aihubmix claude 评同一份给 3/10。

### D5. 为什么有 strip_preamble 这种 seam intervention，不靠 prompt

**答**：3 轮 prompt 强化试过了——pure prompt 改不动 model 的"compliance theater"（嘴上说遵守，行为不遵守）。
**论据**：design/02 P-2026-001 的完整 4 轮迭代 + 7 个 real-LLM run。

### D6. 为什么 MCP server 是 HTTP adapter，不直接 import uteki

**答**：HTTP API 是 SSOT，所有客户端平等。MCP server 不需要懂 SQLite/auth/store partition——它只是发 HTTP request。
**反例**：如果 MCP 直接 import，那 (a) MCP 进程需要 DB 连接，(b) auth 边界混乱，(c) SQLite 持久化是 MCP 的硬阻塞。见 design/03。

### D7. 为什么 self-evolution 强制 G1 + G2 两道人工

**答**：G1 看的是"critique 是否合理 + diff 是否安全"；G2 看的是"A/B 数据是否说服了我"。这两个判断是**不同的人格**——G1 接近 reviewer，G2 接近 PM。
**反例**：自动 apply 通过的 critique → 系统在自己审自己。design/02 §"为什么这个 loop 值得做"明确说了这是 meta 风险。

### D8. 为什么 budget 是 skill 维度，不是 user 维度

**答**：HarnessLimits 是 per-run 硬上限，防止单 run 失控。Per-user cap 是软上限，Phase 3 加。两者目的不同——前者是 safety，后者是 cost ops。

---

## 六、跟现有文档的关系

- **`design/00`** — 当前架构现状（截图）
- **`design/02`** — Phase 1 Self-evolution loop 的技术深度设计
- **`design/05`** — 5 phase roadmap（这份文档是 05 的运行视图）
- **`design/proposals-archive/2026-05-26-001-research-scratchpad/`** — Self-evolution loop 第一次手工跑过的真实样本（本文档 Part B 的活样本）
- **`openspec/specs/harness/spec.md`** — Harness 契约的形式化
- **本文（06）** — 端到端运行图谱 + 节点级设计依据

## 七、读完之后能回答的问题

1. **Alice 发起一次研究到她看到结果，中间经过多少层 + 都做什么** — 13 节点
2. **为什么这个 skill 这次没调 financials 工具** — Node (7) (8)
3. **uteki 是怎么判断一份输出"合格"的** — Node (10) + Part D2 + D4
4. **prompt 改了一行，什么会跟着变** — `load_skill_prompt.cache_clear` + EvolutionStore auto-bump
5. **如果一个 skill 跑炸了，谁兜底** — Node (3) + I2
6. **怎么知道一份研究的数据是不是真的** — Node (8) tool result trust signal + Part D3
7. **半夜系统自己改了 prompt，怎么追责** — I3 audit trail
8. **如果 Bob 想看 Alice 的研究结果，会发生什么** — I1
