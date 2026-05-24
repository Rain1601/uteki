# Users — spec

> 创建于 2026-05-25 · 落地 M4（change 001-tenant-and-auth）

## 数据模型（SQLModel）

```python
class User(SQLModel, table=True):
    id: str = Field(primary_key=True)        # uuid4().hex[:12]
    email: str = Field(unique=True, index=True)
    display_name: str = ""
    avatar_url: str | None = None
    created_at: datetime
    status: str = "active"                   # "active" | "suspended"

class AuthIdentity(SQLModel, table=True):
    id: str = Field(primary_key=True)
    user_id: str = Field(foreign_key="user.id", index=True)
    provider: str                            # "password" | "github" | "google"
    provider_user_id: str = Field(index=True)
    password_hash: str | None = None         # 只 provider=="password" 时填
    created_at: datetime
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

class RefreshToken(SQLModel, table=True):
    jti: str = Field(primary_key=True)       # 24-hex
    user_id: str = Field(foreign_key="user.id", index=True)
    family_id: str = Field(index=True)       # 32-hex；rotation 时同 family 复用
    issued_at: datetime
    expires_at: datetime
    revoked: bool = False
```

## 不变量

- `User.email` 全局唯一（应用层 + DB unique 约束双保险）
- 一个 User 可挂 N 个 AuthIdentity，但 `(provider, provider_user_id)` 全局唯一
- 一个 User 只能有 **0 个或 1 个** provider=`"password"` 的 AuthIdentity（应用层强制；DB 没法表达）
- `RefreshToken.family_id` 在一个 family 被 revoke 后**所有**行都 `revoked=True`（rotation 重放保护）

## Reserved user

`demo@local` 是平台 reserved。任何注册 / OAuth 上来想拿这个 email 的请求都 400 拒绝。该 user 由 `ensure_demo_user(db)` 在 API 启动时幂等创建，用于 `UTEKI_AUTH_REQUIRED=false` 的 dev 兜底。

`user_id="system"` 是另一种保留值（**字符串**，不是 User row）—— platform-level 跑的活（drift_monitor、定时 eval、单元测试）拿它作为 partition key。`system` 没有对应的 User row，任何 `Authorization: Bearer` 都解不出这个 sub。

## UserStore 接口

```python
class UserStore(ABC):
    async def create(user: User) -> None
    async def get(user_id: str) -> User                # raises KeyError
    async def get_by_email(email: str) -> User | None
```

`SqlUserStore` 是当前唯一实现，背后 SQLite/SQLModel。接口隔离的目的是未来切 Postgres 只改实现 + URL。

## Identity 合并语义

完整流程见 `auth/spec.md → upsert_user_from_identity`。这里只列不变量：

- 同 `(provider, provider_user_id)` 永远落到同一个 User
- 同 email 永远合并到同一个 User
- 永不创建第二个孤儿 User

## 输出形状（API）

`UserOut` (Pydantic):
```json
{
  "id": "fd217b556aa0",
  "email": "alice@test.com",
  "display_name": "Alice",
  "avatar_url": null,
  "created_at": "2026-05-24T17:39:01.344302",
  "status": "active"
}
```

`password_hash` / `AuthIdentity` / `RefreshToken` 永不外露。
