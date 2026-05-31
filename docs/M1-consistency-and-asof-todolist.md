# M1 · ConsistencyRunner + `as_of` 串通 · 任务清单

> 收件人：uteki 仓内的 Claude
> 发件人：uteki.open 的 Claude（已完成 uteki vs uteki.open 架构对比 + 评估盘点）
> 日期：2026-05

---

## 0. 背景（必读，3 段）

`uteki.open` 是一个先行实验仓，沉淀了"投研 agent + 多维度评估"。它的两个评估能力 —— **ConsistencyRunner**（同输入跑 N 次量化稳定性）和 **`as_of` 时间窗强约束**（回测时拒绝未来数据）—— uteki 还没有。本里程碑把这两个能力补进 uteki。

**uteki 现状已有**：
- ✅ 完整 SourceCatalog（`provenance/catalog.py`）+ DataPoint + citation parser
- ✅ `as_of` **只在 catalog 层**有效（catalog 拒绝 `published_at > as_of`），但 **没串到 harness/tool 层**
- ✅ 案例 eval runner + LLM-as-judge + DriftMonitor + RunStore
- ❌ 没有 ConsistencyRunner（N 次重跑 + 一致性指标聚合）
- ❌ `as_of` 没自动从 RunContext 透传到所有 tool 调用

**uteki.open 模板路径**（仅作设计参考，不直接拷贝）：
- ConsistencyRunner 参考：`/Users/rain/PycharmProjects/uteki.open/backend/uteki/domains/evaluation/service.py` 69-250 行
- AgentMemory 参考：`/Users/rain/PycharmProjects/uteki.open/backend/uteki/domains/index/models/agent_memory.py`
- 7-Gate 模式参考：`/Users/rain/PycharmProjects/uteki.open/backend/uteki/domains/company/skill_runner.py`

注意：**uteki.open 用 SQLAlchemy + PostgreSQL，uteki 用 SQLModel + SQLite**。schema 形状可借鉴，建表语法要改。

---

## 1. 验收标准（先看这个再动手）

完成本里程碑后，应能：
1. 通过 API 触发"对同一 skill + 同一输入跑 N 次"，返回 action 一致率、gate score CV、token 成本均值 / 方差等指标
2. 在启动 harness 时显式传 `as_of=YYYY-MM-DD`，**所有**工具调用（yfinance / FMP / news_search 等）自动按这个时间点切片，**回测不被未来数据污染**
3. 所有新代码通过 `uv run pytest` + `uv run ruff check` + `uv run mypy`
4. ConsistencyRunner 跑 10 次 `research` skill + `AAPL` 不抛异常，metrics JSON 完整

---

## 2. 任务列表（按依赖顺序）

### Task 1 — `RunContext` 支持 `as_of`
**文件**：`services/api/src/uteki_api/agents/base.py` 或 `agents/harness.py`

- 在 `RunContext`（或等价对象，看现有命名）添加可选字段 `as_of: date | None = None`
- 在 `Harness.run()` 入口接收 `as_of` 参数并写入 ctx
- 写入 `Run` 记录的 metadata（持久化）
- **验收**：单测 — 启动 harness 传 `as_of=date(2024, 1, 1)`，ctx.as_of 正确传递

**Files to read first**: `agents/harness.py`, `agents/base.py`, `runs/store.py`

---

### Task 2 — 把 `as_of` 串到 `SourceCatalog`
**文件**：`services/api/src/uteki_api/provenance/catalog.py`

- 当前 `SourceCatalog` 的 `as_of` 在 init 时传。改成：
  - harness 启动时按 ctx.as_of 实例化 SourceCatalog
  - 把 catalog 注入 RunContext（已经这样做了？确认一下）
- 现有 catalog 拒绝逻辑（`published_at > as_of[:10]`）不动，仅确保它被 fed 了正确的 as_of

**验收**：单测 — catalog 初始化时收到 `as_of='2024-01-01'`，添加 `published_at='2025-06-01'` 的 DataPoint 时被拒绝并记 warning

---

### Task 3 — Tool 层接 `as_of`
**文件**：`services/api/src/uteki_api/tools/base.py` + 各具体工具

- `BaseTool.execute()` 签名扩展：接收 `ctx: RunContext`（或同等机制），从中读 `as_of`
- 改造以下工具按 `as_of` 切片：
  - `market_quote.py` — yfinance: `history(end=as_of)`
  - `kline.py` — 同上
  - `financials.py` — 用 reporting_period ≤ as_of 过滤
  - `news_search.py` — 检索结果按 `published_at ≤ as_of` 过滤
  - `web_search.py` — 这个不能严格过滤，但要把 `as_of` 拼到 query 让 LLM 知情（"as of {as_of}"）
  - `web_extract.py` — 注册 DataPoint 时带上正确的 `published_at`，让 catalog 自行拒绝
  - `report_analysis.py` — 文档发布日期校验
- 工具实现里：如果 ctx.as_of is None → 行为不变（向后兼容）
- 如果 ctx.as_of 被设置 → 按上面规则切片

**验收**：单测每个工具传 `as_of` 后，返回数据不含 `published_at > as_of` 的项；不传 as_of 时行为同改造前

**关键测试用例**：`as_of='2024-01-01'`，调用 `market_quote('AAPL')` 应**只返回 ≤ 2024-01-01 的数据**

---

### Task 4 — `ConsistencyRunner` 核心
**新建文件**：`services/api/src/uteki_api/eval/consistency_runner.py`

API 形状（建议）：
```python
@dataclass
class ConsistencyConfig:
    skill: str                          # e.g. "research"
    input_payload: dict                 # 喂给 skill 的输入
    n_runs: int = 10
    model: str | None = None            # 不传走默认
    as_of: date | None = None           # 透传给 harness
    parallel: int = 3                   # 并发度
    mock_tools: bool = True             # 关键：默认 mock 外部工具确保一致性可测

@dataclass
class ConsistencyResult:
    config: ConsistencyConfig
    runs: list[RunSummary]              # 每次 run 的简要（run_id, final_text, usage, action/verdict）
    metrics: ConsistencyMetrics
    elapsed_ms: int

@dataclass
class ConsistencyMetrics:
    n_success: int
    n_failed: int
    # Categorical fields (action / verdict / recommendation 等)
    categorical_agreement: dict[str, float]   # field -> mode_ratio (0-1)
    categorical_mode: dict[str, str]
    # Numeric fields (conviction / scores)
    numeric_cv: dict[str, float]              # field -> coefficient of variation
    numeric_mean: dict[str, float]
    numeric_std: dict[str, float]
    # Cost / latency
    token_input_mean: float
    token_input_std: float
    cost_usd_mean: float
    cost_usd_std: float
    latency_ms_mean: float
```

实现要点：
- N 次 harness 调用用 `asyncio.gather(...)` 限并发（`parallel` 配置）
- 每次独立的 RunContext + Memory，避免污染
- 从每个 run 的 final_text + run_events 里提取目标字段（用 JSON path 配置或 skill-specific extractor）
- mock_tools 模式：注入 FakeTool，让外部 IO 不影响一致性测量（这条很关键，否则 yfinance 返回波动会掩盖 LLM 的不稳定）

**验收**：
- 跑 `research` skill, n_runs=3, mock_tools=True → 返回 ConsistencyResult，metrics 字段齐全
- 跑 `research` skill, n_runs=10, mock_tools=False → 不卡死、不超 budget、metrics 合理

---

### Task 5 — `ConsistencyRunner` 指标计算
**文件**：`services/api/src/uteki_api/eval/metrics.py`（新建）

实现以下函数（纯函数，可单测）：
- `coefficient_of_variation(values: list[float]) -> float` —— std / mean
- `mode_agreement(values: list[str]) -> tuple[str, float]` —— 返回 (mode, mode_count / len)
- `categorical_distribution(values: list[str]) -> dict[str, float]` —— 类目分布
- `extract_field_from_run(run: Run, json_path: str) -> Any` —— 从 final_text JSON 取字段
- 对 `action_agreement`（特殊）的 helper：把 mode_agreement 应用到 "buy/hold/sell" 三值

**验收**：每个函数有单测，边界情况（空列表、全相同值、单元素列表）覆盖

---

### Task 6 — Mock Tool 工厂
**新建文件**：`services/api/src/uteki_api/eval/_mocks.py`

- `MockToolRegistry(fixtures: dict[str, Any])` —— 给定 tool_name → 固定返回值
- ConsistencyRunner 在 `mock_tools=True` 时把这个 registry 注入 harness
- fixtures 用 YAML / JSON 文件保存在 `services/api/src/uteki_api/eval/fixtures/`，每个 skill 一份
  - `fixtures/research_aapl.yaml` — `market_quote_AAPL` / `news_search_AAPL` / 等的固定返回

**验收**：mock 模式下跑 5 次 research skill，每次工具调用返回完全一致的数据

---

### Task 7 — API endpoint
**文件**：`services/api/src/uteki_api/api/eval.py`（看现有 eval API 在哪）

新增：
- `POST /api/eval/consistency` — body 接 ConsistencyConfig，返回 ConsistencyResult JSON
- `GET /api/eval/consistency/{run_id}` — 拿历史结果

**验收**：curl 跑一次 returns 200 + 合法 JSON

---

### Task 8 — 持久化
**文件**：`services/api/src/uteki_api/eval/store.py`（看现有 store 在哪扩展）

- 新表/新文件保存 `ConsistencyResult`（建议 JSON 列存 metrics + runs，主键 run_id）
- DriftMonitor 改造：除了案例 pass_rate，也跟踪 ConsistencyMetrics 的关键指标（action_agreement、cost_usd_mean）随时间漂移

**验收**：跑两次同 config，第二次能从 DB 拿出第一次的结果做对比

---

### Task 9 — CLI / Makefile
- `Makefile` 加：`make eval-consistency SKILL=research SYMBOL=AAPL N=10`
- 也可考虑 `uv run python -m uteki_api.eval.consistency_runner --skill research --n 10`

---

### Task 10 — 文档 + 测试
- `docs/eval-consistency.md` —— 写明如何跑 + 如何加新 skill 的 fixtures + 指标含义
- `tests/eval/test_consistency_runner.py` —— 至少覆盖：
  - mock_tools=True 时确定性输出
  - n_runs=1 边界
  - 失败 run 不污染整体指标
  - `as_of` 透传

---

## 3. 不在本里程碑（不要做）

- ❌ Arena 3-phase voting（M2）
- ❌ AgentMemory category + agent_key（M3）
- ❌ 重写 harness 架构 —— 只**扩展** RunContext，不动核心
- ❌ 改 ModelRouter —— 不需要
- ❌ 加新 LLM provider

---

## 4. 风险点 & 注意

1. **mock_tools 是 ConsistencyRunner 成立的根本** —— 不 mock 的话外部数据波动会掩盖 LLM 内在不稳定。但**实际生产场景也要支持不 mock 跑**（看真实环境下模型有多稳）。两种都要测。
2. **AgentEvent 的 token/cost 字段必须完整** —— 不然 cost_mean / cost_std 算不准。检查 `runs/store.py` 是否在每次 LLM 调用后写 UsageDelta。
3. **`as_of` 切片对 yfinance 来说**：`history(end=as_of)` 是排除 end 当天的，根据需求决定要不要包含。建议**包含当天**（投资决策当天能看到当天数据）。
4. **mypy strict 模式**：所有新数据类用 `dataclass(slots=True, frozen=True)` 或 Pydantic v2 BaseModel，确保类型签名严格。
5. **不要碰 `domains/`**：uteki 没有 domains 概念（那是 uteki.open 的结构），所有新代码在 `uteki_api/eval/` + `uteki_api/agents/` + `uteki_api/tools/` 内。

---

## 5. 第一步建议

按顺序读这几个文件后再动手：
1. `services/api/src/uteki_api/agents/harness.py` —— 理解 RunContext 和事件流
2. `services/api/src/uteki_api/eval/runner.py` —— 看现有 case runner 怎么写的，新 runner 风格对齐
3. `services/api/src/uteki_api/tools/base.py` —— 看 BaseTool 签名，决定 `as_of` 怎么注入
4. `services/api/src/uteki_api/provenance/catalog.py` —— 确认 as_of 拒绝逻辑

读完后，先做 **Task 1 + Task 2**（最小改动 + 立即可测），跑通后再做 Task 3（影响面大）。

---

## 6. 完成后的简历数字

跑通 M1 后，可以填以下 P0 数字进简历：
- `research` skill action 一致率（N=10，mock）—— P0
- gate score CV（如果 skill 输出含数值分数）—— P0
- 单次完整分析 token 成本均值（mock vs 真实工具两组）—— P0

Done.
