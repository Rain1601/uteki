# uteki Agent 设计

本文档详细说明 uteki 后端 agent 子系统：harness、skill、tool、memory、events、runs、evolution、eval、trigger、多模型路由。

读完本文档你应该能：

- 写一个新的 skill
- 写一个新的 tool 并接入真实数据源
- 理解一次 run 如何被持久化、回放、对比
- 理解 skill 的版本如何被记录与对齐
- 知道在哪里加 cron / 事件触发

## 0. 概念词汇

| 词 | 含义 |
|---|---|
| **skill** | 一种"能力"，比如投研、盘后回顾、选股、QA。代码上是 `BaseAgent` 的子类。 |
| **harness** | 编排层。skill 只表达意图，harness 真正执行、限流、写 run。 |
| **tool** | skill 在执行中调用的外部能力（行情、新闻、PDF 解析、web 搜索…）。 |
| **memory** | skill 的"记忆"。session 短时（对话上下文）+ 用户长时（事实库）。 |
| **run** | 一次具体执行。记录触发原因、事件流、最终输出、耗时。 |
| **event** | run 中的一条记录。`AgentEvent` 统一类型（plan / step_start / thinking / tool_call / tool_result / delta / citation / usage / log / error / done）。 |
| **version** | skill 的某一版配置（prompt + tools + model + params）的快照。 |
| **trigger** | 让 run 发生的原因：user / cron / event / eval / compare。 |

## 1. AgentEvent — 一切交互的载体

```python
class AgentEvent(BaseModel):
    type: Literal["run_start","plan","step_start","step_end",
                  "thinking","tool_call","tool_result",
                  "delta","citation","usage","log","error","done"]
    run_id: str | None
    step_id: str | None
    parent_id: str | None
    data: dict[str, Any]     # 字段随 type 而变
    ts: float
```

`data` 各类型的形状（约定，前后端保持一致）：

| type | data |
|---|---|
| `run_start` | `{agent, session_id}` |
| `plan` | `{steps: [str, ...]}` |
| `step_start` / `step_end` | `{title}` / `{status: "ok"\|"error"}` |
| `thinking` | `{text}` |
| `tool_call` | `{name, args}` |
| `tool_result` | `{name, ok, summary, preview, error?}` |
| `delta` | `{text}` |
| `citation` | `{title, source, url?}` |
| `usage` | `{input_tokens, output_tokens, cost?}` |
| `log` | `{level: "info"\|"warn"\|"error", message, extra?: dict}` |
| `error` | `{reason}` |
| `done` | `{steps, tools}` |

**为什么单一通道**：前端只需要监听一个 SSE 流；后端只需写一个 store；记录、回放、评测、对比都基于同一种数据结构。

## 2. Harness — 协议与生命周期

```
AgentHarness(skill, *, memory, tools, limits,
             triggered_by, trigger_reason, run_store, skill_version)
    .run(messages, session_id=None) -> AsyncIterator[AgentEvent]
```

每次 `run()`：

1. 分配 `run_id`；创建 `Run` 写入 `RunStore`
2. 发 `run_start`
3. `async for raw in skill.run(messages):`
   - 注入 `run_id`
   - `step_start` 计数；超 `max_steps` → `error("max_steps_exceeded")` 终止
   - `tool_call` → 调 `ToolRegistry`，发 `tool_result`；超 `max_tool_calls` 同上
   - `delta` → 写入 buffer 用于 summary
   - 任何 `error` → 标记 `final_status="error"`
   - 写 memory + run store；yield 给上游 SSE
4. 超 `wall_time_seconds` → `error("deadline")`
5. 发 `done`，`run_store.finish(status, summary)`

harness 的**不变量**：

- skill 永远只 yield，不直接执行 tool（避免 skill 内部硬编码 IO）
- 任何 yield 出去的事件**都已经写入 run store**（回放保真）
- 即使 skill 抛异常，run 也会以 status=error 落库

## 3. Skill — 写一个新 skill

```python
# services/api/src/uteki_api/skills/my_skill.py
from collections.abc import AsyncIterator
from uteki_api.agents.base import BaseAgent
from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent

class MySkill(BaseAgent):
    name = "my_skill"

    async def run(self, messages: list[ChatMessage]) -> AsyncIterator[AgentEvent]:
        yield AgentEvent(type="plan", data={"steps": ["第一步", "第二步"]})
        yield AgentEvent(type="step_start", data={"title": "第一步"})
        yield AgentEvent(type="tool_call",
                         data={"name": "kline", "args": {"symbol": "300750.SZ"}})
        # harness 会在下一步注入 tool_result
        yield AgentEvent(type="delta", data={"text": "结论…"})
        yield AgentEvent(type="step_end", data={"status": "ok"})

    def current_signature(self) -> dict:
        return {
            "prompt": "...",
            "tool_names": ["kline", "news_search"],
            "model": "openrouter/anthropic/claude-sonnet-4-6",
            "params": {"temperature": 0.3},
        }
```

注册：在 `skills/__init__.py` `default_skills.register(MySkill(), description="...", version="v1", default_tools=[...], default_model="...")`。

启动时 lifespan 会自动检查 `current_signature()` 与 `EvolutionStore` 中最新版本是否一致，不一致就写一条新版本。

## 4. Tool — 写一个新工具

```python
# services/api/src/uteki_api/tools/my_tool.py
from typing import Any
from uteki_api.tools.base import Tool, ToolResult

class MyTool(Tool):
    name = "my_tool"
    description = "做某件事"
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {"x": {"type": "string"}},
        "required": ["x"],
    }

    async def run(self, **kwargs: Any) -> ToolResult:
        x = kwargs.get("x", "")
        if not x: return ToolResult(ok=False, error="x is required")
        return ToolResult(ok=True, summary=f"done: {x}", data={"x": x})
```

注册：`tools/__init__.py` `default_registry.register(MyTool())`。
所有 tool 自动具备 OpenAI 兼容的 function-calling JSON spec：`tool.to_openai_spec()`。

**当前工具清单**（mock 数据，待接入真实源）：

| name | 真实接入候选 |
|---|---|
| `market_quote` | akshare / Tushare / Wind |
| `news_search` | 同花顺新闻 / 财联社 / 自建 |
| `kline` | akshare bar / Tushare daily |
| `financials` | akshare / Wind 财务接口 |
| `report_analysis` | PDF → unstructured / GPT-4o vision |
| `web_search` | Tavily / Serper / Brave |
| `web_extract` | Jina Reader / Trafilatura |

## 5. Memory — 短时 + 长时

```python
class Memory(ABC):
    # 短时（per session）
    async def append_message(self, session_id, message)
    async def get_messages(self, session_id)
    async def append_event(self, session_id, event)
    async def get_events(self, session_id)
    # 长时（per user）
    async def remember_fact(self, user_id, fact, meta=None)
    async def recall_facts(self, user_id, query, limit=5)
```

默认 `InMemoryStore` 进程内字典。生产换 Redis（短时）+ Postgres + pgvector（长时）。

短时记忆给 skill 提供"上一轮我说了什么"；长时记忆把"这个用户长期关注半导体板块"喂给 skill 做个性化。

## 6. Run — 记录与回放

```python
class Run(BaseModel):
    id: str
    skill: str
    skill_version: str | None
    triggered_by: Literal["user","cron","event","eval","compare"]
    trigger_reason: str
    started_at: float
    ended_at: float | None
    status: Literal["running","ok","error","timeout"]
    user_input: str
    summary: str            # 首 ~200 字最终回答
    events: list[AgentEvent]
    tags: list[str]
```

`RunStore` 是抽象接口，默认 `InMemoryRunStore`。前端从 `/api/runs` 和 `/api/runs/{id}` 拿数据回放——展示效果与原始流式一致，因为事件序列被原样存储。

## 7. Evolution — agent 的"git 历史"

```python
class SkillVersion(BaseModel):
    skill: str
    version: str            # "v1","v2",...
    prompt: str
    tool_names: list[str]
    model: str
    params: dict
    created_at: float
    parent_version: str | None
    changelog: str          # 人读 diff
```

`main.py` 在 lifespan 启动时：

```
for skill in default_skills.list():
    sig = skill.current_signature()
    prev = evolution_store.latest(skill.name)
    if prev is None: record v1
    elif sig != prev: record v(N+1), changelog = diff(prev, sig)
```

每条 Run 的 `skill_version` 字段绑定当时的 version → 用户可以**纵向**对比"同一 skill 在 v1 vs v3 的表现差异"。

## 8. 多模型路由

```python
ModelRouter.resolve("openrouter/anthropic/claude-sonnet-4-6") → LLMClient(...)
ModelRouter.resolve("aihubmix/gpt-4o-mini") → LLMClient(...)
```

约定：模型 id 以 `<provider>/<upstream_id>` 形式。Provider 注册表在 `llm/router.py` `PROVIDERS`。
两家供应商都讲 OpenAI Chat Completions 协议，所以 `LLMClient` 一套实现即可。

API key 走环境变量：`OPENROUTER_API_KEY`、`AIHUBMIX_API_KEY`。

## 9. Eval — 回归与质量门控

```python
EvalCase:
    id, description, messages, expected_substrings, expected_tools

EvalRunner.run_case(case)
    → harness.run(case.messages, triggered_by="eval")
    → 收集 deltas / tool_calls
    → score: substring_score, tool_score
    → passed = score >= 0.5
```

`/api/eval/run` 跑所有 `eval/cases/*.json`，返回 `EvalReport`。
CI 钩：可配置 pass_rate 阈值（如 ≥ 0.8）作为合并门禁。

未来：LLM-as-judge（用另一个模型给 final text 打分），baseline 漂移告警。

## 10. 触发机制

```python
CronTrigger(id, cron, agent, prompt, enabled)
EventTrigger(id, topic, agent, prompt_template, enabled)
```

- Cron：`apscheduler`（待接入 main lifespan），按 cron 定时触发 `harness.run(..., triggered_by="cron", trigger_reason=trigger_id)`
- Event：webhook 进 `POST /api/triggers/event {topic, payload}`；registry 找匹配 EventTrigger，按模板渲染 prompt 后投递到队列（推荐 Vercel Queues / Celery / arq）

两类触发的所有执行都和用户对话**走同一个 harness**，写入同一个 RunStore——所以 `/api/runs?triggered_by=cron` 可以看到所有定时任务的历史。

## 11. 多 agent 对比

横向：`POST /api/compare/run {messages, agents}` 用 `asyncio.gather` 并行 skill；返回 `run_ids`。

```
agents=["research","qna"]
   ├─ harness(research, triggered_by="compare", trigger_reason="vs:qna")
   └─ harness(qna,      triggered_by="compare", trigger_reason="vs:research")
```

`POST /api/compare/diff {run_ids}` 拉两个 run，组装结构化对比：

```
{
  runs: [
    {id, skill, latency_ms, tools_called, usage, summary, final_text},
    ...
  ]
}
```

前端 `/compare` 页面并排展示。

纵向：`/api/runs?skill=research` 按时间排序，前端按 `skill_version` 染色，即可看到同一 skill 在不同版本下的表现轨迹。

## 12. 前端可视化协议

- `lib/api.ts streamChat()` 用 fetch + ReadableStream 解析 `data: ...\n\n` 帧
- 每条事件转成 `AgentEvent`，分发到：
  - `Trace.tsx` 时间线
  - `Message.tsx` 助手气泡（消费 delta）
  - `PlanCard.tsx` / `ToolCallCard.tsx` / `LogLine.tsx` 等专门组件

## 13. 未实现 / TODO

- 工具全部 mock，需接入真实源（akshare / Tavily / PDF parser…）
- LLM 真实调用路径：研究 agent 跑通端到端 plan→tool→synthesize loop（OpenAI tool-call 模式）
- 短时记忆只缓存 events，没把跨轮对话喂回 skill；下一步要在 harness 入口拼接 history
- 长时记忆是简单 keyword score，需要换 pgvector
- 触发执行没接 scheduler / queue（registry 只是声明）
- Eval 的 LLM-as-judge 未实装
- iOS/Android 客户端
