# Provenance — spec

> 最新更新：2026-05-31 · change 004 落地

## Purpose

Provenance makes investment research auditable. Every source-backed fact that a skill wants the model to cite is represented as a `DataPoint` and registered in a per-run `SourceCatalog`. Model output cites those facts with `[src:N]` markers.

## DataPoint

```python
SourceType = Literal[
    "tool_result", "web_search", "web_extract", "market_data",
    "financials", "filing", "news", "computed", "user_input",
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

`published_at` is when the source says the data was published. `fetched_at` is when uteki fetched it. These must not be conflated.

## SourceCatalog

One catalog exists per run.

Responsibilities:

- Assign 1-indexed source ids.
- Deduplicate obvious repeated sources.
- Render a compact LLM block with `[src:N]` markers.
- Serialize to `source-catalog.json`.

Dedup rules:

- With `source_url`: dedupe by `(source_url, key)`.
- With `source_type == "computed"`: dedupe by `(source_type, key, value)`.
- Other source entries are preserved to avoid accidentally merging distinct facts.

Run-scoped ids are stable only within that run.

## Citation markers

Supported syntax:

- `[src:7]`
- `[src:1,3,7]`
- `[src:none]`

Validation rules:

- Every numeric id must exist in the run's `SourceCatalog`.
- `[src:none]` is valid and means "explicitly not source-backed".
- Missing ids are orphan citations. They do not crash the run, but evaluator can fail the output.

## Harness integration

Harness injects:

```python
self.skill.sources = RunSources(SourceCatalog(run_id=run_id), ...)
```

`ToolResult` may carry source partials:

```python
class ToolResult(BaseModel):
    ...
    sources: list[dict[str, Any]] = []
```

Harness registers those source partials after tool execution and attaches registered ids to `tool_result.data.preview._source_ids`.

## Artifact

Standard artifact:

```text
source-catalog.json
```

The artifact stores:

```json
{
  "run_id": "...",
  "items": {
    "1": { "id": 1, "key": "...", "value": "...", "source_type": "..." }
  }
}
```

`source-catalog.json` is written automatically before `done` when a run has at least one registered source.

## Evaluation

Verifier:

```python
citation_ids_exist(target_text, source_catalog) -> (passed, notes)
```

Behavior:

- Missing source catalog fails.
- No citation markers fails.
- Orphan numeric ids fail.
- `[src:none]` is allowed and counted in notes.

## Invariants

1. Source ids are run-scoped.
2. Tool code does not write source artifacts directly; it returns source metadata.
3. Harness owns run-scoped catalog persistence.
4. Orphan citation detection is mechanical and deterministic.
5. `[src:none]` is preferable to fabricated source ids.
