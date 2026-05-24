# 003 · 接入真实 Claude API

## Problem

`llm/client.py` 现在按 OpenAI 协议写，配置上虽然支持 OpenRouter / AiHubMix，但没有走 Anthropic 原生 SDK。结果：

- **拿不到 prompt caching 折扣** —— 引入 financial-services skill 后系统 prompt 会膨胀到 10k+ token，没缓存成本翻 10 倍
- **tool_use 协议有适配损耗** —— OpenAI tool 格式与 Anthropic tool_use block 转换有 corner case
- **拿不到 Anthropic 独有特性** —— extended thinking、PDF input、computer use 等

## Solution

加 `llm/anthropic_client.py`，与现有 `llm/client.py`（OpenAI 兼容）并存。`ModelRouter` 按模型 id 前缀分发：

```
anthropic/claude-sonnet-4-6      → AnthropicClient（原生）
openrouter/anthropic/...         → LLMClient（OpenAI-compat over OpenRouter）
aihubmix/...                     → LLMClient（OpenAI-compat over AiHubMix）
```

skill 默认 model 切到 `anthropic/claude-sonnet-4-6`，环境变量未配 ANTHROPIC_API_KEY 时自动降级 OpenRouter。

### 关键设计点

1. **prompt caching**：system prompt（含 SKILL.md）打 `cache_control: ephemeral` 标记
2. **tool_use 原生**：tool spec 用 `to_anthropic_spec()`；tool_result 用 anthropic content block 格式
3. **流式 → AgentEvent**：把 anthropic 的 stream event（`content_block_start` / `content_block_delta` / `message_delta` / `message_stop`）翻译成 `AgentEvent`
4. **usage 上报**：每次 `message_delta` 携带 usage → emit `usage` event（含 input / output / cache_read / cache_creation tokens）

## Non-goals

- **不**实装 extended thinking（先简单跑通）
- **不**实装 batch API
- **不**实装 computer use
- **不**做多 provider fallback chain（router 暂时硬路由）

## 依赖

- 推荐与 002 同时做（financial-services skill 没真 Claude 跑发挥不出来）
- 不依赖 001

## Risks

- **成本**：金融研究 prompt 长，一次 run 可能 0.05–0.20 美元。需要在 harness 加 `max_cost_usd` 守卫
- **token 计数**：anthropic 不返回 OpenAI 风格的 prompt_tokens，需要单独处理 usage event
- **网络**：直连 anthropic.com 国内不稳定。dev 可走 OpenRouter；prod 看部署位置
