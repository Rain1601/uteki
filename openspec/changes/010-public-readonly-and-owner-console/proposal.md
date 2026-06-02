# 010 · 公开 read-only surface + owner console

## Problem

001 把 uteki 做成了**多租户私有 SaaS**——每个注册用户独立 workspace，所有数据互相隔离。但即将部署的产品形态完全不同：

- 这是 owner 的**研究展示产品**——结果与 trace 对外完全公开
- 操作（触发 agent、改配置、审批 proposal）**仅 owner 可做**
- 注册 / 多账号 / 跨用户隔离都用不到——产品只有**一个 owner，一个公开舞台**

001 的方向是反的（私有 SaaS），现在要变成**单 owner 公开展示 + 私有 console**。

同时浮现一个产品级新约束：**Agent prompt（SKILL.md / references / 7-gate persona 等）不能对外公开**——它是 owner 的"方法学护城河"。外人能看到 agent 的 trace、tool_call、artifact，但 prompt 是黑盒。这是 uteki 的产品定位：**transparent execution + protected methodology**。

## Solution

### 三件事并发

1. **路由 / chrome 拆两个 surface**（同一个 Next deployment，不是两个 repo）
   - `app/(public)/*` — anonymous read-only，bespoke chrome
   - `app/(console)/*` — owner-only，沿用现有 editorial app
   - URL：`uteki.com/` 公开 + `uteki.com/console/*` owner（路径式，单 Cloud Run service）

2. **数据层加 visibility（3 档枚举）+ owner allowlist**
   - `Run.visibility ∈ {private, unlisted, public}`，默认 `private`
   - OAuth 鉴权回调校验 `email in OWNER_EMAILS` / `github_login in OWNER_GITHUB_LOGINS`，非 allowlist → 不发 token
   - 删 `/api/auth/register`（不再多租户，不需要注册）
   - 所有现有 GET route 改成 `optional_user`（匿名 OK，过滤只看 public），所有 mutation route 改成 `require_owner`

3. **Prompt 物理隔离**
   - API 序列化层：非 owner 请求时，`SkillVersion.prompt` 永远返回空串（只返 stats: lines/bytes/updated_at）
   - 给 `SkillEntry` 加 `public_description` 字段——owner 写的方法学说明（技术准确：列工具、列流程，**不含 prompt 文字**）
   - `app/(public)/agents/[name]` 只渲染 `public_description`，物理上不 import `prompt` 字段
   - 同样脱敏 `Proposal.baseline_prompt` / `candidate_prompt` / A/B diff
   - Audit harness 不把 system_prompt 落到 event 持久化

### 关键 invariant

- **公开 surface 数据深度 = console 数据深度**（trace 完整、artifact 完整、tool_call 完整、cost 完整），**除了 prompt 是黑盒**
- 不做 "publish-as-essay" 的 curated 模型——读者看到的就是实时、真实的 run，不是事后整理的文章
- visibility 只控制「这条 run 是否对外」，prompt 脱敏是无条件的硬规则——两者正交

## Non-goals

- **不**实现多用户 / 团队 / 邀请——产品就一个 owner
- **不**做事后 publish / 编辑 essay 流程——公开就是实时直读
- **不**做 per-artifact visibility 覆写——artifact 继承父 run 的 visibility
- **不**做 fine-grained 字段级权限框架——prompt 脱敏是硬编码规则，不可配置
- **不**做 audit log（owner 单一写者，自己审自己没意义）
- **不**做 password 找回 / MFA / 邮箱验证（注册流程已删，OAuth 只对 owner）

## Dependencies

依赖：无功能性依赖；纯粹的权限模型 + UI 重构。

被依赖（后续 change 会用这个作底座）：
- 部署到 GCP Cloud Run / Cloud SQL（PR 5 范围）
- 未来 owner 接收外部 share / link preview 的 unlisted run 流程

## Risks

| 风险 | 处理 |
|---|---|
| 现有 demo / 测试 run 默认 private 但仍存在数据库 → 部署时不小心暴露 | 部署前清空 `data/`，全新 prod 起点 |
| Prompt 字段在 event stream 里漏出去（system message 被持久化） | PR 1 audit harness 持久化路径，确认 events 落盘只含 user/assistant turn |
| Pipeline 跑的 sub-skill 在共享 Run 里——如果未来重构成 child Run 模型，sub run 的 visibility 必须继承 parent | 当前单 Run 架构天然继承，未来若重构需在 harness 入口加 `propagate_visibility` hook |
| OAuth callback URL 切换：dev `http://localhost:3000` vs prod 真实域名 | 环境变量驱动；PR 5 部署时配 |
| `Run.visibility` 加索引后老数据库无字段——alembic backfill | 部署前清空 data，跳过 backfill 复杂度 |
| 单 owner allowlist 配错（typo 邮箱）→ 自己也登不进 | OAuth callback 在校验失败时 log 完整 identity 信息 + 给清晰错误页 |
| Owner 切 visibility 误操作（把私密 run 标 public） | 加 confirm 弹窗，bulk action 显示「will affect N runs」二次确认 |

## 改 vs 重做

考虑过完全重做（drop 001 的多租户表结构、重新设计单 owner schema）。但：

- 001 的 user_id 分区在内部依然有用（drift_monitor 用 `system` user 隔离平台级 eval；未来可能加 owner-shared `team` 用户）
- 重做 = 重写所有 store 接口 + 所有 migration + 所有 fixture
- **保留多租户 schema，硬编码 `OWNER.id` 为唯一 tenant** 是最小改动——schema 不变，runtime 行为变

所以本 change 是**改造**，不是重做。
