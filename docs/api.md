# uteki API

完整、可交互的 OpenAPI 文档：启动 api 后访问 `http://localhost:8000/docs`。本文档是简版速查。

## 通用约定

- Base URL：`http://localhost:8000`
- 所有请求体：`application/json`
- 流式响应（SSE）：`text/event-stream`，帧格式 `data: <JSON>\n\n`
- 错误：FastAPI 标准 `{detail: ...}`

## 健康检查

| Method | Path | 说明 |
|---|---|---|
| GET | `/health` | `{status: "ok"}` |

## 对话（SSE）

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/agent/chat` | 流式 AgentEvent |

Body:
```json
{
  "messages": [{"role": "user", "content": "分析宁德时代"}],
  "session_id": "optional",
  "agent": "research",
  "model": "openrouter/anthropic/claude-sonnet-4-6"
}
```

响应：SSE 帧，`data:` 部分是 `AgentEvent` JSON。事件类型见 `docs/agent-design.md` §1。

## 技能（skill）

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/agents` | 列出所有 skill + 当前版本 |
| GET | `/api/agents/{name}` | skill 详情 |
| GET | `/api/agents/{name}/versions` | skill 版本历史 |
| GET | `/api/agents/{name}/versions/{version}` | 单版本（含 changelog） |

## 执行记录（runs）

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/runs?skill=&triggered_by=&limit=50` | 列表（不含事件） |
| GET | `/api/runs/{run_id}` | 完整 Run（含事件流） |
| GET | `/api/runs/{run_id}/events` | 仅事件流 |

## 横向对比

| Method | Path | 说明 |
|---|---|---|
| POST | `/api/compare/run` | 并行跑多 agent，返回 `run_ids` |
| POST | `/api/compare/diff` | 结构化对比 `run_ids` |

Compare run body:
```json
{
  "messages": [{"role":"user","content":"看下 300750"}],
  "agents": ["research","qna"],
  "model": null
}
```

## 评测

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/eval/cases` | 列出 case |
| POST | `/api/eval/run` | 跑所有 case，返回 EvalReport |

## 触发器

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/triggers` | 列出 cron + event triggers |
| POST | `/api/triggers/event` | 外部 webhook 入口 `{topic, payload}` |
