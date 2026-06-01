# 11 · 从 uteki.open 迁移到 uteki — 分阶段计划

> 创建于 2026-06-01。承接 [design/07-legacy-port-plan.md](./07-legacy-port-plan.md)
> 的 inventory，把它转成可执行的迁移序列。
>
> 原则：**不照搬硬套，基于 uteki 的架构迁移**。
> - uteki.open = FastAPI 多 domain + Postgres/Redis/ClickHouse + SQLAlchemy + 多个 page-per-feature。
> - uteki = 单进程 + SQLite/SQLModel + harness 契约（skill = 意图流，harness = 副作用）
>   + 多租户从 day 1 + mock-LLM hermetic E2E + self-evolution loop（M1.1-M1.12）。
>
> 迁移意味着**把 uteki.open 的"业务价值"用 uteki 的架构重新实现**，而不是把
> 它的代码原封不动拷过来。

## 一、什么值得迁移（按价值排序）

| # | 来源 | 价值 | 迁移方式 |
|---|---|---|---|
| 1 | **公司分析 6 gate persona prompt**（skills.py） | 直接决定分析质量 | port 到 `skills/company/_GATE_INSTRUCTIONS`，剥离 `<tool_call>` 文本协议 |
| 2 | **Gate 7 结构化 JSON 输出** | 解锁前端已有的 fisher_qa/philosophy/radar 字段 | port schema 到 synthesis prompt，artifact 保存为 `final-verdict.json` |
| 3 | **CompanyAgentDossier 编辑式渲染**（1320 行） | 真正"杂志感"的研究输出 | port 视觉手法到 view.tsx：stamped verdict polish + source-type 颜色编码 + score bars + 大师评语框 |
| 4 | **Gate 3/5 反思 prompt**（REFLECTION_PROMPT_*） | 跨 gate 矛盾检测，质量校验 | 作为 pipeline 中间步骤，落 `reflection-N.json` artifact |
| 5 | **uteki = 一个 agent 的主路由**（用户提出） | 改变产品形态：单 chat 入口 vs N 个 workbench | 新 skill `uteki_router`：LLM tool-calling 把现有 sub-skill 包成 tool |
| 6 | **stronger financials.py**（720 行 vs 我们 ~200） | 财报数据深度 | port 关键计算逻辑（FCF、所有者收益等），保留 yfinance 优先 + FMP 兜底架构 |
| 7 | **Index Arena 3-phase pipeline**（Decide → Vote → Tally） | 多模型独立投票产出 ensemble 决策 | 新 pipeline meta-skill，复用 ResearchPipeline 的子代理模式 |
| 8 | **Evaluation 一致性测试** | 同输入 N 次跑测稳定性 | 已经在 design/08（uteki.open Claude 提议），暂缓到 M1.7+ 真用上 A/B 评估时再做 |
| 9 | **News 收集 scheduler** | 长期数据池 | APScheduler 接到 `triggers/registry.py`，按 cron 拉新闻 |
| 10 | **Macro / FOMC / SnB / Crypto 等其他 agent** | 拓展面 | 都重写成 uteki skill，每个独立 commit |

## 二、什么不迁移

| # | 来源 | 不迁的理由 |
|---|---|---|
| 1 | 13 个 domain 的目录结构 | uteki 单进程，按 capability 划分（skills/api/tools），不需要 DDD-style domain split |
| 2 | PostgreSQL + TimescaleDB + ClickHouse + Qdrant + MinIO | 当前 SQLite + 本地 fs 够用；上 prod 真有量再切 Postgres，向量库 / OLAP 等到 use case 明确 |
| 3 | `<tool_call>` / `<conclude>` 文本协议 | 我们的 harness 已经用 typed AgentEvent，更结构化 |
| 4 | SQLAlchemy domain split（models / schemas / service / repository） | SQLModel 单一 table model 已够；过度分层在小项目是负担 |
| 5 | MUI 6 | Next 16 + Tailwind 已是我们的栈，换框架 ROI 负 |
| 6 | 1660 行的 skill_runner.py | 它的角色被我们的 harness + skill 接管，不需要另起一个 runner 抽象 |
| 7 | `/admin` 页面运行时配 LLM key | 我们用 `.env` + `core/config.py`，简单到操作员级别 |

## 三、阶段计划

### Phase A · 公司分析质量补齐（**进行中**）

让 `company_research_pipeline` 这个 sub-skill 的输出立刻上一个台阶。

| | Task | 状态 |
|---|---|---|
| A.1 | 6 个 gate persona prompt 替换通用模板 | ⏳ 本次 commit |
| A.2 | Gate 7 结构化 JSON 输出（fisher_qa 15Q+score, radar_data, philosophy_scores 等） | 下次 |
| A.3 | Gate 3/5 反思 checkpoint | A.2 之后 |
| A.4 | CompanyAgentDossier 视觉手法 port 到 view.tsx | A.2 之后，FE 单独一刀 |

**Phase A gate**：跑一次真 LLM `company_research_pipeline` on NVDA，输出包含
具体 Fisher 15Q 评分 + philosophy_scores + radar_data，前端 view.tsx 能渲染。

### Phase B · uteki = 一个 agent（用户提出的方向）

把 "uteki 是平台" 改成 "uteki 是 agent"。

| | Task | 估时 |
|---|---|---|
| B.1 | 新 skill `uteki_router`：LLM tool-calling 把每个 sub-skill 包成一个 tool | 半天 |
| B.2 | 前端 `/` 改为单 chat 入口；现有 `/company-agent` 退为 power-user 直达入口 | 半天 |
| B.3 | router skill 系统 prompt：把 sub-skill 的能力描述 + 路由判断逻辑写好 | 调优 1 天 |
| B.4 | E2E 测试：用户问"NVDA 怎么看" → router 调 company_research_pipeline | 1 小时 |

**Phase B gate**：一个新用户访问 `/`，输入一句话，agent 自动选 skill 给答复。

### Phase C · 数据深度（依赖 Phase 2 工具接入）

| | Task | 估时 |
|---|---|---|
| C.1 | port uteki.open `financials.py` 的关键计算（FCF、owner earnings、ROIC 等） | 半天 |
| C.2 | 接 SEC EDGAR 真实 API（report_analysis 工具） | 1 天 |
| C.3 | Tavily 接入（news_search 升级，当前是 Google CSE + DDGS） | 半天 |
| C.4 | per-user 配额追踪（避免 LLM cost 失控） | 半天 |

这部分跟 design/05 Phase 2 重叠，可以合并。

### Phase D · 新 skill（按 ROI 排序，逐个进）

每个 skill = 一个独立 commit，互不阻塞。

1. **Index Arena**（3-phase voting）—— 多模型 ensemble decision 的代表性技术，1-2 天
2. **Macro agent** —— FOMC calendar + 宏观事件追踪
3. **News collection scheduler** —— APScheduler 接 `triggers/registry.py`
4. **Crypto agent** —— 优先级低（我们 v1 是 US-only 股票为主）
5. **SnB trading** —— 优先级低（trading 是 Phase 5 ecosystem）

### Phase E · Eval / Self-evolution 联动

uteki 已经有 self-evolution loop（M1.1-1.12）。uteki.open 的 evaluation 一致性
测试是另一种 eval 工具，等 Phase A-B 落地后接入做 A/B 自动评估的底座。

## 四、本次迭代落地（Phase A.1）

完成 Phase A 的第一刀：6 个 gate prompt port。

- 在 `services/api/src/uteki_api/skills/company/__init__.py` 加 `_GATE_INSTRUCTIONS`
  dict，含 6 个 gate 的详细 persona prompt（business_analysis / fisher_qa /
  moat_assessment / management_assessment / reverse_test / valuation）
- `_gate_prompt` 改为 dispatch：look up gate 名 → 拼接 persona + 共享 note
  + 运行时 context（source ledger + evidence + prior gates）
- 剥离 uteki.open 的 `<tool_call>` / `<conclude>` 文本协议（我们的 harness
  用结构化 AgentEvent，不需要这套）
- 保留 uteki.open 的 `_DATA_MISSING_INSTRUCTION` / `_NO_REPEAT_INSTRUCTION`
  作为共享 note

下一刀：Phase A.2 Gate 7 JSON 结构化输出。

## 五、跟 design/05 Roadmap 的关系

| design/05 phase | 本迁移计划对应 |
|---|---|
| Phase 1 自我演化（已完成） | 保持不变 — uteki 的核心差异化 |
| Phase 2 真工具接入 | = 本计划 Phase C |
| Phase 3 Operational | 跟迁移正交 |
| Phase 4 Mobile + Web 完善 | = 本计划 Phase A.4 + Phase B |
| Phase 5 Ecosystem | = 本计划 Phase D |

迁移**不替代** design/05，它是 design/05 Phase 2 + Phase 4 + Phase 5 的具体
内容来源（"做什么"），design/05 仍是"做的顺序 + 验收 + Gate"。

## 六、关键决策

如果哪一步发现 uteki.open 的方案明显不符合 uteki 架构（比如硬依赖
ClickHouse 做时间序列查询），停下来讨论：

| 选项 | 何时选 |
|---|---|
| 简化重写 | 大多数情况 — 用 SQLModel + 单表 |
| 引入新依赖 | 真的需要（如向量搜索）且 ROI 明确 |
| 放弃这个 feature | 价值低或跟 uteki 哲学冲突（如多页面 workbench） |
