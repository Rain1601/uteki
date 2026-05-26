# design/ — 设计文档索引

跨能力的设计探索与提案，区别于 `openspec/` 的契约文档：

| 目录 | 性质 | 例子 |
|---|---|---|
| `openspec/specs/<capability>/spec.md` | "这个能力现在做什么" — 契约 | `auth/spec.md`, `harness/spec.md` |
| `openspec/changes/<NNN>-...` | "对某个能力的具体修改提案" | `001-tenant-and-auth/` |
| `design/` | **跨能力的设计**：愿景、平台级方向探索、不专属于一个 capability 的提案 | 本目录 |

约定：

- **不**重复 `openspec/` 已经讲清楚的事，链接过去
- **不**写实现细节（那是 spec 的事），写"为什么这样设计 + 边界 + 失败模式"
- 单个文件应该能独立读懂，不假设读者读过别的文件

## 当前文档

| 文件 | 类型 | 一句话 |
|---|---|---|
| [`00-agent-platform.md`](./00-agent-platform.md) | 现状盘点 | 当前 agent 平台的分层、关键抽象、完成度、张力点 |
| [`01-claude-code-interop.md`](./01-claude-code-interop.md) | 设计空间探索 | uteki 与 Claude Code 互操作的 3 个方向 |
| [`02-self-evolution-loop.md`](./02-self-evolution-loop.md) | 详细提案 | 用 Claude Code 作为外部 reviewer 的 self-evolution 闭环 |
| [`03-mcp-vs-local.md`](./03-mcp-vs-local.md) | 认知澄清 | 为什么用 MCP 而不是 script/HTTP/直读——MCP 的价值在 CC 推理层，不在传输层 |
| [`04-mcp-real-smoke.md`](./04-mcp-real-smoke.md) | 验证手册 | MCP server 在真 claude CLI 下的 60 秒接入步骤 + 实测结果 + 已知陷阱 |
| [`05-roadmap-to-v1.md`](./05-roadmap-to-v1.md) | **路线图（live spec）** | 现在 → v1 终态的 5 phase 排程，每个 phase 带可见的"标靶 demo"。US-only 数据栈。**当前的工作总纲**。 |
| [`06-agent-flow-demo.md`](./06-agent-flow-demo.md) | **运行图谱** | 端到端 agent 流程：13 节点 single run + 7 节点 self-evolution loop + 4 个跨节点不变量 + 8 个关键设计决策（"为什么 X 不 Y"） |
| [`proposals-archive/`](./proposals-archive/) | 案例库 | self-evolution loop 的真实样本归档；自动化 proposal-store 落地前的人工演练记录 |

## 文档生命周期

写 → 讨论 → 形成共识 → **如果决定落地**：

1. 拆出对应 capability 的 change：在 `openspec/changes/<NNN>-name/` 起草 proposal.md
2. design 文档保留作为"这个想法是怎么来的"的历史记录
3. capability 改完后，对应的 `openspec/specs/<capability>/spec.md` 跟着更新

不是每个 design 文档都必然落地——有的会被否决，有的会演化成完全不同的东西。这些都是 design 的正常归宿。
