# 005 · Design

## 数据模型

```python
class Artifact(BaseModel):
    run_id: str
    name: str                                    # "plan.md" / "draft-X.md" / "eval-report.json"
    kind: Literal["markdown", "json", "text", "binary"]
    size_bytes: int
    sha256: str
    created_at: float
    written_by: str                              # skill name
    description: str = ""                        # optional human label
```

不存内容到数据库——内容写文件系统，db 只存元数据。

## 目录布局

```
data/runs/<run_id>/
├── manifest.json               # 所有 artifacts 的 Artifact 列表
└── artifacts/
    ├── plan.md
    ├── draft-research-brief.md
    └── eval-report.json
```

`<run_id>` 头 2 字符做 sharding：`data/runs/c4/c4f2d054c324/...` 防止单目录文件过多。

## 接口

```python
class ArtifactStore(ABC):
    @abstractmethod
    async def write(self, run_id: str, name: str, content: bytes | str,
                    *, kind: str, written_by: str, description: str = "") -> Artifact: ...

    @abstractmethod
    async def read(self, run_id: str, name: str) -> tuple[Artifact, bytes]: ...

    @abstractmethod
    async def list(self, run_id: str) -> list[Artifact]: ...

    @abstractmethod
    async def url(self, run_id: str, name: str) -> str:
        """Pre-signed / static URL for the frontend to download / preview."""

class LocalFileArtifactStore(ArtifactStore):
    def __init__(self, root: Path = Path("data/runs")): ...

default_artifact_store: ArtifactStore = LocalFileArtifactStore()
```

skill 拿到的不是 store 而是 run-scoped facade：

```python
class RunArtifacts:
    """Convenience facade bound to a single run."""
    def __init__(self, store, run_id, written_by):
        self._store = store
        self._run_id = run_id
        self._written_by = written_by

    async def write(self, name, content, *, kind="markdown", description=""):
        return await self._store.write(self._run_id, name, content,
                                       kind=kind, written_by=self._written_by,
                                       description=description)

    async def read(self, name) -> bytes: ...
    async def list(self) -> list[Artifact]: ...
```

`BaseAgent` 新增字段：

```python
class BaseAgent(ABC):
    _tool_executor: ToolExecutor | None = None
    artifacts: RunArtifacts | None = None       # harness 注入
```

harness 在 `run()` 入口构造并注入：

```python
self.skill.artifacts = RunArtifacts(
    store=default_artifact_store,
    run_id=run_id,
    written_by=self.skill.name,
)
```

## 新事件类型

```python
EventType = Literal[
    ..., "artifact_written", "await_review", ...
]
```

### `artifact_written`

```json
{
  "type": "artifact_written",
  "run_id": "...",
  "step_id": "...",
  "data": {
    "name": "plan.md",
    "kind": "markdown",
    "size_bytes": 1234,
    "written_by": "planner",
    "description": "Initial research plan",
    "url": "/api/runs/c4f2.../artifacts/plan.md"
  }
}
```

harness 在 `RunArtifacts.write()` 成功后**自动 emit** 此事件（不靠 skill 主动 yield）—— 通过把 facade 的 write 实现成一个 async generator + 让 skill yield from。简化：facade.write 返回 Artifact，skill 自己 yield `artifact_written` AgentEvent。**约定**：skill 写完 artifact 后立即 yield 事件，否则前端看不到。

### `await_review`

```json
{
  "type": "await_review",
  "run_id": "...",
  "step_id": "...",
  "data": {
    "checkpoint": "after_primary_data_pull",
    "ready_artifacts": ["plan.md", "draft-section-1.md"],
    "reason": "request review before synthesis",
    "auto_approve_seconds": 0
  }
}
```

harness 处理逻辑：

```python
if event.type == "await_review":
    # Persist as usual
    await emit(event)
    # Decide: pause / auto-approve / reject
    if self.triggered_by == "user" and self.compliance_mode:
        # Pause the run, mark status="awaiting_review"
        await self.run_store.pause(run_id, checkpoint=event.data["checkpoint"])
        return       # skill 的生成器在 yield 后等待外部唤醒
    else:
        # auto-approve, record in tags
        run = await self.run_store.get(run_id)
        run.tags.append("auto-approved")
```

**注意**：暂停 / 唤醒涉及 async generator 的中断恢复，是非平凡的实现。M5 版本先只做"emit 事件 + 自动通过"（compliance_mode 默认 false），人工审批的真实拦截放到 005.2 follow-up（或并到 006 实装时）。

## API 端点

```
GET    /api/runs/{run_id}/artifacts
       → {items: [Artifact...]}

GET    /api/runs/{run_id}/artifacts/{name}
       → application/octet-stream（带 Content-Type 按 kind）

POST   /api/runs/{run_id}/approve
       → 唤醒挂起的 run（005.2 实装）
       body: {decision: "approve" | "reject", notes?: str}
```

## 前端

`/runs/[id]` 详情页加 **Artifacts** tab（与现有 Events tab 并列）：

```
Artifacts (3)
├─ 📄 plan.md            written_by=planner  3.2 KB     [view] [download]
├─ 📄 draft-brief.md     written_by=research 12.1 KB    [view] [download]
└─ 📊 eval-report.json   written_by=evaluator 1.8 KB    [view] [download]
```

点 `[view]` markdown 渲染、json prettify 显示在 modal / 右侧抽屉。

Trace 上的 `artifact_written` 事件 → 在时间线显示 📄 图标 + 文件名 + 链接。

## 重要复用

- 不动 `RunStore` / `Run`：artifacts 通过 `run_id` 关联
- 不动 harness 主循环结构：仅注入 facade、新 event 类型走双写
- 前端 Trace.tsx：新 event type 加一个 case 即可

## 关键文件

**新建**：
- `services/api/src/uteki_api/artifacts/__init__.py`
- `services/api/src/uteki_api/artifacts/models.py` — Artifact
- `services/api/src/uteki_api/artifacts/store.py` — Abstract + LocalFile + RunArtifacts facade
- `services/api/src/uteki_api/api/artifacts.py` — list / get 端点
- `apps/web/components/agent/Artifacts.tsx`
- `apps/web/lib/api.ts` 加 `listArtifacts(runId)` / `getArtifactUrl(...)`

**修改**：
- `services/api/src/uteki_api/schemas/events.py` —— 加 `artifact_written` / `await_review`
- `services/api/src/uteki_api/agents/base.py` —— 加 `artifacts` 字段
- `services/api/src/uteki_api/agents/harness.py` —— 注入 facade
- `services/api/src/uteki_api/main.py` —— 挂 artifacts router
- `apps/web/components/agent/Trace.tsx` —— 渲染新事件
- `apps/web/app/runs/[id]/view.tsx` —— 加 Artifacts tab
