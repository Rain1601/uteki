# uteki 架构总览

## 一句话

uteki 把投研流程做成对话式 agent：用户提问 → skill 调度工具 → 流式回答 → 全量留痕 → 可对比、可评测、可触发。

## 拓扑

```
                    ┌─────────────────────────────────┐
                    │            Frontends            │
                    │  web (Next.js)  ios   android   │
                    └─────────────┬───────────────────┘
                                  │  HTTPS / SSE
                                  ▼
                ┌────────────────────────────────────────────┐
                │              FastAPI (uteki-api)            │
                │                                             │
                │  api/                                       │
                │   ├── health        /health                 │
                │   ├── agent         /api/agent/chat (SSE)   │
                │   ├── agents        /api/agents/**          │
                │   ├── runs          /api/runs/**            │
                │   ├── compare       /api/compare/**         │
                │   ├── eval          /api/eval/**            │
                │   └── triggers      /api/triggers/**        │
                │                                             │
                │  agents/Harness ──orchestrates──┐           │
                │       │                         │           │
                │       ▼                         ▼           │
                │  skills/                    tools/          │
                │   ├── research              ├── market_quote│
                │   ├── recap                 ├── news_search │
                │   ├── screener             ├── kline       │
                │   └── qna                   ├── financials  │
                │                             ├── report_analysis
                │                             ├── web_search  │
                │                             └── web_extract │
                │                                             │
                │  memory/  runs/  evolution/  eval/  triggers│
                │                                             │
                │  llm/router ──► OpenRouter / AiHubMix / ... │
                └────────────────────────────────────────────┘
```

## 13 维需求 → 落地映射

| # | 维度 | 实现位置 |
|---|---|---|
| 1 | agent 执行过程可视化 | `schemas/events.AgentEvent` + `apps/web/components/agent/Trace.tsx` |
| 2 | agent 执行结果可视化 | `apps/web/app/runs/[id]/page.tsx`（回放） |
| 3 | **harness** | `agents/harness.AgentHarness`：guardrails / tool dispatch / run 写入 / 版本绑定 |
| 4 | 结果评测 | `eval/runner.EvalRunner` + `/api/eval/run` |
| 5 | 触发机制 | `triggers/registry.{CronTrigger,EventTrigger}` + `/api/triggers/event` |
| 6 | tools / memory | `tools/base.Tool` + `tools/*` + `memory/{base,in_memory}.py` |
| 7 | 多模型 | `llm/router.ModelRouter`（OpenRouter / AiHubMix 前缀路由） |
| 8 | 动态前端渲染 | SSE + `Trace.tsx` 按 `event.type` 模式匹配渲染 |
| 9 | 结构化日志 | `AgentEvent` `type="log"` `data={level,message,extra}` + `LogLine.tsx` |
| 10 | skill 模式 | `skills/` 包 + `SkillRegistry` |
| 11 | 触发原因 + 全事件留痕 | `runs/Run` 字段 `triggered_by`, `trigger_reason`, `events` |
| 12 | agent 自我进化 trace | `evolution/SkillVersion` + 启动期自动 diff |
| 13 | 横向 / 纵向对比 | `api/compare.py` + `apps/web/app/compare/page.tsx`; 历史比较走 `runs/list` |

## 数据流（一次对话）

```
user → POST /api/agent/chat {messages, agent:"research"}
        │
        ▼
   SkillRegistry.get("research") ──► ResearchAgent
        │
        ▼
   AgentHarness.run(messages, triggered_by="user", trigger_reason="chat:...")
        │
        ├─► RunStore.create(Run{id, skill, skill_version, ...})
        │
        ├─► async for event in skill.run():
        │     ├─► Memory.append_event(session_id, event)
        │     ├─► RunStore.append_event(run_id, event)
        │     ├─► if event.type == "tool_call":
        │     │     ToolRegistry.get(name).run(**args)
        │     │     emit tool_result event
        │     └─► yield event  ──► SSE ──► frontend
        │
        └─► RunStore.finish(run_id, status, summary)
```

## 演化（agent 自我迭代）

每个 skill 启动时调用 `current_signature() → {prompt, tool_names, model, params}`。`main.py` lifespan 把签名和 `EvolutionStore.latest(name)` 对比：

- 不存在 → 写入 `v1`
- 已存在但签名变了 → 写入 `vN+1`，`changelog` 含字段级 diff

每次 run 的 `skill_version` 字段绑定当时的 version。`/api/agents/{name}/versions` 可以按时间纵向看：

```
v1 [research]  prompt: ...  tools: [market_quote, news_search]  model: claude-sonnet-4-6
v2 [research]  prompt: ...  tools: [+kline, +financials]        model: same
v3 [research]  prompt: ...  tools: same                          model: gpt-5
```

结合 `/api/runs?skill=research` 即可纵向比较"同一 skill 不同版本的实际表现"。

## 横向对比

`POST /api/compare/run {messages, agents: [a, b, c]}` 用 `asyncio.gather` 并行 harness，每个 agent 写一条 Run。前端拿 `run_ids` 后 poll `/api/runs/{id}`，再调 `/api/compare/diff` 拿结构化对比（延迟、tool 调用、final text）。

## 触发机制

| 来源 | 入口 | 用途 |
|---|---|---|
| 用户 | `POST /api/agent/chat` | 对话 |
| 定时 | `CronTrigger` (cron 表达式) | 盘后回顾、晨报 |
| 事件 | `POST /api/triggers/event` | 财报披露 / 突发新闻 / 价格突破 |
| 评测 | `eval/EvalRunner` | 回归测试 |
| 对比 | `POST /api/compare/run` | A/B |

所有来源最终都走同一个 `AgentHarness.run()`，写入同一个 `RunStore`。这是关键不变量：**一切执行都是一条 Run**。

## 目录结构

```
uteki/
├── apps/
│   ├── web/                # Next.js 16 + React 19
│   ├── ios/                # 占位
│   └── android/            # 占位
├── services/
│   └── api/                # FastAPI + uv
├── packages/
│   ├── shared-types/       # OpenAPI 生成的 TS 类型
│   └── ui/                 # 共享 React 组件占位
├── docs/                   # 本文档目录
└── scripts/                # dev / gen-types
```

详细见 [`agent-design.md`](./agent-design.md) 和 [`api.md`](./api.md)。
