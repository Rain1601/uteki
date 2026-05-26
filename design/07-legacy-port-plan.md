# 07 · uteki.open Inventory + Port Plan

> 2026-05-27 · 调研 `~/PycharmProjects/uteki.open`（上一代 uteki）的成果。
> 用途：Phase 2（真实工具接入）的 port 决策依据 + 跨版本 architecture 对比记录。

## 一、为什么 legacy 比 current 重 5-10 倍（≠ "更完善"）

| 维度 | uteki.open (legacy, 2019 源文件) | uteki (current, 185 源文件) |
|---|---|---|
| README 定位 | "AI-powered **quantitative trading** platform" | "investment research **agent** platform" |
| 核心范式 | **skill = Python code**（1660 行 `skill_runner.py` 实现 7-gate ReAct）| **skill = prompt + tool**（270 行 `ResearchPipeline` + SKILL.md ~500 行） |
| 资产范围 | US + A 股 + HK + 加密 + 外汇 + 期货 | US-only |
| 持久层 | PostgreSQL + ClickHouse + Qdrant + Redis + MinIO | SQLite |
| 领域分层 | 13 个 DDD 风格 domain（每个 models/api/repository/service）| 1 个扁平 layer + skills/tools 插件 |

**legacy 多出来的代码，绝大部分是**：
- CRUD scaffolding（13 个 domain）
- Python 写死的投研逻辑（vs 现在搬到 prompt）
- 多资产 normalization 层
- Production-grade 多数据库 ops 工具

**这些不是"更完善的 agent 架构"，是 pre-LLM 时代的 code-first habits**。当前架构看似"功能不全"，其实是**把 domain 知识 offload 给 LLM + tool 调用**的现代范式。代码量小 5-10x 是范式收益，不是技术负债。

代价：LLM 行为不稳定 + 每次 run 有成本。
收益：self-evolution loop 可行 + 零代码加 skill + prompt 即版本。

## 二、treasury inventory（值得 port 的清单）

| 路径 | LOC | 用途 | Port 决定 |
|---|---|---|---|
| **`data/providers/base.py`** | 132 | `BaseDataProvider` ABC + `KlineRow` + `DataProviderFactory` + `AssetType` 路由 | 🔴 **直接 port**——当前 uteki tool 直接调外部 API，缺这层 |
| **`data/providers/yfinance_provider.py`** | 122 | yfinance 实现，含 retry + 指数退避 | 🔴 **直接 port** |
| **`data/providers/fmp_provider.py`** | 108 | FMP REST API | 🔴 **直接 port** |
| `data/providers/{akshare,tushare,binance}_provider.py` | — | A-share / 加密 | ⚫ **不 port**（US-only 决策 + 不做加密） |
| **`agent/research/search_engine.py`** | ~150 | `SearchStrategy` ABC + **Google Custom Search 完整实现** | 🟡 **可选**——见 Q3 重做决策 |
| `agent/research/web_search.py` | 61 | tool facade | 🟡 模式可学，代码改写 |
| **`agent/research/web_scraper.py`** | 253 | 网页抓取 + 主体内容提取 | 🔴 **直接 port** 给 `web_extract` tool |
| **`company/financials.py`** | 720 | yfinance 高级 wrapper + cache + 基本面数据 | 🟡 拿 cache 模式 + 部分逻辑（不全 port，太重） |
| `agent/research/orchestrator.py` | 399 | "Decompose → Search → Scrape → Synthesize" | ⚫ 不 port——current `ResearchPipeline` 同构且更干净 |
| `news/{bloomberg,cnbc,...}_*.py` | — | 商业新闻订阅 | ⚫ v1 跳，Phase 2 用 Tavily / Google 替代 |
| **`macro/fred_api.py`** | 79 | FRED 宏观数据（M2 等） | 🟢 **可选 port**——作为第 8 个 tool 加值高 |
| `agent/core/budget.py` | 67 | `ToolBudget` per-gate 概念 | 🟢 对照学习——current `HarnessLimits` 是 per-run，legacy 是 per-gate，两种各有合理 |
| `agent/core/tool_parser.py` | 196 | 多格式 LLM tool-call 解析 | ⚫ 不需要——current 用 provider 原生 tool_use API |
| `company/skill_runner.py` | 1660 | 7-gate ReAct 投资分析 pipeline | ⚫ **不 port，作为反面教材阅读**——证明"prompt-first 比 code-first 小一个数量级" |

## 三、5 个值得吸收的设计模式

### F1. `BaseDataProvider` ABC + Factory · 缺失的中间层

```python
# uteki.open:
class BaseDataProvider(ABC):
    async def fetch_daily_klines(symbol, start, end) -> List[KlineRow]: ...
    async def get_quote(symbol) -> Optional[dict]: ...

class DataProviderFactory:
    @classmethod
    def get_provider(cls, asset_type: AssetType) -> BaseDataProvider: ...

# 用法：
provider = DataProviderFactory.get_provider(AssetType.US_STOCK)
klines = await provider.fetch_daily_klines("NVDA", ...)
```

**当前 uteki**：Tool 直接 import yfinance/FMP SDK，**没 provider 抽象层**。

**Port 价值**：
- Tool（"agent 看见的能力"）和 Provider（"真实后端"）分离
- **多 provider failover** 天然支持（yfinance 挂了切 FMP）
- 测试更易 mock
- Phase 2 的 architecture 一开始就该这样

### F2. retry + exponential backoff 已有现成模式

`yfinance_provider.py` 已经写好（MAX_RETRIES=3，base_delay=1s，指数 1→2→4s）。**省去重新设计的 30 分钟，直接 copy**。

### F3. Cache layer 是 production must

`company/financials.py:14`：
```python
CACHE_KEY_PREFIX = "uteki:company:data:"
CACHE_TTL = 7 * 24 * 3600  # 7 days
```

7 天 TTL 对财报数据合理（季度发一次）。**当前 uteki 没任何 cache**——每次 run 都 hammer 外部 API。

**Port 重点**：先做 in-process LRU（`functools.lru_cache` 或 `cachetools`），后期 Redis。

### F4. `as_of` 参数 · point-in-time 查询

`financials.py` 注释：
> The cache key is namespaced by `as_of` so historical-backtest runs do not pollute the live ("now") snapshot.

**深刻**——做投研 agent 应该支持"以 2024-06-30 数据视角写报告"（backtest 场景）。当前 uteki 完全没这个概念。**Phase 2 设计 ToolResult 时加 `as_of` 字段**。

### F5. `AssetType` enum + `PROVIDER_ROUTING` 路由表

```python
PROVIDER_ROUTING: dict[AssetType, DataProvider] = {
    AssetType.US_STOCK: DataProvider.YFINANCE,
    AssetType.US_ETF: DataProvider.YFINANCE,
    ...
}
```

**简单但有效**——asset type 决定 provider，不用 Tool 层判断。前端展示也能根据 asset_type 切换 UI。

## 四、3 个反面教训（不该 port）

### A1. 13-domain 单体应用 = 过度工程

```
backend/uteki/domains/
├── admin / auth / company / data / evaluation
├── index / macro / news / notification / snb / user
└── agent
```

每个 domain 自己有 models/api/repository/service。**2019 源文件 vs current 185**。

**不学**。当前 uteki 扁平 + agent-first 架构对"agent platform"更合适。Domain 拆分是 CRUD 应用范式，不是 agent 范式。

### A2. 1660 行 skill_runner = "skill 写在 code 里"

`company/skill_runner.py`：每个 gate 一段 prompt + verifier + cross-gate reflection——**一个 skill 1660 行 Python**。

vs current `ResearchPipeline` 270 行——领域知识在 **SKILL.md prompts** 里。

**这是范式差异，不是工程差异**。**Prompt-first 让 self-evolution loop 可行**——SKILL.md 改完 hash 自动 bump 版本，code 改不能。

### A3. 多格式 tool_call_parser = LLM 早期痛苦

`tool_parser.py` 解析 4 种 LLM 输出格式（XML/JSON/markdown/wrapper）。Anthropic + OpenAI 现在都标准化了 native tool_use，**这一层痛苦可以跳过**。

## 五、修订后的 Phase 2 任务表

替换 [`05-roadmap-to-v1.md`](./05-roadmap-to-v1.md) 原 Phase 2 任务表。Port 后总工时从 16d → ~12d。

| # | Task | Port from | 估时 |
|---|---|---|---|
| **2.0** | **新增**：建 `tools/providers/` 目录 + port `base.py` (BaseDataProvider ABC + KlineRow + Factory + AssetType) | `uteki.open/data/providers/base.py` | 0.5d |
| 2.1 | 数据源决策（Q1-Q4）+ API key 准备 | — | 0.5d |
| **2.2** | Port `yfinance_provider.py`（含 retry/backoff） | 直接 copy + 适配 | 0.5d |
| **2.3** | Port `fmp_provider.py` | 直接 copy + 适配 | 0.5d |
| 2.4 | `market_quote` + `kline` Tool 改成调 `DataProviderFactory` | — | 0.5d |
| **2.5** | **新增** in-process LRU cache layer（按 data type 不同 TTL） | `uteki.open/company/financials.py` 学 TTL 策略 | 0.5d |
| **2.6** | Port `search_engine.py` Google CSE + 选配 TavilyStrategy（env 切换） | `uteki.open/agent/research/search_engine.py` | 1d |
| 2.7 | `news_search` + `web_search` tool 接入 SearchEngine | — | 0.5d |
| **2.8** | Port `web_scraper.py` for `web_extract` tool | 直接 copy + 适配 | 0.5d |
| 2.9 | `financials` Tool 接 FMP API（income/balance/cashflow） | 新写（legacy 没现成 FMP financials wrapper） | 1.5d |
| 2.10 | SEC EDGAR `report_analysis` Tool（pypdf 解析 10-K） | 新写 | 2d |
| 2.11 | `ToolResult` 加 `{provenance, fetched_at, freshness, confidence, as_of}` | 设计新增 | 1d |
| 2.12 | Per-user 配额追踪 + 月度费用累积 | 设计新增 | 1d |
| 2.13 | （可选）Port FRED `macro_indicator` Tool | `uteki.open/macro/fred_api.py` | 0.5d |
| 2.14 | 真实数据跑 Phase 1 self-evolution loop 全闭环验证 | — | 1d |

**新总工时**: ~11.5d（vs 老计划 16d）。

## 六、Q3 数据决策 · 修订建议

调研后发现 legacy 用的是 **Google Custom Search**——这就是当时用户问"为啥不用 Google"的客观答案。

| 选项 | 描述 | 工时 | 月成本 |
|---|---|---|---|
| **A** | **Port uteki.open 的 Google CSE 代码**（推荐） | 0 额外接入 | 已有 key 时 $0；新申请 $5/1k 查询 |
| B | Tavily $30/月 | 接入 1h | $30/月 |
| C | A + B 都接，env 切换 | 接入 +0.5h | 按用量 |

**修订推荐**：**A**——既然 legacy 已有完整 Google CSE 实现 + 用户已经熟悉 Google API，**直接 port**。Tavily 留作 Phase 5 优化项。

## 七、port 顺序建议

按依赖关系：

```
Day 1:  2.0 base.py ABC + Factory
Day 1.5: 2.2 yfinance_provider.py
Day 2:  2.3 fmp_provider.py + 2.4 wire Tools
Day 2.5: 2.5 cache layer
Day 3-4: 2.6 search_engine.py port (Google CSE)
Day 4.5: 2.7 + 2.8 search + extract Tool wiring
Day 5-6: 2.9 FMP financials wrapper (新写)
Day 7-8: 2.10 SEC EDGAR + pypdf (新写)
Day 9: 2.11 ToolResult metadata + 2.12 quota
Day 10: 2.13 (opt) FRED + 2.14 闭环验证
```

每个 Day 完成后**可独立 commit + 测试**，不阻塞后续。

## 八、跨版本 architecture 学到的元教训

1. **代码量 ≠ 架构成熟度**。legacy 2019 文件不代表"更完善的 agent"——它是更完善的"CRUD + 多资产平台"。

2. **范式跨越**比"做加法"重要。从 code-first skill 切换到 prompt-first skill 是 10x 收益的范式变更，不是工程优化。

3. **能 port 的代码是数据集成层**——provider 抽象、retry 机制、scraping 逻辑——这些是 LLM-agnostic 的。**不能 port 的是 orchestration**（skill_runner）和 **架构选择**（13 domain）。

4. **当前 architecture 不是 legacy 的简化版**，是**针对 LLM agent 时代重新设计的**。Port 时要保持这个判断——不要把当前 architecture 改回 legacy 的样子。

## 九、Cross-references

- `design/00-agent-platform.md` — 当前架构现状
- `design/05-roadmap-to-v1.md` Phase 2 — 原计划（被本文修订）
- `design/06-agent-flow-demo.md` — 端到端运行图谱
- `uteki.open/CLAUDE.md` — legacy 项目的当前状态（已加入 working dir，可直接 read）
