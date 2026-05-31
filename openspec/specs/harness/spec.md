# Harness — spec

> 最新更新：2026-05-31 · M4 user_id；M3 tool-use；M5 artifact；004 provenance；005 artifact-first runs；007 trace diagnosis；008 tool governance；M1.x as_of backtest

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
    as_of: date | None = None,
)
```

`triggered_by` / `trigger_reason` / `run_store` / `skill_version` / `user_id` / `as_of` 是 keyword-only。

## M4 — user_id 注入

每一次 `run()` 都属于某个 user：

- 用户路由（`/api/agent/chat`、`/api/compare/run`、`/api/eval/run`）在构造 `AgentHarness` 时必须传 `user_id=user.id`（从 `Depends(current_user)` 拿到）
- 平台级调用（drift_monitor、scheduled cron、单元测试）省略 `user_id`，默认 `"system"` 兜底
- harness 把 `user_id` 写到 `Run.user_id`（必填字段；漏传 → `InMemoryRunStore.create` 抛 ValueError）
- harness 在创建 `RunArtifacts` 时把 `user_id` 透传给 `LocalFileArtifactStore`，落到 `data/users/<user_id>/runs/<sha2>/<run_id>/...`
- harness 所有 `memory.append_event(...)` 调用都加 `self.user_id` 作为前置参数（M4 后 Memory ABC 的短期方法签名变为 `(user_id, session_id, ...)`）

跨用户隔离的保证（API 层）：`run_store.get(run_id, user.id)` 不属于该 user 时抛 `KeyError`，路由统一映射为 404 —— 与"不存在"同形态，避免泄漏存在性。

## M1.x — as_of backtest 时间窗

`AgentHarness(as_of=date)` 让一次 run 进入"如果今天是 X 日"的回测模式。`None` = live mode（默认）。

### 注入路径

- `ChatRequest.as_of: date | None` → `/api/agent/chat` 接受可选 ISO 字符串
- `_build_harness(..., as_of=req.as_of)` → harness 构造时拿到
- `AgentHarness.__init__` 把 `as_of.isoformat()` 缓存为 `self._as_of_iso`
- 三个下游同时受影响：
  1. **SourceCatalog** —— `SourceCatalog(as_of=self._as_of_iso)`：catalog 自带的 future-`published_at` 拒绝逻辑（004）触发。
  2. **tool kwargs** —— `_invoke_tool` 把 `as_of=ISO_DATE` 写进 `args`，**前提是 skill 没显式传** —— skill 始终有最终决定权（可能想要 tool call 跨窗口）。同样路径覆盖 `_make_tool_executor`（LLM tool-use loop）。
  3. **skill 自身** —— `self.skill.as_of = self._as_of_iso`：skill 可在 prompt 里告诉 LLM "今天是 X"，避免模型用训练截止后的常识。
- `Run.tags` 自动加 `as_of:YYYY-MM-DD`，方便 `/api/runs?tag=...` 查询（filter 端点未来再加；tag 先落）。

### Tool 责任

每个 tool 自己决定如何处理 `as_of`：

| Tool 类型 | 处理 | 例子 |
|---|---|---|
| 历史性（fetcher 支持 end=）| 在 API 调用层切片 | `kline`：`yfinance.history(end=as_of+1d)`，把 as_of 当天含进去 |
| 历史性（fetcher 不支持）| fetch 后客户端 filter | `financials`：post-fetch 过滤 `period_label[:10] <= as_of` |
| 历史性（外部不可控）| fetch 后客户端 filter + 报告 dropped 数 | `news_search`：过滤 `published_at > as_of` 的 item，无 published_at 的保留 |
| 快照性 | **拒绝**（`ok=False`），指明替代 tool | `market_quote` as_of < today → "use kline instead"。**不允许 silent fallback**——会产生看不见的 correctness bug |
| 不可控源头 | soft inject 进 query；最终靠 catalog 把关 | `web_search`：query 末尾拼 `(information available as of X)` |
| 无源头时间线 | 不动 | `web_extract`：已经把 `published_at` 写进 source dict，catalog 自己拒绝 |

### 不变量

- `as_of` 缺省 = live = 所有 tool 行为与历史一致（向后兼容；T11 + 32 个已有 E2E 验证）
- `as_of` 设置后 catalog 里**不能**出现 `published_at > as_of` 的 DataPoint（T11 断言）
- `Run.tags` 包含 `as_of:YYYY-MM-DD` 当且仅当 harness 收到了 `as_of` 参数

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
[6] 若有最终内容但没有主产物，写 `final-report.md` 并 emit `artifact_written`
[7] 若 source catalog 非空，写 `source-catalog.json` 并 emit `artifact_written`
[8] 写 `trace-diagnosis.json` 并 emit `artifact_written`
[9] emit done
[10] 把 usage_totals 落回 Run.usage_summary
[11] run_store.finish(status, summary)
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
self.skill.sources = RunSources(SourceCatalog(run_id=run_id))         # 004
```

skill 自由选择是否用。这些 inject 都是 run-scoped、identity-bound——skill 不能跨 run 操作，也不能假冒别的 skill。

## Provenance / source catalog（004）

ToolResult 可携带 source metadata：

```python
class ToolResult(BaseModel):
    ok: bool
    summary: str = ""
    data: Any = None
    error: str | None = None
    sources: list[dict[str, Any]] = []
```

`_invoke_tool()` 执行 tool 后：

1. 把 `result.sources` 注册进 `self.skill.sources`
2. 将注册后的 ids 写进 `tool_result.data.preview._source_ids`
3. 不因 malformed source metadata 失败 tool call

run 结束前，如果 catalog 非空且尚未写 `source-catalog.json`，harness 自动写 artifact 并 emit `artifact_written`。因此前端和 evaluator 可以把来源目录当成 run 的标准产物读取。

## Artifact-first runs（005-artifact-first-runs）

Run detail 的阅读入口是 artifact，不是 delta 拼接。Harness 在 run 完成前执行 primary artifact fallback：

1. 如果 `final-report.md` 已存在，不重复写
2. 优先复制 `investment-memo.md`、`final-research.md`、`research.md`
3. 若没有命名产物，则使用本次 run 累积的 delta 文本
4. 写入 `final-report.md`，`role="primary"`，`display_name="Final report"`
5. emit `artifact_written`

这保证旧 skill、mock path 和真实 LLM path 都能被 artifact-first UI 读取，同时不破坏旧事件回放。

## Trace diagnosis（007-trace-diagnosis）

Harness 在 `done` 前写入 `trace-diagnosis.json`，role=`diagnosis`。它是从事件流和 run-scoped state 派生的确定性 JSON，不调用 LLM：

- `event_counts`
- `failures`
- `warnings`
- `tools.calls`
- `tools.failures`
- `usage`
- `artifacts`
- `citations`

该 artifact 是 review/debug 的摘要入口；原始 `/events` 仍是完整审计日志。

## await_review / high-risk tool checkpoint（008）

当前语义选择：**立即 reject，fail-closed**。

`await_review` 在 008 阶段不是一个会暂停 run 并等待人工输入的异步状态；
它是高风险工具被拦截时的治理检查点事件，供 UI、审计和后续 005.2 人审
能力识别"这里本来需要 review"。

当前 high-risk tool 的完整事件序列必须是：

```python
tool_call(name="...", risk_level="high")
await_review(checkpoint="high_risk_tool", auto_approved=False)
tool_result(ok=False, error="high_risk_tool_requires_review")
```

约束：

- Harness 不执行 `risk_level="high"` 的工具。
- Harness 先 emit `await_review` 留下审计点，再 emit 失败的 `tool_result` 结束该 tool call。
- `await_review` 事件名保留给未来 005.2 真正的人审 / `compliance_mode` 暂停能力；在该能力落地前，它表示"需要 review 且已被当前 harness 阻断"。
- Skill 不得通过自行执行工具绕过这个序列。真实副作用仍只能由 harness 执行。

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

## Tool governance（008-tool-governance）

每个 tool 暴露：

```python
Tool.risk_level: Literal["low", "medium", "high"] = "low"
```

Harness 是唯一允许执行真实副作用的边界：

- `low` / `medium`：按原逻辑执行
- `high`：默认不执行
  - emit `await_review`，`checkpoint="high_risk_tool"`
  - emit `tool_result(ok=False, error="high_risk_tool_requires_review")`

Risk level 也会写入 OpenAI/Anthropic tool spec 的 description，帮助模型在计划阶段知道工具风险；但真正的拦截必须发生在 `_invoke_tool()` / harness tool-call 分支，不能依赖 prompt。

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
8. **source catalog 不破坏 run**：source metadata 解析失败不会让 tool / run 失败；失败只影响 verifier 结果
9. **primary artifact 优先**：已完成 run 若有最终内容，必须可通过 `primary_artifact` 读取；events 仅作为诊断日志
10. **diagnosis 不影响 run**：诊断生成失败只 emit warn log，不应让业务 run 失败
11. **高风险工具默认不执行**：LLM 请求 high-risk tool 只能得到 review checkpoint + blocked result，不能产生副作用

## 不属于本 spec

- Anthropic 原生 tool_use（cache_control + content_blocks） —— change 004
- 用户级 partition（runs.user_id） —— change 001
- 异步 cancellation（SSE 客户端断开 → 中止 skill） —— follow-up
- Artifact 持久化机制本身 —— see `openspec/specs/artifacts/spec.md`
- Pipeline / 多 skill 编排细节 —— see `openspec/specs/pipeline/spec.md`
- LLM-as-judge —— change 007
- Provenance / citation schema 细节 —— see `openspec/specs/provenance/spec.md`
