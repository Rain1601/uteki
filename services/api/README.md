# uteki-api

FastAPI 后端 — uteki 投研智能体的 LLM 推理、工具调用与数据接入层。

## 开发

```bash
cd services/api
uv sync                 # 安装依赖
cp .env.example .env    # 按需填 LLM key（不填则走 mock 流式响应）
uv run uvicorn uteki_api.main:app --reload --port 8000
```

打开：
- http://localhost:8000/health
- http://localhost:8000/docs（Swagger UI）

## 目录

```
src/uteki_api/
├── main.py             # FastAPI 应用、CORS、路由挂载
├── core/
│   ├── config.py       # pydantic-settings
│   └── logging.py
├── api/
│   ├── health.py       # GET /health
│   └── agent.py        # POST /api/agent/chat（SSE）
├── agents/
│   ├── base.py
│   └── research.py     # 投研 agent（默认 mock 流式输出）
├── llm/
│   └── client.py       # LLM 客户端（OpenAI 兼容）
├── tools/              # 行情、财报等工具（待填充）
└── schemas/
    └── chat.py         # ChatRequest / ChatChunk
```

## 测试

```bash
uv run pytest
uv run ruff check .
```
