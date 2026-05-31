# `as_of` 串通到 harness/tool — 1.5 天小任务

> 出处：[`../docs/M1-consistency-and-asof-todolist.md`](../docs/M1-consistency-and-asof-todolist.md)
> （uteki.open Claude 给 uteki Claude 的跨 repo 任务清单）中 Task 1-3 的精简实现版。
> 该文档另外提的 ConsistencyRunner（Task 4-10）暂缓 —— 等 design/05 M1.7（A/B 自动评估）
> 时再做，那时它正好是 A/B 评估的底座。
>
> 实施 owner：uteki repo 内的 agent（codex/Claude）。

## 1 · 为什么做

**问题**：现在 `SourceCatalog(as_of=...)` 已经能拒绝 `published_at > as_of` 的 DataPoint
（codex 上周 dd2482d 落地），但拒绝是发生在 **数据已经被 fetcher 拉回来之后**。
意味着：
- 浪费一次外部 API 调用 + 网络往返。
- 拒绝只在登记到 catalog 时生效；tool 直接返回给 LLM 的 `data` payload 里
  依然包含未来数据，LLM 会把它写进 final_text，然后只是 catalog 里没 source 撑腰。

**目标**：在 fetcher 层就按 `as_of` 切片，从源头不放未来数据进来。

**适用场景**：回测（"如果 2024-01-01 那天做这个决策"）、复现历史 run、
M1.7 A/B 评估（同一时间窗下对比新旧 skill）。

## 2 · 验收

1. `AgentHarness(as_of=date(2024, 1, 1))` 后，所有 tool 返回的 `data` 和 `sources` 里
   都不出现 `published_at > 2024-01-01` 的条目。
2. `POST /api/agent/chat` body 接 `as_of: "2024-01-01"`（可选），透传到 harness。
3. 不传 `as_of` 时所有行为不变（向后兼容，现有 32 个 E2E 全过）。
4. 新增 1 个 E2E case：`test_11_as_of_threading.py` —— 跑 `research` skill
   带 `as_of=2024-01-01`，断言 `sources.json` 里所有条目 `published_at ≤ 2024-01-01`。
5. `ruff check src/ tests/` clean；`pnpm typecheck`（apps/web）clean。

## 3 · 改动清单

### 3.1 Schema + API（~30 分钟）

**`services/api/src/uteki_api/schemas/chat.py`**
```python
from datetime import date

class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(..., min_length=1)
    session_id: str | None = None
    agent: str = "research"
    model: str | None = None
    as_of: date | None = None  # ← 新增；YYYY-MM-DD ISO 字符串，pydantic 自动 parse
```

**`services/api/src/uteki_api/api/agent.py`**
在 `_build_harness` 加 `as_of` 参数，传给 `AgentHarness(...)`：
```python
async def _build_harness(
    agent_name: str,
    model: str | None,
    session_id: str | None,
    user_id: str,
    as_of: date | None = None,  # ← 新增
) -> AgentHarness:
    ...
    return AgentHarness(
        ...,
        as_of=as_of,
    )
```
`chat()` 和 `start()` 都把 `req.as_of` 透传。

### 3.2 Harness（~1h）

**`services/api/src/uteki_api/agents/harness.py`**

`AgentHarness.__init__` 加 `as_of: date | None = None`，存为属性。

实例化 `SourceCatalog` 时传入：
```python
self.skill.sources = RunSources(
    catalog=SourceCatalog(run_id=run_id, as_of=self.as_of.isoformat() if self.as_of else None),
    run_id=run_id,
    user_id=self.user_id,
)
```
（catalog 已经接 `as_of: str | None`，直接复用，注意 str 化。）

把 `as_of` 暴露给 skill：
```python
self.skill.as_of = self.as_of  # 让 skill 可以在 prompt 里告诉 LLM "今天是 X"
```

**关键：把 `as_of` 注入 tool 调用** —— 修改 `_invoke_tool`：
```python
async def _invoke_tool(self, run_id: str, call: AgentEvent) -> AgentEvent:
    name = call.data.get("name", "")
    args = dict(call.data.get("args", {}) or {})
    if self.as_of is not None and "as_of" not in args:
        args["as_of"] = self.as_of.isoformat()  # 注入但不覆盖 skill 显式传的
    ...
```

`_make_tool_executor` 同样处理（LLM tool-use loop 路径）。

**写入 Run 记录**：在 `run_record = Run(...)` 里加 `metadata={"as_of": ...}`
（需要先确认 Run 模型有 metadata 字段；如没有，先简单写到 `trigger_reason` 或加字段，
查看 `runs/models.py` 决定）。

### 3.3 Tool 侧（~3h，每个 30-60 分钟）

总原则：tool 接受 `as_of` 字符串 kwarg，不传时行为不变。

**`tools/kline.py`** —— 最干净
```python
async def run(self, **kwargs: Any) -> ToolResult:
    ...
    as_of = kwargs.get("as_of")  # 'YYYY-MM-DD' or None
    if not settings.use_mock_data:
        bars = await _yfinance_bars(symbol.upper(), interval, limit, end=as_of)
    ...

def _yfinance_bars_sync(symbol, interval, limit, end=None):
    ...
    if end:
        df = yf.Ticker(symbol).history(end=end, period=period, interval=yf_interval, ...)
    else:
        df = yf.Ticker(symbol).history(period=period, interval=yf_interval, ...)
```
mock 分支：把 `now_ts` 改成 `as_of` 解析的 ts（若提供）。

**`tools/financials.py`** —— 过滤 reporting_period ≤ as_of
读现有实现，把 fetch 后的报告列表按 `period_end ≤ as_of` 过滤。FMP 接口本身不
支持 end 参数，所以是 fetch-then-filter；可接受，因为这条数据量小。

**`tools/news_search.py`** —— 过滤 published_at ≤ as_of
fetch-then-filter；Google CSE 不支持 date upper bound（dateRestrict 是 lower bound 的反向），
所以走客户端过滤，记一个 metric 看丢弃率。

**`tools/market_quote.py`** —— 特殊处理
"quote" 概念是 "现在的快照"。如果 `as_of` 被设置且 ≠ 今天：
```python
async def run(self, **kwargs):
    as_of = kwargs.get("as_of")
    if as_of and as_of < date.today().isoformat():
        return ToolResult(
            ok=False,
            error=f"market_quote returns spot snapshot only; for as_of={as_of} use kline instead",
            summary="historical quote not supported; use kline tool",
        )
    ...
```
这样 skill 收到清晰错误，会改用 kline。**不要**让 market_quote 偷偷返回当天数据 ——
那是 silent correctness bug。

**`tools/web_search.py`** —— 注入 query 提示
```python
as_of = kwargs.get("as_of")
if as_of:
    query = f"{query} (information available as of {as_of})"
```
不能严格过滤外部搜索结果的发布日期，所以是 best-effort soft 约束 +
依赖 `web_extract` 写入 catalog 时被拒绝。

**`tools/web_extract.py`** —— 不动
已经把 `published_at` 写进 source dict，catalog 自己会拒绝未来的。

### 3.4 Tests（~2h）

**Unit**（`services/api/tests/unit/`）：
- `test_as_of_tools.py` —— 每个 tool 一个 case：
  - `kline(symbol="AAPL", as_of="2024-01-01")` mock 模式下最后一根 bar 的 ts ≤ 2024-01-01
  - `financials(symbol="AAPL", as_of="2024-01-01")` 返回的报告 period_end 全部 ≤
  - `news_search(query=..., as_of="2024-01-01")` 返回 items 全部 published_at ≤
  - `market_quote(symbol="AAPL", as_of="2024-01-01")` ok=False
  - `web_search(query="x", as_of="2024-01-01")` 看到 query 含 "as of"
- 不传 as_of 时所有 tool 行为不变（baseline assertion 不动）。

**E2E**（`services/api/tests/e2e/test_11_as_of_threading.py`）：
```python
def test_as_of_blocks_future_sources(client, alice, reporter):
    resp = client.post("/api/agent/chat", json={
        "messages": [{"role": "user", "content": "分析 AAPL"}],
        "agent": "research",
        "as_of": "2024-01-01",
    }, headers={**alice.auth_header(), "Accept": "text/event-stream"})
    # 解析 SSE，找 sources.json artifact
    # 断言：catalog 里每条 published_at <= "2024-01-01"
```

mock-LLM 模式下，确保 mock skill 里塞的 source published_at 是过去的（如果不是，
mock skill 也要顺便调成过去的，方便测试）。

### 3.5 Spec（~30 分钟）

**`openspec/specs/harness/spec.md`** 加一段：
```markdown
## as_of 时间窗

`AgentHarness(as_of=date)` 让所有 tool 调用按该日期切片，配合 `SourceCatalog`
拒绝 `published_at > as_of` 的 DataPoint，实现"如果在 X 日做这个决策"的回测。

注入路径：
- 实例化 SourceCatalog 时传入 → catalog 拒绝未来数据（已存在）
- _invoke_tool 把 `as_of=ISO_DATE` 注入 tool kwargs → fetcher 按时间切片（M1.x 新增）
- 暴露为 skill.as_of → skill 可在 prompt 里告诉 LLM "今天是 X"

Tool 责任：
- 历史性 tool（kline/financials/news_search）按 as_of 过滤
- 快照性 tool（market_quote）若 as_of ≠ 今天，必须返回 ok=False；不允许 silent fallback
- 不可控 tool（web_search）soft inject query 提示，最终靠 catalog 拒绝
```

## 4 · 不做

- ConsistencyRunner —— 等 M1.7
- Mock tool factory（专用于 consistency 测试）—— 等 M1.7
- 新增 `POST /api/eval/consistency` 端点 —— 等 M1.7
- Run metadata 全字段改造（只加 as_of 一个字段够用）
- 改 ModelRouter / 加新 LLM provider

## 5 · 工时盒

| 阶段 | 估时 |
|---|---|
| 3.1 Schema + API | 0.5h |
| 3.2 Harness | 1h |
| 3.3 Tool 改造 × 5 | 3h |
| 3.4 Tests (unit + 1 E2E) | 2h |
| 3.5 Spec | 0.5h |
| Buffer | 1h |
| **合计** | **8h ≈ 1 工作日** |

文档说 1.5 天 —— 留 0.5 天给踩 yfinance/FMP 兼容性的坑。

## 6 · 完成判据

```bash
./scripts/e2e.sh                                  # 32 → 33 pass
cd services/api && uv run ruff check src/ tests/  # clean
cd apps/web && pnpm typecheck                     # clean
```

最后 commit message 示例：
```
feat(harness): thread as_of through harness and tools

Pipes optional as_of date from ChatRequest → harness → tool kwargs, so
fetchers slice at the source instead of fetching-then-rejecting at the
catalog layer. Backtests can now run "as if it were 2024-01-01" without
future data leaking through tool .data payloads to the LLM.

- ChatRequest.as_of (optional, ISO date)
- AgentHarness(as_of=...) injects into _invoke_tool kwargs
- kline: yfinance history(end=as_of); financials: period_end filter;
  news_search: published_at filter; market_quote: refuse historical
  (use kline instead); web_search: soft query hint
- T11 verifies sources.json contains no published_at > as_of

Refs design/09-as-of-threading.md; archives design/08 Task 1-3.
```
