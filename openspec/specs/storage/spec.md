# Storage — spec

> 创建于 2026-05-25 · 落地 M4（change 001-tenant-and-auth）

## 总原则

uteki 的每一种 user-owned 持久状态都**必须**带 `user_id`。M4 给四个 store 引入了 partition：

| Store | Partition key | 实现 | 位置 |
|---|---|---|---|
| **RunStore** | `Run.user_id` 列 | `InMemoryRunStore` | 进程内 dict |
| **ArtifactStore** | 路径前缀 `data/users/<user_id>/runs/...` | `LocalFileArtifactStore` | 本地文件 |
| **Memory（短期）** | dict 键 `(user_id, session_id)` | `InMemoryStore` | 进程内 dict |
| **EvalHistoryStore** | 路径前缀 `data/users/<user_id>/eval-history/...` | `JsonFileEvalHistory` | 本地 ndjson |

`EvolutionStore`（skill 版本）**不分区**——平台级共享，所有 user 看到同一份 evolution 历史。

## RunStore

```python
class RunStore(ABC):
    async def create(run: Run) -> None                                       # run.user_id required
    async def append_event(run_id: str, event: AgentEvent) -> None
    async def finish(run_id: str, status: RunStatus, summary: str) -> None
    async def get(run_id: str, user_id: str | None = None) -> Run
    async def list(user_id: str, skill=None, triggered_by=None, limit=50) -> list[Run]
```

不变量：
- `Run.user_id` 必填；漏传 → `create()` 抛 ValueError（M4 在 `InMemoryRunStore` 显式校验）
- `get(run_id, user_id)` 不属于该 user → 抛 `KeyError`（API 层映射 404，与"不存在"同形态）
- `list(user_id, ...)` 永远只返回该 user 自己的 runs

## ArtifactStore

路径布局（M4，**实际落盘**）：

```
data/runs/                            # ArtifactStore root (pre-M4 也是这里)
└── users/
    └── <safe(user_id)>/              # M4 加的 partition 层
        └── runs/
            └── <sha2(run_id[:2])>/   # 防单目录过宽
                └── <run_id>/
                    ├── artifacts/<name>
                    └── manifest.json
```

兼容性：M4 前版本 `data/runs/<sha2>/<run_id>/...` 已**废弃**。M4 上线即清空 `data/`，无迁移路径。

接口：

```python
class ArtifactStore(ABC):
    async def write(run_id, name, content, *, kind, written_by, description, user_id=None) -> ArtifactMeta
    async def read(run_id, name, user_id=None) -> tuple[ArtifactMeta, bytes]
    async def list(run_id, user_id=None) -> list[ArtifactMeta]
    async def exists(run_id, name, user_id=None) -> bool
```

`user_id=None` 仅供内部调用 / 测试 / `"system"` 路径；所有用户路由必须传 `owner = run.user_id`（通过 `_owner_id(run_id, user)` 在 API 层先校验 ownership 再读 store）。

## Memory（短期）

ABC 短期方法在 M4 后强制带 `user_id`：

```python
class Memory(ABC):
    # 短期（user-scoped）
    async def append_message(user_id, session_id, message) -> None
    async def get_messages(user_id, session_id) -> list[ChatMessage]
    async def append_event(user_id, session_id, event) -> None
    async def get_events(user_id, session_id) -> list[AgentEvent]
    # 长期（已经是 user-scoped）
    async def remember_fact(user_id, fact, meta=None)
    async def recall_facts(user_id, query, limit=5) -> list[str]
```

`InMemoryStore` 短期 dict 的 key 从 `session_id` 改为 `(user_id, session_id)`，避免两个 user 偶然用同一个 session_id 时相互看到事件。

harness 11 处 `memory.append_event(...)` 调用都加 `self.user_id` 作为前置参数。

## EvalHistoryStore

```python
class EvalHistoryStore(ABC):
    async def append(user_id, record) -> None
    async def list_case(user_id, case_id, limit=50) -> list[EvalRecord]
    async def list_recent(user_id, limit=100) -> list[EvalRecord]
```

ndjson 文件按 user 分区：

```
data/users/<user_id>/eval-history/
├── all.ndjson
└── by-case/
    ├── research-sector-primer.ndjson
    └── ...
```

平台级调用（`drift_monitor.check_drift`）显式传 `user_id="system"`。

## EvolutionStore（不分区）

skill 的版本演化是平台级 IP：所有 user 共享同一份"research v3"prompt。EvolutionStore 不带 `user_id`，路径仍是 `data/evolution/<skill>/...`。

## 跨用户隔离的可观察保证

- A 拿 B 的 run_id 调 `/api/runs/<B.run_id>` → 404（同"不存在"形态）
- A 拿 B 的 run_id 调 `/api/runs/<B.run_id>/artifacts` → 404
- A 调 `/api/runs` → 只看到自己的 runs
- A 调 `/api/eval/history` → 只看到自己跑过的 eval 记录
- 文件系统层：`data/users/A/...` 和 `data/users/B/...` 物理隔离

测试参见 V3（plan 验收），TestClient + in-proc store 跑过。
