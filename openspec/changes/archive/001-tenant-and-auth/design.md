# 001 · Design

## 持久化：SQLite + SQLModel

dev / 小规模 prod 用 SQLite；切 Postgres 时改 URL 即可。

```
data/uteki.db                    # 单文件数据库
services/api/src/uteki_api/core/db.py   # engine + session 工厂
```

依赖加：
```toml
sqlmodel >= 0.0.22
alembic >= 1.13
bcrypt >= 4.2
pyjwt >= 2.10
httpx[http2] >= 0.27   # 已有
```

## 数据模型

```python
class User(SQLModel, table=True):
    id: str = Field(primary_key=True)               # uuid7
    email: str = Field(unique=True, index=True)
    display_name: str
    avatar_url: str | None = None
    created_at: datetime
    status: Literal["active", "suspended", "deleted"] = "active"

class AuthIdentity(SQLModel, table=True):
    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    provider: Literal["password", "github", "google"]
    provider_user_id: str = Field(index=True)        # email / github sub / google sub
    password_hash: str | None = None
    created_at: datetime
    # 唯一约束: (provider, provider_user_id)

class RefreshToken(SQLModel, table=True):
    jti: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    issued_at: datetime
    expires_at: datetime
    revoked: bool = False
    family_id: str                                    # 用于 rotation 检测重放
```

## 现有 store 改造

所有 in-memory store 改成 SQLite-backed，加 `user_id` 字段：

| Store | 加字段 | 改的接口 |
|---|---|---|
| `RunStore` | `user_id` | `list(user_id, skill, triggered_by)` / `get(user_id, id)` |
| `InMemoryMemory` → `SqliteMemory` | `user_id` + `session_id` | 全部加 `user_id` 参数 |
| `EvolutionStore` | **不加** | skill 版本仍全局 |

watchlist / tasks 现在是前端 demo 数据，落后端时也按 user_id 建表。

## JWT

```
access  · HS256 · 15 min · payload {sub, exp, jti, scope}
refresh · HS256 · 30 day · 存 cookie (httpOnly, Secure, SameSite=Lax)
```

rotation：每次 `/api/auth/refresh` 用旧 refresh 发新 refresh + 新 access；旧 refresh 立刻 revoke。
family detect：refresh 携带 `family_id`，若同 family 的旧 refresh 被复用（已 revoke 仍来用） → 撤销整个 family（视为被盗）。

## OAuth flow

### GitHub

```
1. 前端 GET /api/auth/oauth/github/start?next=/dashboard
   → 302 https://github.com/login/oauth/authorize?client_id=...&state=<csrf>&scope=user:email
2. GitHub 回 /api/auth/oauth/github/callback?code=...&state=...
3. 后端：
   a. 校验 state (CSRF)
   b. POST code → access_token
   c. GET https://api.github.com/user + /user/emails
   d. upsert AuthIdentity(provider=github, provider_user_id=<github user id>)
   e. 若同邮箱已有 User → 关联；否则建 User
   f. 颁发 access + refresh，set-cookie，302 → next
```

### Google

OAuth 2.0 + OpenID Connect。沿用同样的 upsert 逻辑，identity provider 字段不同。

## FastAPI 鉴权依赖

```python
async def current_user(
    request: Request,
    db: Session = Depends(get_db),
) -> User:
    token = (
        request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        or _get_dev_user_fallback(request)
    )
    if not token:
        raise HTTPException(401, "missing token")
    try:
        claims = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
    except jwt.InvalidTokenError:
        raise HTTPException(401, "invalid token")
    user = db.get(User, claims["sub"])
    if user is None or user.status != "active":
        raise HTTPException(401, "user not found")
    return user
```

`UTEKI_AUTH_REQUIRED=false` 走 dev 兜底 user `demo@local`。

## 前端路由组

```
apps/web/app/
├── (auth)/                       # 不含 shell
│   ├── login/page.tsx
│   ├── register/page.tsx
│   └── oauth/[provider]/callback/page.tsx   # 接 cookie 并跳 next
├── (app)/                        # 含 shell，需登录
│   ├── layout.tsx                # 服务端读 cookie，无 user → redirect /login
│   ├── page.tsx                  # 现 / 搬进来
│   ├── watchlist/...
│   ├── tasks/...
│   ├── runs/...
│   └── ...所有现有页面
└── api/
    └── auth/                     # Next route handlers，仅做 cookie 中转
```

Sidebar 底部 Pin 按钮**上方**新增 user pill（avatar + name + logout）。

## 环境变量新增

```bash
UTEKI_DB_URL=sqlite:///data/uteki.db
UTEKI_JWT_SECRET=<32+ char random>
UTEKI_AUTH_REQUIRED=true
UTEKI_GITHUB_CLIENT_ID=
UTEKI_GITHUB_CLIENT_SECRET=
UTEKI_GOOGLE_CLIENT_ID=
UTEKI_GOOGLE_CLIENT_SECRET=
UTEKI_OAUTH_REDIRECT_BASE=http://localhost:8000
```
