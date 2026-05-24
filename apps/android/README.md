# uteki Android

技术栈尚未确定（候选：Kotlin + Jetpack Compose 原生 / React Native + Expo）。本目录暂为占位，骨架阶段不引入 Gradle 工程，避免选型变更后的清理成本。

## 与后端的对接约定

- API 基址：`http://<host>:8000`
- 主要端点：
  - `POST /api/agent/chat` — 对话流（Server-Sent Events）
  - `GET /api/agents` — 可用 skill 列表
  - `GET /api/runs` — 历史执行记录
- 事件协议见 `services/api/src/uteki_api/schemas/events.py` 的 `AgentEvent`。
- 流式响应：`data: <AgentEvent JSON>\n\n`；客户端按 `event.type` 渲染。

## 落地计划

1. 选型（Compose vs RN）：与 iOS 同步决策；如果选 RN，则与 iOS 共用一份 RN 工程放在 `apps/mobile/`。
2. 最小可用版本：登录 → skill 选择 → 对话页（Trace + Message）。
3. 后续：runs 历史、FCM 推送（cron/event 触发时下发）。
