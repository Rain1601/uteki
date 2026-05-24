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
