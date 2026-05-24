# Pipeline — spec

> 最新更新：2026-05-24 · change 006 落地

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

无新端点。`POST /api/agent/chat { "agent": "research_pipeline", ... }` 即可。

## 关键文件

- `services/api/src/uteki_api/skills/planner/{__init__.py,SKILL.md}`
- `services/api/src/uteki_api/skills/evaluator/{__init__.py,SKILL.md,verifiers.py}`
- `services/api/src/uteki_api/skills/pipelines/{__init__.py,research_pipeline.py}`
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

## 不属于本 spec

- LLM-as-judge 真实实装（占位见 `llm_judge_score` stub） —— change 007
- Pipeline 并行 sub-skill —— 显式不做（串行就够）
- 多 sprint 串行（Anthropic 后来去掉了 sprint 概念） —— 显式不做
- Pipeline 自身的 prompt 模板（pipeline 行为是代码，不是 prompt） —— 设计如此
- 前端真正的折叠 / 展开交互 —— 仅缩进，折叠/展开是 follow-up
