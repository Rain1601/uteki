# uteki

> 投研智能体（agent） — 让对话替你读财报、看行情、出研报。

支持三端：

- **Web** — Next.js 16 + React 19 + TypeScript
- **iOS** — 待选型（占位中）
- **Android** — 待选型（占位中）

后端统一由 **FastAPI (Python 3.13)** 承担 LLM 推理、工具调用与数据接入；三端只负责 UI 与流式渲染。

## 目录结构

```
uteki/
├── apps/
│   ├── web/                # Next.js（已可运行）
│   ├── ios/                # 占位
│   └── android/            # 占位
├── services/
│   └── api/                # FastAPI + uv
├── packages/
│   ├── shared-types/       # 由 OpenAPI 生成的 TS 类型
│   └── ui/                 # 未来共享 React 组件
├── docs/                   # 架构与 API 文档
├── scripts/                # dev / gen-types 等脚本
└── Makefile                # 统一命令入口
```

## 快速开始

前置：Node ≥ 22、pnpm ≥ 9、Python 3.13、[uv](https://docs.astral.sh/uv/)。

```bash
# 1. 安装所有依赖（node + python）
make setup

# 2. 同时启动 web (3000) 与 api (8000)
make dev

# 3. 访问
open http://localhost:3000/agent      # 对话页
open http://localhost:8000/docs       # FastAPI Swagger
```

## 端到端验证

```bash
# 后端健康
curl http://localhost:8000/health

# 流式对话（SSE）
curl -N -X POST http://localhost:8000/api/agent/chat \
  -H 'Content-Type: application/json' \
  -d '{"messages":[{"role":"user","content":"分析一下宁德时代"}]}'
```

## 进阶

- 生成前端共享类型：`make types`（api 须先启动）
- 仅启 web：`make web` / 仅启 api：`make api`
- 详细架构与 API：见 [`docs/architecture.md`](docs/architecture.md) 和 [`docs/api.md`](docs/api.md)
- 设计文档（跨能力愿景、CC 互操作等）：[`design/`](design/)

## Claude Code 接入（MCP）

把 uteki 的 skill 注入 Claude Code 的工具集，让 CC 自然语言驱动研究流水线。
设计说明：[`design/03-mcp-vs-local.md`](design/03-mcp-vs-local.md)。

```bash
# 1. 后端以匿名模式启动（MCP MVP 暂走 demo@local 兜底）
cd services/api
UTEKI_AUTH_REQUIRED=false uv run uvicorn uteki_api.main:app --port 8000 &

# 2. 把 MCP server 注册到 CC（一次性）
claude mcp add uteki -- /absolute/path/to/uteki/scripts/uteki-mcp.sh

# 3. 验证
claude mcp list                       # 应该看到 uteki
```

之后任意 CC 会话里，自然语言提问 uteki 就会被自动调用：

```
> 用 uteki 跑一份半导体设备板块的研究框架，然后帮我审一下
```

CC 会自动调用 `uteki_run_skill` → 轮询 `uteki_get_run` → 读取 artifacts → 给出评审。
