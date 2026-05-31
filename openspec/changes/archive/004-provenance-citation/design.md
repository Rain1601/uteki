# 004 · Design

## Key design

### 1. Run-scoped source catalog

新增 `uteki_api.provenance`：

```python
SourceType = Literal[
    "tool_result",
    "web_search",
    "web_extract",
    "market_data",
    "financials",
    "filing",
    "news",
    "computed",
    "user_input",
]

ConfidenceLevel = Literal["high", "medium", "low"]

class DataPoint(BaseModel):
    id: int
    key: str
    value: Any
    source_type: SourceType
    source_url: str | None = None
    publisher: str | None = None
    published_at: str | None = None
    fetched_at: str
    as_of: str | None = None
    derived_from: list[int] = []
    confidence: ConfidenceLevel = "medium"
    excerpt: str | None = None
```

`SourceCatalog` 每个 run 一个：

```python
class SourceCatalog:
    def add(partial: dict) -> int: ...
    def get(dp_id: int) -> DataPoint | None: ...
    def has(dp_id: int) -> bool: ...
    def valid_ids() -> set[int]: ...
    def to_dict() -> dict[str, Any]: ...
    def to_llm_block(ids: list[int] | None = None) -> str: ...
```

Dedup 规则：

- 有 `source_url`：按 `(source_url, key)` 去重。
- `computed`：按 `(source_type, key, value)` 去重。
- 其他无 URL source：不强去重，避免误合并。

### 2. Harness injection

类似 `RunArtifacts`，harness 在 `skill.run()` 前注入：

```python
self.skill.sources = RunSources(
    catalog=SourceCatalog(),
    run_id=run_id,
    user_id=self.user_id,
)
```

`BaseAgent` 增加可选属性：

```python
sources: RunSources | None = None
```

`RunSources` 是 facade：

```python
class RunSources:
    async def add(self, partial: dict) -> int: ...
    async def list(self) -> list[DataPoint]: ...
    async def write_artifact(self, artifacts: RunArtifacts) -> Artifact: ...
    def valid_ids(self) -> set[int]: ...
    def parse_citations(self, text: str) -> CitationExtraction: ...
```

run finish 前，harness 调：

```python
if self.skill.sources and len(self.skill.sources) > 0:
    artifact = await self.skill.sources.write_artifact(self.skill.artifacts)
    emit artifact_written for source-catalog.json
```

如果 skill 自己已经写过 `source-catalog.json`，harness 不覆盖，避免 last-write surprise。

### 3. Tool result source metadata

当前：

```python
class ToolResult(BaseModel):
    ok: bool
    summary: str = ""
    data: Any = None
    error: str | None = None
```

扩展为：

```python
class ToolResult(BaseModel):
    ok: bool
    summary: str = ""
    data: Any = None
    error: str | None = None
    sources: list[dict] = []
```

约定：

- `sources` 里的 dict 是未分配 id 的 DataPoint partial。
- harness `_invoke_tool()` 执行 tool 后，如果有 `result.sources` 且 `self.skill.sources` 存在，就逐条注册。
- 注册后的 source ids 写回 `tool_result.data.source_ids` 或 `tool_result.data._source_ids`。

这样 leaf tools 不需要知道 run_id，也不直接写 artifact。

### 4. Citation parser

迁移 `uteki.open` 的 parser，支持：

- `[src:7]`
- `[src:1,3,7]`
- `[src:none]`

输出：

```python
class CitationExtraction:
    text: str
    citations: list[Citation]
    orphan_ids: list[int]
    no_source_count: int
    def all_cited_ids(self) -> set[int]: ...
    def cleaned(valid_ids: set[int]) -> str: ...
```

规则：

- orphan citation 不让 run 崩溃。
- evaluator 可以把 orphan citation 作为 hard fail。
- UI 后续可以用 `cleaned()` 避免显示不存在的 source chip。

### 5. Artifact contract

新增标准 artifact：

```text
source-catalog.json
```

Schema：

```json
{
  "run_id": "abc123",
  "items": {
    "1": {
      "id": 1,
      "key": "revenue_2024",
      "value": 123.4,
      "source_type": "financials",
      "publisher": "FMP",
      "source_url": "https://...",
      "published_at": "2025-02-01T00:00:00Z",
      "fetched_at": "2026-05-30T02:00:00Z",
      "confidence": "high",
      "excerpt": "..."
    }
  }
}
```

`source-catalog.json` 是 run-scoped，不跨 run 复用。

### 6. Evaluator integration

新增 verifier：

```python
async def citation_ids_exist(target_text: str, source_catalog: dict) -> tuple[bool, str]:
    ...
```

新增 helper：

```python
async def load_source_catalog(artifacts: RunArtifacts) -> SourceCatalog | None:
    ...
```

Evaluator 行为：

- 如果 contract 要求 citation compliance，但没有 `source-catalog.json`，返回 fail。
- 如果有 orphan ids，返回 fail，notes 中列出 orphan ids。
- `[src:none]` 不算 orphan，但会计入 unsourced count，供 judge rubric 使用。

### 7. Backward compatibility

- 没有 `sources` 的旧 skill 正常运行。
- 没有 `source-catalog.json` 的旧 run 正常回放。
- `ToolResult.sources` 默认为空，不破坏现有 tools。

## Key milestones

### M1 — Provenance models

- 新增 `DataPoint`、`SourceCatalog`、`CitationParser`。
- 单测覆盖 add/dedup/to_dict/to_llm_block。

### M2 — Harness integration

- `BaseAgent.sources` 可选注入。
- harness 注册 `ToolResult.sources`。
- run finish 前写 `source-catalog.json` artifact。

### M3 — Citation verifier

- evaluator 支持 citation id validation。
- eval case 可要求 source catalog 存在。

### M4 — First tool adaptation

- 选择 1-2 个低风险工具先适配 source metadata：
  - `news_search`
  - `web_extract`
  - 或 mock `financials`

## Key results

- 一次 research run 可以产出 `source-catalog.json`。
- final text 中 `[src:N]` 能被机械验证。
- 模型编造 `[src:999]` 时 evaluator 能 fail，而不是人工 review 才发现。
- 后续 company pipeline 可以复用同一 provenance 层。

