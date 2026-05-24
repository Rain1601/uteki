# LLM Routing — spec

> 最新更新：2026-05-19 · 引入自 change 003-anthropic-sdk-integration

## 目的

skill 不直接选 LLM provider。一个模型 id 字符串 → router 解析 → 配好的 client。skill 只在乎"client 能不能跑"，不在乎下面是哪家。

## Model id 协议

```
<provider>/<upstream_model_id>
```

| 前缀 | Client | 含义 |
|---|---|---|
| `anthropic/` | `AnthropicClient` | 直连 Anthropic Messages API，享 prompt caching |
| `openrouter/` | `LLMClient` (OpenAI-compat) | base_url = `https://openrouter.ai/api/v1` |
| `aihubmix/` | `LLMClient` (OpenAI-compat) | base_url = `https://aihubmix.com/v1` |
| _(无前缀)_ | `LLMClient` | 走 legacy `UTEKI_LLM_BASE_URL` 配置 |

例：
```
anthropic/claude-sonnet-4-6                    → Anthropic 原生
openrouter/anthropic/claude-sonnet-4-6         → OpenRouter 中转
openrouter/openai/gpt-4o-mini                  → OpenRouter 走 OpenAI
aihubmix/deepseek-chat                         → AiHubMix
gpt-4o-mini                                    → legacy LLMClient
```

## Client 接口（隐式契约）

所有 router 返回的 client 必须有：

```python
@property
def configured(self) -> bool: ...
async def stream_chat(messages: list[ChatMessage]) -> AsyncIterator[str | UsageDelta]: ...
```

- `configured` 表示 API key 已配。skill 用这个决定走真实路径 vs mock
- `stream_chat` 屈是异步生成器，**主要** yield `str`（文本增量）；可选 yield `UsageDelta` 上报 token 用量
- 调用方不关心哪些 chunk 是哪种 —— 用 `isinstance(chunk, str)` 区分即可

## Fallback 规则

router 用宽松降级：

1. 请求 `anthropic/X` 但 `ANTHROPIC_API_KEY` 没配 → fallback 到 `openrouter/anthropic/X`（OpenRouter 也镜像 anthropic 模型）
2. 未知前缀 → 当作 legacy bare model id 处理
3. 最终 client 仍 `configured == False` → skill 自然走 mock 路径

→ **永不抛错**。配置缺失是常态，不应该让请求失败。

## Provider 注册表

```python
OPENAI_COMPAT_PROVIDERS = {
    "openrouter": (base_url="...", api_key_attr="openrouter_api_key"),
    "aihubmix":   (base_url="...", api_key_attr="aihubmix_api_key"),
}
ANTHROPIC_PROVIDER = "anthropic"  # 独立路径
```

新增 provider：

- 若它讲 OpenAI 协议 → 加进 `OPENAI_COMPAT_PROVIDERS`
- 若它有独家特性（caching / native tool use / 特殊 schema） → 单独 client + router 分支

## Prompt caching（Anthropic 独家）

`AnthropicClient` 默认把 system prompt 整块打 `cache_control: ephemeral` 标记：

```python
system=[{"type": "text", "text": prompt, "cache_control": {"type": "ephemeral"}}]
```

→ 同 prompt 在 5 分钟内重发，input_tokens 走 cache_read（单价 1/10）。

对长 SKILL.md（10k+ tokens）一天跑几十次，成本差 10x。

OpenAI-compat 路径无此特性，是切回 `anthropic/` 前缀的核心理由。

## Env vars

```
ANTHROPIC_API_KEY=
ANTHROPIC_BASE_URL=          # 可选，走代理
OPENROUTER_API_KEY=
AIHUBMIX_API_KEY=

UTEKI_DEFAULT_MODEL=anthropic/claude-sonnet-4-6
UTEKI_LLM_BASE_URL=          # legacy bare-id fallback
UTEKI_LLM_API_KEY=
UTEKI_LLM_MODEL=gpt-4o-mini
```

## 不属于本 spec

- Cost-aware 路由（按 step 重要度选 cheap/strong 模型）—— 留 follow-up
- 多 provider 自动 failover（HTTP 5xx 时自动跳到下一家）—— 留 follow-up
- Anthropic 原生 tool_use 控制流（开启后 client 自己跑 tool loop）—— change 004
