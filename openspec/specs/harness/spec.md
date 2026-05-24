# Harness — spec

> 最新更新：2026-05-25 · M4 加入 user_id 注入（多租户）；tool-use loop（M3）+ artifact 注入（M5）+ 哲学段（吸收自 Anthropic）

## 哲学（不可妥协的原则）

uteki harness 的设计参考 [Anthropic · Harness Design for Long-Running Apps](https://www.anthropic.com/engineering/harness-design-long-running-apps)，落地 8 条原则：

1. **意图与执行分离** —— skill 只 yield `AgentEvent`；harness 负责真实副作用（调 tool / 写库 / 扣预算 / 记录）。任何"在 skill 里直接调用外部系统"的代码都是 spec 违规。
2. **预算 / 守卫硬上限** —— 6 项（max_steps / max_tool_calls / wall_time / max_input_tokens / max_output_tokens / max_cost_usd）。任何一项越界即终止，状态明确（error / timeout）。
3. **文件作 agent 通信脊梁**（计划于 005） —— planner / generator / evaluator 之间通过 artifact 文件交换，不靠 event 历史。
4. **多角色分工，独立评估**（计划于 006） —— "Generator 不会评判自己" → 必须有独立 Evaluator agent，且用不同模型。
5. **预算决策动态化** —— Evaluator 不是固定 on/off：任务难度低于当前模型能力时跳过，超过时启用。
6. **Prompt > Architecture**（计划于 007） —— 同样的 spec 调整 prompt 措辞可以从根上改变输出风格（"museum quality"）。比改架构便宜得多。
7. **Cite or flag** —— 任何数字必须能追溯到 tool_result，否则标 `[UNSOURCED]`。系统级防线，写在共享 guardrails.md。
8. **跨 session 状态在文件** —— event 流是日志，artifact 是真状态。session 之间靠 artifact 传递。

## 心智模型

Skill 只 yield 意图事件；harness 把意图变成动作并留痕。

## 构造参数

```python
AgentHarness(
    skill: BaseAgent,
    memory: Memory = default_memory,
    tools: ToolRegistry = default_registry,
    limits: HarnessLimits = HarnessLimits(),
    *,
    triggered_by: Literal["user","cron","event","eval","compare"] = "user",
    trigger_reason: str = "",
    run_store: RunStore = default_run_store,
    skill_version: str | None = None,
    user_id: str = "system",
)
```

`triggered_by` / `trigger_reason` / `run_store` / `skill_version` / `user_id` 是 keyword-only。

## M4 — user_id 注入

每一次 `run()` 都属于某个 user：

- 用户路由（`/api/agent/chat`、`/api/compare/run`、`/api/eval/run`）在构造 `AgentHarness` 时必须传 `user_id=user.id`（从 `Depends(current_user)` 拿到）
- 平台级调用（drift_monitor、scheduled cron、单元测试）省略 `user_id`，默认 `"system"` 兜底
- harness 把 `user_id` 写到 `Run.user_id`（必填字段；漏传 → `InMemoryRunStore.create` 抛 ValueError）
- harness 在创建 `RunArtifacts` 时把 `user_id` 透传给 `LocalFileArtifactStore`，落到 `data/users/<user_id>/runs/<sha2>/<run_id>/...`
- harness 所有 `memory.append_event(...)` 调用都加 `self.user_id` 作为前置参数（M4 后 Memory ABC 的短期方法签名变为 `(user_id, session_id, ...)`）

跨用户隔离的保证（API 层）：`run_store.get(run_id, user.id)` 不属于该 user 时抛 `KeyError`，路由统一映射为 404 —— 与"不存在"同形态，避免泄漏存在性。

## HarnessLimits — 六个硬上限

| 字段 | 默认 | 越界后 status | 越界后 event reason |
|---|---|---|---|
| `max_steps` | 20 | `error` | `max_steps_exceeded` |
| `max_tool_calls` | 30 | `error` | `max_tool_calls_exceeded` |
| `wall_time_seconds` | 120.0 | `timeout` | `deadline` |
| `max_input_tokens` | 200_000 | `error` | `max_input_tokens_exceeded` |
| `max_output_tokens` | 8_192 | `error` | `max_output_tokens_exceeded` |
| `max_cost_usd` | 1.0 | `error` | `max_cost_usd_exceeded ($N.NNNN)` |

`None` 代表无上限。三个 budget guard 都在 `usage` 事件到达时即时检查。

## Run 生命周期

```
[1] 分配 run_id (uuid4().hex[:12])
[2] 创建 Run 记录（在 RunStore）
[3] emit run_start
[4] for raw in skill.run(messages):
       ├── deadline check → error+break, status=timeout
       ├── 注入 run_id（model_copy）
       ├── 计数 step_start / tool_call → 超 → error+break
       ├── tool_call → 执行 tool（_invoke_tool）→ emit tool_result
       ├── delta → 缓冲，最后做 summary
       ├── usage → 累加 + budget check → 越界 emit error+break
       ├── error event → 标记 final_status=error
       └── 双写 memory + run_store, yield 给上游
[5] catch skill exception → emit error, status=error
[6] emit done
[7] 把 usage_totals 落回 Run.usage_summary
[8] run_store.finish(status, summary)
```

## Run 的字段

```python
class Run:
    id, skill, skill_version
    triggered_by, trigger_reason
    started_at, ended_at, status
    user_input, summary
    events: list[AgentEvent]
    tags: list[str]
    usage_summary: UsageSummary       # input/output/cache_read/cache_creation tokens + cost_usd
```

## 成本估算

```python
_PRICE_PER_M_TOKENS = {
    "claude-sonnet-4-6": {
        "input": 3.00, "output": 15.00,
        "cache_read": 0.30, "cache_creation": 3.75,
    },
    # 加新模型在这里
}
```

`_estimate_cost(model, usage)` 取 model id 最后一段（`anthropic/claude-sonnet-4-6` → `claude-sonnet-4-6`），未知模型返回 `0.0`。

## Skill injection（M3 + M5）

进 skill.run 前，harness 注入两个对象到 BaseAgent：

```python
self.skill._tool_executor = self._make_tool_executor(run_id)        # M3
self.skill.artifacts = RunArtifacts(                                 # M5
    store=default_artifact_store, run_id=run_id, written_by=self.skill.name,
)
```

skill 自由选择是否用。两个 inject 都是 run-scoped、identity-bound——skill 不能跨 run 操作，也不能假冒别的 skill。

## await_review 分支（M5）

```python
if event.type == "await_review":
    # 双写 + yield
    record = await self.run_store.get(run_id)
    if "auto-approved" not in record.tags:
        record.tags.append("auto-approved")
    continue
```

M5 只 auto-approve；005.2 接入 compliance_mode 真拦截。

## Tool-use loop（M3）

OpenAI 协议路径 —— DeepSeek / AiHubMix / OpenRouter 全覆盖。

```
harness.run(messages):
    self.skill._tool_executor = self._make_tool_executor(run_id)
    async for event in self.skill.run(messages):
        if event.type == "tool_call":
            ...
            if not event.data.get("_already_executed"):
                # 老路径：skill 单方 yield tool_call → harness 执行
                result = await self._invoke_tool(run_id, event)
                yield result
            # 新路径（_already_executed=True）：skill 已通过
            # stream_chat_with_tools 调过 tool；harness 仅留痕，跳过执行
```

skill 决策：
- 走 LLM 工具循环 → `llm.stream_chat_with_tools(payload, tools, self._tool_executor)`；翻译 `ToolCallRequested` / `ToolCallFulfilled` 为带 `_already_executed=True` 的 AgentEvent
- 不走（mock 路径或老 skill） → 仍 yield `tool_call` 让 harness 派发

Anthropic 原生 `tool_use` 协议（cache_control + content blocks）留到 change 004。

## Sub-skill delegation（M6 · pipeline meta-skill）

Harness 一次 run 对应一个 skill，这条不变量在 M6 没变。**pipeline 是
一个 yield 很多 event 的普通 skill**——它在自己内部按需把其他 skill 当作
"sub-skill"调起来，但 harness 视角只有一个 `self.skill`。

### Pipeline 怎么共享 harness 注入

```python
# pipeline 内部，run() 期间
async def _delegate(self, skill_name, messages, run_events):
    sub = default_skills.get(skill_name)
    sub._tool_executor = self._tool_executor   # 同 executor → 共享审计/预算
    sub.artifacts      = self.artifacts        # 同 facade   → 共享 run-scoped 文件
    yield AgentEvent(type="subagent_start", data={"name": skill_name})
    async for ev in sub.run(messages):
        run_events.append(ev.model_dump())     # 累积给后续 evaluator 用
        yield ev
    yield AgentEvent(type="subagent_end", data={"name": skill_name})
```

### 不变量

- **harness 不感知 pipeline**：对 harness 而言，pipeline yield 的
  `subagent_start` / `subagent_end` / `error` / `delta` / `tool_call` /
  ... 与任何 leaf skill yield 的事件无区别——双写 memory + run_store、计步、
  扣预算、deadline 检查统统一致执行。
- **没有 nested harness**：pipeline **不能**自己 `AgentHarness(sub_skill).run()`；
  那会产生两个 run_id、两份 run_store 记录，预算分裂。pipeline 只能调
  `sub.run(...)` 并把事件透传给上层 harness。
- **sub-skill 看到的 `artifacts` / `_tool_executor` 与独立跑时相同**：sub
  代码不该有 `if self._is_subagent: ...` 分支；想让 generator 看到 contract
  就把 contract 写入同一 run 的 artifacts，sub 读就好。
- **subagent_start/end 走默认双写**：harness 不需要为这两个新类型加特殊分支。

### 新增事件类型（M6）

`subagent_start` / `subagent_end`：参见 `openspec/specs/pipeline/spec.md`。

## 不变量

1. **写后 yield**：所有 yield 出去的 event 都已写 memory + run_store
2. **永远到 done**：skill 抛异常也走到 done + finish（status 标 error）
3. **skill 不可篡改 event**：harness 用 `event.model_copy(update={"run_id": ...})`，不改原对象
4. **tool 异常不冒泡**：单 tool 失败包成 `tool_result(ok=False)`，run 继续
5. **tool 不二次执行**：`_already_executed` 标记的 tool_call event 仅留痕，不重派
6. **跨 iteration 的 usage 单次结算**：`stream_chat_with_tools` 内部累加所有轮次的 token，最终 yield 一个 UsageDelta
7. **pipeline 在 harness 眼里是普通 skill**：subagent_start/end 走默认双写分支

## 不属于本 spec

- Anthropic 原生 tool_use（cache_control + content_blocks） —— change 004
- 用户级 partition（runs.user_id） —— change 001
- 异步 cancellation（SSE 客户端断开 → 中止 skill） —— follow-up
- Artifact 持久化机制本身 —— see `openspec/specs/artifacts/spec.md`
- Pipeline / 多 skill 编排细节 —— see `openspec/specs/pipeline/spec.md`
- LLM-as-judge —— change 007
