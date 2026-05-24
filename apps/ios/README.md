# uteki iOS

技术栈尚未确定（候选：SwiftUI 原生 / React Native + Expo）。本目录暂为占位，骨架阶段不引入 Xcode 工程，避免选型变更后的清理成本。

## 与后端的对接约定

- API 基址：`http://<host>:8000`
- 主要端点：
  - `POST /api/agent/chat` — 对话流（Server-Sent Events）
  - `GET /api/agents` — 可用 skill 列表
  - `GET /api/runs` — 历史执行记录
- 事件协议见 `services/api/src/uteki_api/schemas/events.py` 的 `AgentEvent`。
- 流式响应：`data: <AgentEvent JSON>\n\n`；客户端按 `event.type` 渲染。

## 落地计划

1. 选型（SwiftUI vs RN）：根据团队人力 + 是否需要与 Android 共享代码决定。
2. 最小可用版本：登录 → skill 选择 → 对话页（Trace + Message）。
3. 后续：runs 历史、推送通知（cron/event 触发时下发）。
