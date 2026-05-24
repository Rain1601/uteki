# 005 · Artifact 持久化层 + await_review checkpoint

## Problem

Anthropic 文章观察："Communication was handled via files: one agent would write a file, another agent would read it and respond either within that file or with a new file."

uteki 当前所有产出（plan / draft / 评测报告）只活在 `AgentEvent` 事件流里。当 006 引入 planner/generator/evaluator 多 skill 分工时，没有"传文件"的脊梁 —— 而这是稳定 multi-skill 编排的前提。

另外，`_shared/guardrails.md` 里写了"stop and surface for review"，但 harness 没实装 await_review 机制。研究类任务在 compliance 场景下需要人工审核后才能继续。

## Solution

引入 **Artifact 层**：一条 run 关联一组命名的、结构化的文件型产出。新增两个 AgentEvent 类型：`artifact_written` / `await_review`，分别对应"产出 artifact"和"请求审核"。

```
runs/<run_id>/artifacts/
├── plan.md                     # planner 产出
├── sprint-1-contract.json      # generator + evaluator 协商
├── draft-research-brief.md     # generator 产出
├── eval-report.json            # evaluator 产出
└── checkpoint-await-review.json # 用户审核请求
```

skill 通过 `self.artifacts.write(name, content, kind="markdown")` / `.read(name)` 操作；harness 注入 `ArtifactStore` 实例（run-scoped）。

await_review event 让前端按 trigger 类型决定行为：
- `user` 触发：弹"待审核"条 + 提供"继续 / 拒绝 / 备注"按钮
- `cron` / `event` 触发：自动通过 + 写入 `run.tags=["auto-approved"]`

## Non-goals

- **不**实装真审批工作流（multi-stakeholder / 角色权限）—— 留 M4 多租户之后
- **不**做 artifact 版本控制 / diff（artifact 现版即覆盖；run 自己天然就是版本）
- **不**做 artifact 上传 / 用户挂载文件（只是 skill 产出）
- **不**改 run_store 字段（artifacts 是独立 store + run.id 关联）

## 依赖

无。是 006 的前置（006 完全依赖 artifact 通信）。

## Risks

- **磁盘容量**：每条 run 几个 markdown 不大；但 long-running 累积下会有量。M5+ 加 retention policy（默认 30 天）
- **并发写**：同一 run 内 artifact 是 skill 串行写，无并发
- **跨容器 / 分布式**：当前 LocalFileStore；多实例部署需切到 S3。接口已隔离
