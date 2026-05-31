# Artifacts — spec

> 最新更新：2026-05-31 · change 005-artifact-first-runs 落地

## 设计哲学

Anthropic harness design 中"文件作 agent 通信脊梁"：

> "Communication was handled via files: one agent would write a file, another
> agent would read it and respond either within that file or with a new file."

uteki 的 Artifact 层就是这条原则的实装。Event 流是日志（"发生了什么"）；artifact 是状态（"现在是什么"）。M6 planner/generator/evaluator 之间靠 artifact 通信。

## 数据模型

```python
ArtifactKind = Literal["markdown", "json", "text", "binary"]
ArtifactRole = Literal[
    "primary", "draft", "plan", "contract", "evaluation",
    "trace", "source_catalog", "diagnosis", "auxiliary",
]

class Artifact(BaseModel):
    run_id: str
    name: str
    kind: ArtifactKind
    size_bytes: int
    sha256: str
    created_at: float
    written_by: str       # skill name
    description: str = ""
    content_type: str = "" # MIME，由 kind 推
    role: ArtifactRole = "auxiliary"
    display_name: str = ""
    source_refs: list[int] = []
```

## 接口

```python
class ArtifactStore(ABC):
    async def write(
        run_id, name, content, *, kind, written_by, description="",
        role="auxiliary", display_name="", source_refs=None
    ) -> Artifact
    async def read(run_id, name) -> tuple[Artifact, bytes]
    async def list(run_id) -> list[Artifact]
    async def exists(run_id, name) -> bool

class RunArtifacts:
    """Run-scoped facade. Skill 通过 self.artifacts.write/read 操作。"""
    @property
    def run_id: str
    async def write(
        name, content, *, kind="markdown", description="",
        role="auxiliary", display_name="", source_refs=None
    ) -> Artifact
    async def read(name) -> bytes
    async def read_text(name) -> str
    async def list() -> list[Artifact]
    async def exists(name) -> bool
```

## 默认实装：LocalFileArtifactStore

```
data/runs/<sha2>/<run_id>/
├── manifest.json
└── artifacts/<name>
```

`<sha2>` = `run_id[:2]`，单目录控制。`manifest.json` 原子写（`.tmp` → `os.replace`）。

## Artifact 命名约定

```
research   → final-research.md
earnings   → final-earnings.md
planner    → plan.md, sprint-contract.json     (M6)
evaluator  → eval-report.json, judge-*.json     (M6/M7)
provenance → source-catalog.json                (004)
run        → final-report.md                    (005-artifact-first-runs)
company   → company-profile.json, financials.json, news-brief.json,
            gate-*.md, decision.json,
            peer-comparison.json, ranking.json, capital-plan.json,
            agent-capability-review.json        (006/009-company-research-pipeline)
diagnosis → trace-diagnosis.json                (007)
```

`name` 字段必须匹配 `[A-Za-z0-9._-]+` 且不能是 `..`。任何路径分隔符直接 reject。

## 安全：路径穿越防线

**两道防线**：

1. `_validate_name(name)`：regex 白名单
2. 拼接后绝对路径必须 `startswith(<root>/<sha2>/<run_id>/artifacts/)`

REST 层（`api/artifacts.py`）只把 `ValueError` 映射成 HTTP 400 / `FileNotFoundError` 映射成 404；不重复校验。

## 新事件类型

```python
"artifact_written"   data: {name, kind, size_bytes, written_by, description, url}
"await_review"       data: {checkpoint, ready_artifacts: [name...], reason?}
```

约定：**skill 写完 artifact 后立即 yield `artifact_written`**。Run detail API 会返回 artifact index；事件流仍保留 artifact_written 事实流以兼容 SSE 和旧页面。

例外：`source-catalog.json` 可由 harness 在 run 结束前自动写入，并由 harness emit `artifact_written`。这是因为 source metadata 来自多个 tools / sub-skills，catalog 的持久化属于 run-level concern。

`final-report.md` 也可由 harness 在 run 结束前自动写入，并由 harness emit `artifact_written`。这是 artifact-first run detail 的 primary deliverable fallback：若 skill 没有直接写主报告，但存在 `final-research.md` / `investment-memo.md` / streamed delta，harness 负责落成稳定主产物。

## Artifact-first run detail（005-artifact-first-runs）

`GET /api/runs/{run_id}` MUST include:

- `artifacts`: artifact refs from manifest
- `primary_artifact`: role=`primary` 的 artifact；没有时按 `final-report.md`、`investment-memo.md`、`final-research.md`、`research.md` fallback
- `events_summary`: event type histogram
- legacy `events`: kept for replay/debugging

`GET /api/runs` SHOULD include `artifact_count` and `primary_artifact` so list pages can link to the stable deliverable without reconstructing deltas.

## Company research artifacts（006-company-research-pipeline）

`company_research_pipeline` SHOULD emit:

- evidence: `company-profile.json`, `financials.json`, `news-brief.json`
- gate drafts: `gate-01-business_analysis.md` through `gate-06-valuation.md`
- peer evaluation: `peer-comparison.json`, `ranking.json`
- sizing evaluation: `capital-plan.json`
- stage review: `agent-capability-review.json`
- primary: `final-report.md`, role=`primary`, display name `Investment memo`
- structured decision: `decision.json`
- source catalog: `source-catalog.json` when tool sources exist

`capital-plan.json` MUST set `real_order_execution=false` and keep `max_position_pct <= 10`.

`agent-capability-review.json` MUST include stage entries with autonomy, observability, traceability, and self-iteration fields.

## Trace diagnosis artifact（007-trace-diagnosis）

Every artifact-capable run SHOULD write `trace-diagnosis.json` with role `diagnosis`.
It summarizes event counts, failures, tool usage, artifacts, usage totals, and citation/source-catalog status.

## await_review 当前行为（M5）

```python
if event.type == "await_review":
    # 双写 + yield
    record = await self.run_store.get(run_id)
    if "auto-approved" not in record.tags:
        record.tags.append("auto-approved")
    continue   # skill 继续
```

005.2 加 `compliance_mode` + `POST /api/runs/{id}/approve` 实装真拦截。

## REST 端点

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/runs/{run_id}/artifacts` | 列表（manifest） |
| GET | `/api/runs/{run_id}/artifacts/{name}` | 下载 / 查看（Content-Type 按 kind） |

## 不属于本 spec

- 真审批拦截（005.2）
- Retention policy（005.3）
- S3 / Vercel Blob backend（005.4）
- Artifact 版本控制 / diff（artifact 是 run-scoped，run 本身就是版本）
- Skill 间结构化协议（schema 校验）—— 走 SKILL.md prompt 约定 + Python class 内部固定命名
- SourceCatalog schema —— see `openspec/specs/provenance/spec.md`

## 不变量

1. **manifest 是元数据真相源**：磁盘文件即使被删，list/read 走 manifest（read 时再校验文件存在）
2. **last-write-wins**：同 run 同 name 重写 → 覆盖（同 run 串行执行，无并发）
3. **artifact index 是阅读入口**：run detail 优先展示 primary artifact；events 是诊断入口
4. **路径绝不出 sandbox**：`_validate_name` + 绝对路径 startswith 检查 → 双重防线
