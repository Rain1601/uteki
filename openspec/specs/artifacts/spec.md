# Artifacts — spec

> 最新更新：2026-05-24 · change 005 落地

## 设计哲学

Anthropic harness design 中"文件作 agent 通信脊梁"：

> "Communication was handled via files: one agent would write a file, another
> agent would read it and respond either within that file or with a new file."

uteki 的 Artifact 层就是这条原则的实装。Event 流是日志（"发生了什么"）；artifact 是状态（"现在是什么"）。M6 planner/generator/evaluator 之间靠 artifact 通信。

## 数据模型

```python
ArtifactKind = Literal["markdown", "json", "text", "binary"]

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
```

## 接口

```python
class ArtifactStore(ABC):
    async def write(run_id, name, content, *, kind, written_by, description="") -> Artifact
    async def read(run_id, name) -> tuple[Artifact, bytes]
    async def list(run_id) -> list[Artifact]
    async def exists(run_id, name) -> bool

class RunArtifacts:
    """Run-scoped facade. Skill 通过 self.artifacts.write/read 操作。"""
    @property
    def run_id: str
    async def write(name, content, *, kind="markdown", description="") -> Artifact
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

约定：**skill 写完 artifact 后立即 yield `artifact_written`**。前端只读 events 上的元数据，不调 `/api/runs/{id}/artifacts`（防止 N+1）。

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

## 不变量

1. **manifest 是元数据真相源**：磁盘文件即使被删，list/read 走 manifest（read 时再校验文件存在）
2. **last-write-wins**：同 run 同 name 重写 → 覆盖（同 run 串行执行，无并发）
3. **event = artifact 的事实流**：前端只看 events 不查 manifest（防 N+1）
4. **路径绝不出 sandbox**：`_validate_name` + 绝对路径 startswith 检查 → 双重防线
