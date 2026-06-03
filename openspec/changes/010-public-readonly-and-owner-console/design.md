# 010 · Design

## 整体架构

```
┌─────────────────────────────────────────────────────────────────────┐
│ Browser                                                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  uteki.com/...              uteki.com/console/...                    │
│  ─────────────              ────────────────────                     │
│  公开 surface                Owner console                           │
│  (public) route group        (console) route group                   │
│  bespoke chrome              现有 editorial app                      │
│  无登录                       OAuth allowlist gate                    │
│  无写按钮                     全部写按钮 + visibility 控件           │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│ FastAPI · /api/* (单一 API service)                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Depends(optional_user)  → 匿名 OK，按 visibility 过滤              │
│  Depends(require_owner)  → 非 owner 401                              │
│                                                                      │
│  序列化层硬规则：                                                    │
│  - SkillVersion.prompt 永远脱敏 (non-owner)                          │
│  - Proposal.{baseline,candidate}_prompt 永远脱敏                     │
│  - Events 落盘不含 system message                                    │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

**单 Next deploy + 单 FastAPI deploy**——简单一个 service per layer。

## 数据模型

### 新字段（一处）

```python
# services/api/src/uteki_api/runs/models.py
class RunVisibility(str, Enum):
    PRIVATE  = "private"   # 仅 owner 可见
    UNLISTED = "unlisted"  # 直链可读，列表不出现
    PUBLIC   = "public"    # 列表 + 直链都公开

class Run(SQLModel, table=True):
    ...
    visibility: str = Field(default="private", index=True)
```

`index=True` 因为 list 查询每次都按 visibility 过滤。值用 `str` 而非 `Enum` 直接（SQLModel 跟 Enum 列处理跨方言行为不一致，str + Literal 验证最稳）。

### Skill metadata 加 public_description

```python
# services/api/src/uteki_api/skills/registry.py
@dataclass
class SkillEntry:
    skill: BaseAgent
    description: str               # 现有：1 句话短描述，console 用
    public_description: str = ""   # 新增：方法学说明，public 用
    version: str
    default_tools: list[str] = field(default_factory=list)
    default_model: str = ""
    kind: SkillKind = "skill"
```

`public_description` 由 owner 在 `skills/__init__.py` 注册时手写，技术准确风格——例如：

```python
default_skills.register(
    _company_research_pipeline,
    description="公司 7-gate 投研流水线：证据收集 → 六维分析 → 投资备忘录 + 结构化裁决。",
    public_description="""\
分析单家美股公司，按 7 个 gate 顺序执行：

1. business_analysis     业务理解 + 客户 / 收入 / 成本结构
2. fisher_qa             费雪 15 问框架打分
3. moat_assessment       五力 + 网络效应 + 切换成本
4. management_assessment 管理层资本配置历史 + 持股结构
5. reverse_test          反向情景：什么情况下 thesis 会错
6. valuation             DCF + EV/EBITDA + 历史分位
7. final_verdict         结构化裁决 + radar + philosophy scores

工具：market_quote (yfinance) / financials (yfinance 含 owner earnings, insider, R&D)
     / news_search (Google CSE + DDGS) / report_analysis (SEC EDGAR 10-K)
     / web_extract (httpx + bs4)
模型：deepseek/deepseek-chat（默认）
产物：final-verdict.json + final-memo.md + 中间 6 个 gate artifacts
""",
    version="v1",
    ...
)
```

10 个 skill 全部一次性写完，长度 50-200 字，技术准确。

### Migration

```python
# alembic/versions/XXXX_add_run_visibility.py
def upgrade():
    op.add_column("runs", sa.Column(
        "visibility", sa.String(16),
        nullable=False,
        server_default="private",
    ))
    op.create_index("ix_runs_visibility", "runs", ["visibility"])

def downgrade():
    op.drop_index("ix_runs_visibility", table_name="runs")
    op.drop_column("runs", "visibility")
```

部署前清空 `data/` → 不需要 backfill 老数据。

## 权限模型

### 新增 dependencies

```python
# services/api/src/uteki_api/auth/deps.py

async def optional_user(
    request: Request, db: Session = Depends(get_db)
) -> User | None:
    """匿名 OK；带合法 JWT 返 User，无 / 错 token 返 None。"""
    token = _extract_bearer(request)
    if not token:
        return None
    try:
        claims = decode(token)
    except InvalidTokenError:
        return None
    return await get_user(db, claims["sub"])

async def require_owner(
    user: User = Depends(current_user),  # 仍要求合法 token
) -> User:
    """非 owner 401。owner = email/github_login 在 allowlist 内。"""
    if not is_owner(user):
        raise HTTPException(403, "owner only")
    return user

def is_owner(user: User) -> bool:
    if user.email in settings.owner_emails_list:
        return True
    for ident in user.identities:
        if ident.provider == "github" and ident.provider_user_id in settings.owner_github_logins_list:
            return True
    return False
```

### Env 配置

```bash
# services/api/.env
OWNER_EMAILS=wyq5ycdkrqh1d@yahoo.com
OWNER_GITHUB_LOGINS=Rain1601
# 二者并集；至少配一个
```

OAuth callback 流程：identity upsert 后立即检查 `is_owner`：
- ✓ owner → 发 access token + refresh cookie，跳 `/console`
- ✗ 非 owner → 不发 token、删 identity（避免数据库残留），跳 `/`（公开首页）+ flash message

### Route 改造矩阵

| 路由 | 当前 dep | 改成 | 备注 |
|---|---|---|---|
| `GET /api/agents` | `current_user` | `optional_user` | prompt 字段脱敏 |
| `GET /api/agents/:name` | `current_user` | `optional_user` | 同上 |
| `GET /api/agents/:name/versions` | `current_user` | `optional_user` | 同上 |
| `GET /api/agents/:name/versions/:version` | `current_user` | `optional_user` | 同上 |
| `GET /api/runs` | `current_user` | `optional_user` | 按 visibility 过滤 |
| `GET /api/runs/:id` | `current_user` | `optional_user` | private → 404；unlisted/public → ok |
| `GET /api/runs/:id/artifacts/*` | `current_user` | `optional_user` | 继承 run.visibility |
| `POST /api/agent/chat` | `current_user` | `require_owner` | 触发新 run |
| `POST /api/runs/:id/visibility` | — (新) | `require_owner` | 单条切换 |
| `POST /api/runs/visibility/bulk` | — (新) | `require_owner` | 批量切换 |
| `POST /api/triggers/*` | `current_user` | `require_owner` | 配置触发器 |
| `POST /api/admin/reload-skills` | `current_user` | `require_owner` | 已是 admin 限 |
| `GET /api/evolution/proposals` | `current_user` | `require_owner` | proposal 是内部研发流程 |
| `POST /api/evolution/proposals/:id/approve` | `current_user` | `require_owner` | 同上 |
| `GET /api/evals/*` | `current_user` | `optional_user` | 公开只聚合 public runs |
| `POST /api/auth/register` | open | **删除** | 单 owner，禁止注册 |
| `GET /api/auth/oauth/:provider/start` | open | 保留 | OAuth 入口 |
| `GET /api/auth/oauth/:provider/callback` | open | 保留 | 但 callback 内校验 owner |
| `POST /api/auth/login` (email+pw) | open | **删除** | 没有非 owner 账号了 |

### Prompt 脱敏序列化层

新增 `api/_serialize.py`：

```python
def serialize_skill_version(v: SkillVersion, *, is_owner: bool) -> dict:
    data = v.model_dump()
    if not is_owner:
        prompt = data.pop("prompt", "")
        data["prompt"] = ""
        data["prompt_stats"] = {
            "lines": prompt.count("\n") + 1 if prompt else 0,
            "bytes": len(prompt.encode("utf-8")) if prompt else 0,
            "sha12": hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:12] if prompt else None,
        }
    return data

def serialize_proposal(p: Proposal, *, is_owner: bool) -> dict:
    data = p.model_dump()
    if not is_owner:
        data["baseline_prompt"] = ""
        data["candidate_prompt"] = ""
        data["ab_summary"].pop("diff", None)
    return data
```

所有相关 GET route 用这两个函数 wrap response。

## 前端结构

### 路由布局

```
apps/web/app/
├── (public)/                          ← NEW route group, no auth
│   ├── layout.tsx                     ← top-nav layout（uteki 标 / Runs / Skills / About / Sign in）
│   ├── page.tsx                       ← landing：hero + 最近 public runs feed + featured skills
│   ├── runs/page.tsx                  ← public runs 列表 + filter
│   ├── runs/[id]/page.tsx             ← 完整 trace replay（复用 components/agent/Trace）
│   ├── agents/page.tsx                ← skill 目录卡片
│   ├── agents/[name]/page.tsx         ← skill 公开页（public_description + tools + 最近 public runs）
│   └── about/page.tsx                 ← "uteki 是啥 / agent 框架介绍 / 投研边界"
│
├── (console)/                         ← 当前 (app) 改名
│   ├── layout.tsx                     ← server check owner，非 owner → redirect /
│   ├── page.tsx                       ← 现 dashboard
│   ├── runs/                          ← + visibility 控件 + 写按钮
│   ├── agents/                        ← + prompt 可见 + 版本回滚
│   ├── company-agent/                 ← 现 dossier 入口
│   ├── compare/
│   ├── evals/
│   └── admin/                         ← NEW
│       ├── triggers/page.tsx          ← 现 /tasks 迁过来
│       ├── proposals/page.tsx         ← self-evolution 审批
│       └── eval-cases/page.tsx        ← eval case 编辑
│
└── (auth)/
    └── login/page.tsx                 ← 简化：只 GitHub + Google 按钮（删 email+pw + 删 register）
```

### 共享组件

`components/agent/*` 全部不动——`Trace / Message / PlanCard / ToolCallCard / Artifacts / LogLine` 在两个 surface 都用，**它们物理上不 import `SkillVersion.prompt`**，所以天然安全。

### 关键防御

- `(public)/agents/[name]/page.tsx` 调 `GET /api/agents/:name` 拿到的 `prompt: ""`，组件不渲染 prompt 区块；只渲染 `public_description`
- `(console)/agents/[name]/page.tsx` 调同一个 API（但带 owner JWT），拿到完整 prompt，渲染 "view prompt" 折叠区块
- 两个 page.tsx 不共享代码——即使它们引同样的低层组件

### Visibility UI 控件

**`/console/runs` 列表**（owner-only 增强）：
- 行左 checkbox（多选）
- 行右 visibility chip（🌐 public / 🔗 unlisted / 🔒 private），点击 cycle
- 顶部 filter dropdown：`visibility: all / public / unlisted / private`
- 多选后 floating action bar：`Set N runs → [Public | Unlisted | Private]`

**`/console/runs/[id]` 详情**：
- header 区 segmented control 三档切换
- 切换发 `POST /api/runs/:id/visibility` → 乐观更新 UI

**`/` 公开列表**（anon 视角）：
- 没 checkbox、没 chip、没 filter、没 toggle
- 只看到 visibility=public 的 row，干净读者视角

## Sub-skill visibility 继承

当前架构：pipeline 跑 sub-skill 全在同一个 harness invocation 里，共享一条 `Run`。所以 visibility 自动覆盖整条 trace + 所有 artifact。**当前无需代码改动**。

未来若重构成 child Run 模型（按 sub-skill 单独计费 / 单独 trace replay），harness `_delegate` 入口加：

```python
async def _delegate(self, skill_name: str, messages, *, parent_run: Run):
    child_run = await default_run_store.create(
        user_id=parent_run.user_id,
        skill=skill_name,
        visibility=parent_run.visibility,  # 继承
        parent_run_id=parent_run.id,
    )
    ...
```

本 change 不做，只留注释。

## 部署形态

详细见 PR 5。骨架：

- 单 GCP project，启用 Cloud Run / Cloud SQL / Cloud Storage / Secret Manager / Cloud Build / Artifact Registry
- 2 个 Cloud Run service：`uteki-api`（FastAPI 容器）+ `uteki-web`（Next standalone build 容器）
- Cloud SQL Postgres db-f1-micro → SQLModel 接口已抽象，URL 切换即可
- Cloud Storage bucket → 写 `GCSArtifactStore`（继承现有 ArtifactStore ABC）
- 自定义域名映射，自动 TLS
- $299/年 plan 的 $550 GCP credit 覆盖个人规模流量约 30+ 月

## 部署前数据清理

- `rm -rf services/api/data/*`
- alembic migrate
- 启动期自动 `ensure_owner_user()` 从 OWNER_EMAILS 第一个 email 建 owner
- 首次访问 → 干净 prod 起点

## 跨 change 影响

- `001-tenant-and-auth`：本 change **改用法**（保留 user_id 分区，硬编码 owner.id），不改 schema
- `005-artifact-layer`：artifact 路径继承现状（`data/users/<user_id>/runs/<sha2>/<run_id>/...`），不变
- `006-pipeline`：harness `_delegate` 不动；如未来加 child Run 模型时再处理 visibility 继承
- `007-llm-judge`：proposal 数据脱敏新增字段，但 schema 不变
- `008-tool-governance`：tool registry 不动
- `009-company-deep-research-v2`：不影响

后续可以更新对应 specs/*/spec.md 来反映新约束（PR 5 时一并做）。
