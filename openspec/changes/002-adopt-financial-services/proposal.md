# 002 · 引入 anthropics/financial-services 的金融研究能力

## Problem

uteki 当前 4 个 skill（research / recap / screener / qna）是 mock —— prompt 写死在 Python 字符串里，输出无结构、无 cite、无审核 checkpoint，离"分析师可用"差一大截。

Anthropic 官方在 [anthropics/financial-services](https://github.com/anthropics/financial-services) 开源了 10 个产投研工作流（Pitch / Market Researcher / Earnings Reviewer / Model Builder / GL Reconciler / KYC Screener / …），每个都是分析师级别的 SKILL.md，含数据源优先级、审核 checkpoint、cite-or-flag 等业界规约。**Apache-2.0**，允许商用 + 修改。

## Solution

把它的**内容**（SKILL.md / 子技能 markdown）搬进 uteki，**不**搬它的 runtime（Cowork plugin / Managed Agents YAML）。

我们的 harness 已具备：tool 调度、事件协议、版本绑定、run 持久化。它的 SKILL.md 装载为 system prompt + 引用文件，由 uteki harness 跑。

### 第一批引入的 3 个 skill

| uteki skill name | 来源 | 用途 |
|---|---|---|
| `research` | market-researcher | 行业 / 主题研究框架，五段产出 |
| `earnings` | earnings-reviewer | 财报 + 电话会 → 模型更新 → 笔记草稿 |
| `comps` | vertical-plugins/equity-research/skills/comps | 可比公司估值表 |

后续按用户需求加 `model-builder` / `pitch-agent` 等。

### 保留 vs 丢弃

| 资产 | 处置 |
|---|---|
| `agents/*.md`（主 prompt） | → `services/api/src/uteki_api/skills/<name>/SKILL.md` |
| `skills/<sub>/SKILL.md`（子技能） | → `services/api/src/uteki_api/skills/<name>/references/<sub>.md` |
| `plugin.json` | 丢 |
| `agent.yaml` / `managed-agent-cookbooks/` | 仅作子技能拆分的参考，不直接用 |
| `scripts/orchestrate.py` 等 | 丢，uteki harness 取代 |

### License 合规

- 在 uteki 根目录加 `THIRD_PARTY_NOTICES.md`，列出引入的文件 + 源 commit hash + Apache-2.0 链接
- 每个 fork 进来的 markdown 文件头部加：
  ```
  <!-- Adapted from anthropics/financial-services@<sha> · Apache-2.0 -->
  <!-- Modifications: <date> · adapted for uteki harness runtime -->
  ```

## Non-goals

- **不**直接接 Cowork / Managed Agents API（我们有自己的 harness）
- **不**引入它的 MCP 数据连接器（CapIQ / FactSet），uteki 用 mock tool；真实数据接入是另一个 change
- **不**引入 Excel / PowerPoint 输出（pptx-author 等），uteki 现阶段只产文本 + 图表

## 依赖

- 推荐先做 **003-anthropic-sdk-integration**（真 Claude 才能让这些 prompt 发挥作用），否则 mock LLM 无视 system prompt
- 不强依赖 **001-tenant-and-auth**，可并行

## Risks

- **prompt 长度膨胀**：Market Researcher 的 SKILL.md + references 加起来可能 8–15k token。需要 prompt caching（Anthropic SDK 默认支持），否则成本爆炸
- **预期工具不存在**：原文档假设有 CapIQ MCP，uteki 现在只有 mock `kline` / `financials`。skill 内必须能识别并降级（"如果 MCP 不可用，明确告知用户数据来自 mock"）
- **审核 checkpoint 强度**：原 skill 频繁要求 "stop and surface for review"，前端要支持暂停 + 用户确认；harness 需要新增 `await_review` event 类型
