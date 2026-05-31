# Pipeline — spec

> 最新更新：2026-05-31 · research pipeline + company 7-gate pipeline

## 设计哲学

Anthropic harness design 的"多角色分工，独立评估"原则：

> Tuning a standalone evaluator to be skeptical turns out to be far more
> tractable than making a generator critical of its own work.

**Pipeline = 一个不调 LLM 的 meta-skill**，它从 `default_skills` registry 取
其他 skill 实例并按编排顺序调用；不是 harness 层的新机制。这样 harness
不变量（一次 run 一个 skill）依然成立——pipeline 对 harness 来说就是一个
yield 很多 event 的普通 skill。

## 组成

| 角色 | skill name | 职责 | 产物 |
|---|---|---|---|
| Planner | `planner` | 把一句话需求扩成 spec（含可机器校验的 acceptance criteria） | `plan.md`, `sprint-contract.json` |
| Generator | `research`（或其他） | 看 contract 跑工具循环写 draft | `final-research.md`（或对应名） |
| Evaluator | `evaluator` | 按 contract 跑 verifier 打分 | `eval-report.json` |
| 串联器 | `research_pipeline` | Planner → Generator → Evaluator → 必要时迭代 | `run-trace.json` |
| 公司投研串联器 | `company_research_pipeline` | 证据收集 → 6 个公司分析 gate → 同行排序 → 仓位计划 → 投资备忘录 | `final-report.md`, `decision.json`, `gate-*.md`, `ranking.json`, `capital-plan.json` |

## Sprint Contract schema

由 Planner 写入 `sprint-contract.json`：

```json
{
  "intent": "用户原话",
  "scope": ["维度1", "维度2", "..."],
  "acceptance_criteria": [
    {
      "id": "C1",
      "must": "human-readable assertion",
      "verifier": "regex_in_text" | "tool_call_in_run" | "numeric_in_range" | "llm_judge_score",
      "args": { ... }
    }
  ],
  "max_iterations": 3
}
```

`max_iterations` 上限 5（pipeline 强制 clamp）。

### Verifier 协议

每个 verifier 函数签名一致：返回 `(passed: bool, notes: str)`。

| Verifier | `args` | 说明 |
|---|---|---|
| `regex_in_text` | `{"pattern": str}` | 对 draft 文本跑 `re.search`（IGNORECASE） |
| `tool_call_in_run` | `{"tool_name": str}` | 在 `run-trace.json` 里找 `type=tool_call, data.name=<tool_name>` |
| `numeric_in_range` | `{"name": str, "lo": float, "hi": float}` | 在 label 之后 80 字符内找首个数字，检查范围 |
| `llm_judge_score` | `{"rubric": str, "min_score": int}` | M6 占位 always-pass；007 接 LLM judge |

Verifier 不是 tool，不进 ToolRegistry —— Generator LLM 看不见，调不到。

## ResearchPipeline 编排

```python
yield plan
async for ev in delegate("planner", messages, run_events): yield ev
contract = read("sprint-contract.json")

for iteration in range(contract.max_iterations):
    async for ev in delegate("research", messages, run_events, iteration=iteration): yield ev
    write("run-trace.json", json.dumps(run_events))
    async for ev in delegate("evaluator", messages, run_events, iteration=iteration): yield ev

    report = read("eval-report.json")
    if report.decision == "approve": break
    if report.decision == "reject": break
    # revise: 把 suggestions 拼成 user message 加到下一轮 messages
    messages.append(ChatMessage(role="user", content="Evaluator 反馈，请改进...\n- " + "\n- ".join(report.suggestions)))
```

### `_delegate(name, ...)` 不变量

1. **共享 tool executor**：`sub.skill._tool_executor = self._tool_executor`
2. **共享 artifacts facade**：`sub.skill.artifacts = self.artifacts`
3. **包装事件**：sub 的所有 event 都被前后裹上 `subagent_start` / `subagent_end`
4. **错误隔离**：sub 抛异常 → emit `error` event，pipeline 仍走 `subagent_end`
5. **事件累积**：sub 每个 event 序列化 (model_dump) 进 `run_events: list[dict]`，给 Evaluator 的 `tool_call_in_run` verifier 用

## 新事件类型

```python
"subagent_start"   data: {name: str, iteration?: int}
"subagent_end"     data: {name: str, iteration?: int}
```

前端 Trace 在 `subagent_start` 看见后，把后续事件的渲染缩进 16px（depth × 16），
直到匹配的 `subagent_end`。

## SkillRegistry.kind

```python
SkillEntry.kind: Literal["skill", "pipeline"] = "skill"
```

`research_pipeline` 注册时 `kind="pipeline"`，其他 leaf skill `kind="skill"`。
前端 skill picker 可以分组展示。

## API

无新端点。`POST /api/agent/chat { "agent": "research_pipeline", ... }` 或
`POST /api/agent/chat { "agent": "company_research_pipeline", ... }` 即可。

## CompanyResearchPipeline（006-company-research-pipeline / 009-company-deep-research-v2）

从 `uteki.open` 迁移 7-gate 投研框架，但不迁移旧 domain service / SQL repository / XML tool parser。
在 uteki 中它是一个普通 pipeline skill：

1. 解析目标美股 ticker；若用户提供 peer，则最多取 3 家，否则按内置美股 peer map 自动补齐最多 3 家
2. 用 harness `_tool_executor` 为目标和 peers 拉取 `market_quote`、`financials`、`news_search`
3. 写入 `company-profile.json`、`financials.json`、`news-brief.json`
4. 依次运行 6 个目标公司分析 gate：
   - `business_analysis`
   - `fisher_qa`
   - `moat_assessment`
   - `management_assessment`
   - `reverse_test`
   - `valuation`
5. 每个 gate 用 `subagent_start` / `subagent_end` 包裹，并写 `gate-<NN>-<name>.md`
6. 基于确定性 scorecard 写 `peer-comparison.json` 和 `ranking.json`，ranked companies 最多 4 家（目标 + 3 peers）
7. 写 `capital-plan.json`：给出 BUY / WATCH / AVOID 对应的初始仓位、最大仓位、加仓/减仓/卖出触发条件；最大单名仓位上限 10%；不执行真实下单
8. 每个关键阶段更新 `agent-capability-review.json`，评价 autonomy / observability / traceability / self-iteration
9. 综合写 `final-report.md`（role=`primary`）和 `decision.json`
10. 若工具返回 sources，harness 自动补 `source-catalog.json`

旧 006 单公司 contract 仍兼容：

1. 用 harness `_tool_executor` 拉取 `market_quote`、`financials`、`news_search`
2. 写入 `company-profile.json`、`financials.json`、`news-brief.json`
3. 依次运行 6 个分析 gate：
   - `business_analysis`
   - `fisher_qa`
   - `moat_assessment`
   - `management_assessment`
   - `reverse_test`
   - `valuation`
4. 每个 gate 用 `subagent_start` / `subagent_end` 包裹，并写 `gate-<NN>-<name>.md`
5. 综合写 `final-report.md`（role=`primary`）和 `decision.json`
6. 若工具返回 sources，harness 自动补 `source-catalog.json`

### Gate vs Skill

`skill` 是 harness 可调度的能力单元：有 registry 名称、推荐 limits、工具列表、model signature、artifact facade 和 run 级 trace。

`gate` 是 `company_research_pipeline` 内部的投资分析检查点：它有独立 prompt、artifact 和 subagent trace，但不单独注册到 SkillRegistry，也不能被用户直接调度。因此当前实现是 **agentic pipeline**，不是“每个 gate 一个独立 agent”的 multi-agent 系统。

这个边界是刻意选择：第一版深研先保持数据流简单，避免把 6 个 gate 过早拆成 6 个可复用 skill。后续若需要更强自治，应优先拆出可复用的 `company_peer_ranker`、`capital_allocator`、`risk_reviewer` 或 `company_gate_*` skills。

迁移边界：保留投资框架和 gate naming；旧的 ReAct XML 解析器、company_analyses 表、provider adapter 层不复制。

## 关键文件

- `services/api/src/uteki_api/skills/planner/{__init__.py,SKILL.md}`
- `services/api/src/uteki_api/skills/evaluator/{__init__.py,SKILL.md,verifiers.py}`
- `services/api/src/uteki_api/skills/pipelines/{__init__.py,research_pipeline.py}`
- `services/api/src/uteki_api/skills/company/__init__.py`
- `services/api/src/uteki_api/skills/research/__init__.py` —— `_load_contract_criteria()` 把 contract acceptance_criteria 拼进 system prompt
- `services/api/src/uteki_api/schemas/events.py` —— 加 `subagent_start` / `subagent_end`
- `apps/web/components/agent/Trace.tsx` —— 缩进渲染 + 新事件 dot 配置
- `apps/web/lib/types.ts` —— EventType 同步

## 不变量

1. **Pipeline 不调 LLM**：自己 yield 只是 `plan` / `subagent_*` / `log` / `error`；所有 LLM/tool 真实调用都发生在 sub-skill 内
2. **Sub-skill 不知道自己被 pipeline 调**：它访问 `self.artifacts` / `self._tool_executor` 跟独立跑时一模一样；不可侵入 sub-skill 的接口
3. **Generator 看 contract 是 opt-in**：research skill 在 `run()` 入口检查 `self.artifacts` 是否有 `sprint-contract.json`；没有就走老路径
4. **Evaluator 是纯函数式**：M6 的 verifier 全部不调 LLM（`llm_judge_score` 占位 always-pass）→ 结果可复现、可单测
5. **迭代有上限**：`max_iterations` clamp 到 `[1, 5]`，pipeline 内部循环固定上限；保险丝是 harness 的 `max_steps`
6. **revise 必须有 suggestions**：Evaluator 标 revise 但 suggestions 为空 → pipeline 提前 break（不空转）
7. **公司投研产物按 gate 拆分**：公司 pipeline 的每个 gate 都必须有独立 artifact，最终裁决必须落在 `final-report.md`
8. **公司深研不下单**：`capital-plan.json` 只给 sizing guidance，`real_order_execution=false`，不调用高风险交易工具
9. **公司深研引用可校验**：最终 memo 的 `[src:*]` 引用必须是 SourceCatalog 数字 id 或 `[src:none]`；模型生成的非 catalog label 必须被确定性清洗

## 不属于本 spec

- LLM-as-judge 真实实装（占位见 `llm_judge_score` stub） —— change 007
- Pipeline 并行 sub-skill —— 显式不做（串行就够）
- 多 sprint 串行（Anthropic 后来去掉了 sprint 概念） —— 显式不做
- Pipeline 自身的 prompt 模板（pipeline 行为是代码，不是 prompt） —— 设计如此
- 前端真正的折叠 / 展开交互 —— 仅缩进，折叠/展开是 follow-up
