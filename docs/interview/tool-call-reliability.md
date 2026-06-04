# 如何保证 tool 被稳定执行 / 执行成功

> 1-page talking points for live interview · 答好的核心是把 "稳定" 拆成多层而非一层

---

## 0 · 30 秒开场（先建立维度）

> 这个问题答好的关键是先拆开 "稳定" 和 "成功"——它们是不同维度的问题。
>
> **稳定** = 系统在变化的环境（网络抖、API 限流、第三方挂）下还能跑得动。
> **成功** = 拿到的结果是真的，能被引用，不是 LLM 编的。
> **正确** = 在 prompt 决策层，LLM 选了正确的 tool 和正确的参数。
>
> 三个维度都要扛，而且最常被新人漏掉的是第三层——**HTTP 200 不等于 tool succeeded**。

---

## 1 · Failure 实际发生在哪 5 层（不是一层）

| 层 | 长什么样 | 谁的锅 |
|---|---|---|
| **LLM 决策** | 该调不调 / 调错 tool / 参数错 (symbol="苹果")/ 死循环 | prompt + model |
| **协议** | tool schema 跟 LLM 输出对不上；JSON 解析失败；tool_use_id 串错 | adapter |
| **执行** | 网络抖 / 429 / API 欠费 / 第三方挂 / schema 突变 | infra |
| **数据** | 200 OK 但 body 空；返回 NaN / 异常值 / 旧数据 | data quality |
| **状态** | 超时但实际成功（duplicate write）；并发改同一资源 | concurrency |

只答其中一层（最常见：第 3 层）= partial credit。

---

## 2 · 三个相互独立的保险（按优先级讲）

### A. **Observability — 失败时知道怎么坏的**（最优先）

- 每次 tool call 都 emit 结构化事件（`tool_call_id` / `name` / `args` / `latency` / `ok` / `error_class`）
- 错误分类：retryable / permanent / cost / quota — 不同类型不同处理
- LLM 看到的 tool_result 跟监控记的必须一致（不能给 LLM 看好数据但日志写错误）
- **金句**：「failure 不可怕，silent failure 才可怕」

### B. **Resilience — 失败时能继续**

- **Retry + backoff**：只对 idempotent tool（读）；非幂等（下单、发邮件）绝对不能重试
- **Circuit breaker**：同 provider 连续 N 次 fail → 跳过一段时间
- **Fallback chain**：主源 → 备源 → mock（uteki 是 `yfinance → FMP → mock`）
- **Graceful degradation**：返回 `ok=False` 而非抛异常，让 LLM 自己决策 plan B
- **金句**：「tool 是 best-effort，harness 必须 always-on」

### C. **Verification — 成功时知道真的成了**（最容易漏）

HTTP 200 ≠ tool succeeded。三道验证：

- **Schema validation**：tool_result 出 registry 前过 Pydantic
- **Semantic validation**：股价为负？revenue=0？该报告里没有这个 ticker？
- **Source attribution**：每个数字回溯到 tool_result 的具体 field
- **金句**：「tool 的成功 = output 可被引用、可被验证」

---

## 3 · 一句话哲学（埋这句进答案里）

> "We **lift errors into the protocol** rather than raise exceptions."
>
> 意思：tool 失败不抛异常，而是返回 `ToolResult(ok=False, error=...)`。
> 异常会 crash harness；`ok=False` 让上层（LLM / harness）**看见失败、显式决策**。
> 这是 senior 跟 mid 的关键区别——你把错误当 signal，不当 emergency。

---

## 4 · 强限制 vs 弱限制（这是 architecture maturity 的核心 signal）

新人会把所有规则都塞 prompt；naive 工程师会把所有规则都塞代码。
**Senior 知道分清楚**：

| | 强限制 (Hard) | 弱限制 (Soft) |
|---|---|---|
| **本质** | 结构上不可能违反 | 鼓励 / 要求，但模型可绕开 |
| **生效层** | 调度 / 协议 / 代码 | Prompt / 训练数据 / 评分 |
| **违反后果** | 物理上做不到 | 监控告警，事后纠正 |
| **修复方式** | 改代码 | 改 prompt / 加 eval case |
| **LLM 可绕过？** | ❌ 不能 | ✅ 能 |
| **Trust** | 不信任 LLM | 信任 LLM（带验证） |

**金句**：「**强限制是 architecture，弱限制是 culture。**」

### 4.1 uteki 的强限制（代码物理实现）

| 限制 | 在哪 |
|---|---|
| `max_tool_calls=30` / `wall_time=120s` / `max_cost_usd=0.5` | `harness.py:43-62` |
| `risk_level == "high"` 物理阻挡，根本不调 `tool.run()` | `harness.py:485` |
| 跨用户读 artifact 返 `FileNotFoundError` | `artifacts/store.py` 路径分区 |
| Tool schema validation | Pydantic `ToolResult` |
| Skill 不能直接调 tool — 只能 yield event | `BaseAgent` 不持有 registry |
| `tool_call_id` 配对 | `llm/client.py:166-176` |
| Timeout / Exception → `ok=False` | `harness.py:488-503` |

### 4.2 uteki 的弱限制（prompt + evaluator）

| 限制 | 在哪 |
|---|---|
| 数字必须 cite `[src:N]` | `guardrails.md` Rule 2 |
| `tool_call` 前先 yield `thinking` | `guardrails.md` Rule 6 |
| Artifact 不能含"过程话" | `guardrails.md` Rule 5a |
| 该用 tool 时不要凭记忆 | `guardrails.md` Rule 1 |
| 工具选择优先级（financials > web_search） | `guardrails.md` 1a 表 |

### 4.3 怎么判定一条规则该走强还是弱（送分判定题）

> **会造成不可逆损失 / 安全 / cost 失控 / 法律风险 → 强限制。
> 只是质量 / 风格 / 偏好 → 弱限制。**

| 例子 | 答案 |
|---|---|
| "下单前必须 owner approval" | **强**（金钱不可逆） |
| "回答尽量用中文" | **弱**（风格） |
| "max cost per run $1" | **强**（cost 失控） |
| "不能调用 high-risk tool" | **强**（uteki 已做） |
| "每条 numerical claim 要有 [src:N]" | **弱**（uteki 现状，靠 evaluator 后置审计） |
| "优先 financials 而非 web_search 拿财务" | **弱**（质量偏好） |

### 4.4 进阶 — 强弱限制会随时间迁移

一条限制初期是弱（prompt 教），跑一阵发现 LLM 经常违反、且违反代价大 → 升级为强。

uteki 真实迁移案例：
- `report_analysis` 参数：起初 prompt 提醒（弱）→ 后来加 Pydantic input validator（强）
- `max_cost_usd` 上限：起初没有 → real-LLM 跑 pipeline 偶尔失控 → 加进 HarnessLimits（强）
- `thinking` event 现在是弱；如果 evaluator 持续 catch 到「无 thinking → 质量下降」相关性 → 未来可能 self-evolution propose 升级为强

**Senior 系统设计** = 知道哪些必须 day 1 强制、哪些先 soft、等数据说话再 harden。
- Over-engineering = 全设成强（系统死板，加 case 困难）
- Naive = 全设成弱（系统失控，不可预测）

### 4.5 一句话收尾（如果面试官追问）

> 「架构上**让正确事情容易做、错误事情做不到**，是强限制。
> 剩下的靠 **prompt + evaluator 的反馈环纠偏**，是弱限制。
> 关键是判断**什么必须 hard-enforced**：cost / safety / 不可逆操作走强，
> 其他都先走弱、被 evaluator catch 到再 graduate 成强。」

---

## 5 · uteki 真实代码引用（被追问时直接报）

### A. ToolResult 协议把错误抬到 protocol
`services/api/src/uteki_api/tools/base.py:21-26`
```python
class ToolResult(BaseModel):
    ok: bool = True                  # 失败信号
    summary: str = ""                # LLM 可读的摘要
    data: dict[str, Any] = ...
    error: str | None = None         # 失败原因（非异常）
    sources: list[dict[str, Any]]    # 引用 SSOT
```

### B. Harness 6 道硬上限，防 LLM 死循环 / 烧钱
`services/api/src/uteki_api/agents/harness.py:43-62`
```python
class HarnessLimits:
    max_steps: int = 20
    max_tool_calls: int = 30        # 调用次数上限
    wall_time_seconds: float = 120  # 总时长
    max_input_tokens: int = 200_000
    max_output_tokens: int = 8192
    max_cost_usd: float = 0.50
```
超 → harness emit `error event`，run 结束，状态 `final_status=error`。LLM 不能"无限请求第三方"。

### C. Fallback chain — graceful degrade，不 crash
`services/api/src/uteki_api/tools/market_quote.py:173-180`
```python
if settings.use_mock_data:
    return _mock_result()           # E2E 走 mock，零成本
for fetcher in (_yfinance_quote, _fmp_quote):
    try:
        result = await fetcher(symbol)
        if result:
            return _build_real(result)
    except Exception as e:           # noqa: BLE001 — provider 失败必降级
        last_error = str(e)
return _mock_result(note=f"degraded: {last_error}")   # 最后兜底 mock
```

### D. Source attribution — 把"成功"绑死在可验证的引用上
`services/api/src/uteki_api/agents/sources.py:SourceCatalog`
+ `services/api/src/uteki_api/skills/_shared/guardrails.md` 强制：
```
每个 numerical claim 必须 [src:N]
N 必须指向 tool_result 的具体 field
否则 evaluator 自动标 [UNSOURCED]
```
**Structural guarantee, not a habit**——LLM 想编都没地方编。

### E. Harness 拦事件，tool 不被 skill 直接调
`services/api/src/uteki_api/agents/harness.py:267-269`
```python
if event.type == "tool_call":
    tool_count += 1
    if tool_count > self.limits.max_tool_calls:
        yield AgentEvent(type="error", data={"reason": "max_tool_calls_exceeded"})
        return
```
**Skill 只能 yield 事件**，harness 负责真调用 + 记账 + 限额。架构上把 tool 调用收敛到单一边界。

---

## 6 · 怎么测稳定执行率（被追问就答这套）

| 测试层 | uteki 做法 | 频率 |
|---|---|---|
| **Hermetic E2E** | 14 条 chain test，全部 mock LLM + mock tool，验 tool_call → tool_result event 完整 | 每个 PR |
| **Tool-level unit** | 每个 tool stub httpx，验真实 HTML/JSON 解析 + 错误降级 | 每个 PR |
| **Real-LLM smoke** | `UTEKI_USE_MOCK_LLM=false` 跑 NVDA 7-gate，真 API 真工具 | 发版前 + 每周 |
| **Per-tool success rate** | 24h 窗口 `ok=True / total`，跌破阈值告警 | prod（未做） |
| **Eval-as-canary** | drift_monitor 跑 fixed eval suite，pass_rate 跌 >10pp → 自动开 proposal | 每天 |

---

## 7 · uteki 现状的诚实自评（被追问 gap 时讲）

| 防御 | 状态 | 备注 |
|---|---|---|
| 结构化 event | ✅ | harness 强制 |
| ok=False 不 crash | ✅ | ToolResult 协议 |
| Fallback chain | ✅ | 每个 tool 内置 |
| Schema validation | ✅ | Pydantic + JSONSchema 双格式 |
| Source attribution | ✅ | SourceCatalog + guardrails |
| 预算上限 | ✅ | HarnessLimits 6 维 |
| Circuit breaker | ⚠️ 未做 | per-provider，prod hardening 时加 |
| Retry with backoff | ⚠️ 部分 | httpx 有 timeout，没系统级 retry policy |
| Numerical sanity | ⚠️ 未做 | 信 yfinance，曾被空 DataFrame 坑过（C.1 修） |
| Idempotency / dedup | N/A | 暂时全是 read-only tool；加 write tool 必做 |
| Cost / quota active throttle | ⚠️ | 记账但不主动停（C.4 跳过了） |

**坦诚说"未做"**比假装"全 cover"加分——senior 知道 prod hardening 是渐进的。

---

## 8 · 千万别说的 trap 答案

❌ "我们加了 try/except，捕获所有异常，记日志"

暴露问题：
- 不知道**有些异常应该传播**（让 LLM 看见错误才能换策略）
- 不知道 try/except **抓不到语义错误**（200 OK + 空 body）
- 不知道**有些重试有害**（非幂等 / cost-bearing tool 重试 = 重复扣钱）

正确说法：**"we lift errors into the protocol"**。

---

## 9 · 一分钟收尾（如果让你 wrap up）

> 这道题答好的关键是别只盯 tool 本身。围绕 tool 的 **LLM 决策**、**harness 边界**、**observability**、**evaluation**——是同一个问题的不同侧面。
>
> 我们的设计哲学是：
> - **Tool = best-effort 函数**（可能失败，可能慢）
> - **Harness = reliability 边界**（retry / budget / observability 都在这）
> - **Skill = intent 表达**（yield 事件，不直接调）
> - **Evaluator = continuous verification**（drift monitor + LLM judge + eval suite）
>
> 这四层独立 + 协同，是 agent 从 demo 变成 production system 的 minimum bar。
