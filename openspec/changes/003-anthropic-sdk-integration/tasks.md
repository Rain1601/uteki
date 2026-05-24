# 003 · Tasks

## Phase 1 — SDK

- [x] **T1.1** 加依赖 `anthropic >= 0.45` → 装到 0.102.0
- [x] **T1.2** `.env.example` 加 `ANTHROPIC_API_KEY` / `ANTHROPIC_BASE_URL` / `OPENROUTER_API_KEY` / `AIHUBMIX_API_KEY` / `UTEKI_DEFAULT_MODEL`
- [x] **T1.3** `core/config.py` 加 anthropic / openrouter / aihubmix / default_model 字段，沿用各家**约定**变量名

## Phase 2 — Client

- [x] **T2.1** `llm/anthropic_client.py` — AsyncAnthropic 封装，`stream_chat(messages) -> AsyncIterator[str | UsageDelta]`，system prompt 默认 `cache_control: ephemeral`
- [x] **T2.2** `tools/base.py` 加 `to_anthropic_spec()` + `ToolRegistry.anthropic_specs()`
- [ ] **T2.3** stream tool_use 翻译 → 移交 change 004（本 change 仅文本流，保持 scope 小）

## Phase 3 — Router 接入

- [x] **T3.1** `llm/router.py` 加 `anthropic` 分支，返回 AnthropicClient；其他 provider 注册表化
- [x] **T3.2** 4 个 skill 默认 model 全切到 `anthropic/claude-sonnet-4-6`
- [x] **T3.3** ANTHROPIC_API_KEY 未配 → fallback 到 `openrouter/anthropic/...`，log warn（已验证）

## Phase 4 — Harness 接 usage / cost

- [x] **T4.1** harness 累计 `usage` event 的 4 项 token 数
- [x] **T4.2** `HarnessLimits` 加 `max_input_tokens=200_000` / `max_output_tokens=8_192` / `max_cost_usd=1.0`
- [x] **T4.3** 超阈值 → emit error + status=error；reason 含具体 metric 名
- [x] **T4.4** `Run.usage_summary: UsageSummary`（含 cost_usd）；harness 在 `finish()` 前回写

## Phase 5 — 验证

- [x] **T5.1** uv sync + ruff 全过；模块级 smoke（router fallback / tool spec / Run 字段 / HarnessLimits）通过
- [x] **T5.2** 端到端跑一次 mock chat：26 events、status=ok、usage_summary={120, 480, 0, 0, cost_usd=0.00756} —— cost 计算正确
- [ ] **T5.3** 真 ANTHROPIC_API_KEY 端到端 —— 待用户配 key 后验
- [ ] **T5.4** 缓存命中验证（连续两次相同 prompt，input_tokens 大幅下降）—— 待 T5.3 后

## Phase 6 — Spec

- [x] **T6.1** `openspec/specs/llm-routing/spec.md`
- [x] **T6.2** `openspec/specs/harness/spec.md`（含 budget guard 章节、cost pricing 表、不变量、不属于本 spec 的项）

## 阻塞与 follow-up

- **本 change 不含真实 tool_use 循环**：当前路径下，skill 走 mock 模式 yield tool_call，真 Claude 路径只做文本流（绕过 tools）。完整 tool_use 由后续 change 004 引入。
- 实际验证真模型需要 `ANTHROPIC_API_KEY`（或 `OPENROUTER_API_KEY` 走 fallback）。
