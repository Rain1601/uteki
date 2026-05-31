# Auth — spec

> 创建于 2026-05-25 · 落地 M4（change 001-tenant-and-auth）

## Token 模型

两种 JWT，HS256 共享密钥 `UTEKI_JWT_SECRET`（≥ 32 char）：

| 名字 | TTL | 转运 | claims |
|---|---|---|---|
| **access** | 15 min | `Authorization: Bearer <token>` | `{sub:user_id, iat, exp, jti, kind:"access"}` |
| **refresh** | 30 day | Set-Cookie `uteki_refresh`，httpOnly + SameSite=Lax，Secure 在 prod | `{sub, exp, jti, family, kind:"refresh"}` |

claim 的 `kind` 是反向滥用防线 —— `decode_access` 拒绝任何非 `"access"`，反之亦然，避免 refresh 被当 access 用。

## 端点

```
POST   /api/auth/register     { email, password, display_name? }
                              → 200 { access_token, token_type, user } + Set-Cookie refresh
POST   /api/auth/login        { email, password }
                              → 200 同上
POST   /api/auth/refresh      cookie:uteki_refresh
                              → 200 { access_token } + Set-Cookie refresh（rotated）
POST   /api/auth/logout       cookie:uteki_refresh
                              → 204 + Clear-Cookie
GET    /api/auth/me           Authorization: Bearer
                              → 200 UserOut

GET    /api/auth/oauth/{github|google}/start?next=/path
                              → 302 to provider
GET    /api/auth/oauth/{github|google}/callback?code&state
                              → 302 /oauth/{provider}/callback#access_token=...&next=<next>
                              + Set-Cookie refresh
```

### 错误形状

| 场景 | code | detail |
|---|---|---|
| Bad password / unknown email | 401 | `"invalid email or password"`（**两种统一同一句**，杜绝 email 枚举） |
| 注册重复 email | 409 | `"email already registered"`（Conflict —— REST 标准比 400 更准） |
| 注册 reserved email `demo@local` | 422 | Pydantic `EmailStr` 拦截（缺 TLD），永远走不到 handler 里的 reserved 检查；handler 检查保留作 defense-in-depth |
| Refresh cookie 缺失 | 401 | `"missing refresh cookie"` |
| Refresh token 已 revoked / 不存在 / 过期 | 401 | `"token replay detected; family revoked"` 或 `"unknown refresh"` 或 `"refresh expired"` |
| Invalid Bearer (decode 失败 / kind 错 / sub 缺) | 401 | `"invalid token"` 或 `"not an access token"` —— **永远不回带 PyJWT 内部错误文本**（曾经会泄漏 codec / 结构信息） |
| 无 Bearer 且 `auth_required=True` | 401 | `"missing bearer token"` |
| User suspended | 403 | `"account status: <status>"` |

## Refresh 轮转 + Family 防重放

策略：**单次使用 + family detection**。

1. `issue_refresh(user_id)` 创建新 `family_id = uuid4().hex`，写 `RefreshToken(jti, user_id, family_id, expires_at, revoked=False)`，签 JWT `{sub, exp, jti, family, kind:"refresh"}`
2. `rotate_refresh(old)`：
   - decode → 取 `(jti, family_id)`
   - DB lookup by jti
     - 不存在 → `InvalidRefresh("unknown refresh")`
     - `revoked==True` → **重放检测**：`UPDATE refresh_token SET revoked=true WHERE family_id=<family>`（family 全部烧掉），raise `InvalidRefresh("refresh token reuse — family revoked")`
     - 过期 → revoke 该行，raise
     - 否则 → revoke 旧行，`issue_refresh(user_id, family_id=<family>)` 在同 family 内发新 token
3. `revoke_refresh(token)` (logout)：silent，单行 revoke

可观察的攻击模型：攻击者通过 XSS / cookie 偷到 refresh1 → 攻击者 refresh → 拿到 refresh2，原合法 client 当 access 过期再 refresh refresh1 → server 看到 revoked → 烧 family → 攻击者的 refresh2 也作废 + 合法 client 也作废。两边都被踢出 → 用户必须重登 → 异常立刻可见。

## OAuth (GitHub / Google)

### State CSRF（无状态 HMAC）

`make_state(next_url)` 签 `<b64(payload)>.<b64(sig)>`，payload = `{"n": next_url, "t": iat}`，sig = HMAC-SHA256(jwt_secret, b64(payload))。

`verify_state(state)`：
- 拆 `<payload>.<sig>` → b64-decode → HMAC compare_digest
- `iat` 与当前时间差 > 10 min → 拒绝
- 任何字段缺失 / 解码失败 / 签名不匹配 → `ValueError`

为什么不用 server-side session：状态 ≤ 10 min，存储几乎没用；signed token 自证、零 DB 写、CDN 友好。

### Provider 抽象

每个 provider 实现：
```python
def configured() -> bool                                  # 是否填了 client_id+secret
def callback_url() -> str                                 # f"{oauth_redirect_base}/api/auth/oauth/{p}/callback"
def authorize_url(state: str) -> str                      # 302 目标
async def exchange_code(code: str) -> str                 # 拿 provider access_token
async def fetch_user(access_token: str) -> ProviderUser   # 含 provider_user_id / email / name / avatar_url
```

GitHub 额外细节：当 user 邮箱不公开时，调 `GET /user/emails` 取 `primary && verified`。
Google 用 OIDC userinfo endpoint，`sub` 即 `provider_user_id`。

### upsert_user_from_identity

合并策略（按优先顺序）：

1. `(provider, provider_user_id)` 匹配现有 AuthIdentity → 用其 user，刷新 cosmetic（display_name 留空才更新，avatar_url 总是覆盖以保持新鲜）
2. provider 给的 email 命中 User.email → 在该 user 下新增 AuthIdentity（同邮箱即合并）
3. 都没有 → 新建 User + AuthIdentity，display_name = provider.name 或 email 前缀

**不会**因为 OAuth 登录创建第二个孤儿 User —— 同邮箱永远合并。

## current_user 依赖

```python
async def current_user(request, db) -> User:
    # 1. Authorization: Bearer <access_token> → decode → User
    # 2. 无 header 且 settings.auth_required=False → ensure_demo_user(db)
    # 3. 否则 → 401 "auth required"
```

`optional_user` 同语义但 401 / 缺失 token 返 `None`。

`ensure_demo_user(db)` 是幂等的：第一次 boot 时创建 `demo@local`（status=active，无 password_hash），之后每次 fast path lookup。

## Reader / Admin / Local Full Access

当前权限分成两层：

- `role`：持久身份标签，当前只使用 `reader | admin`。
- `permissions`：本次请求实际可做的动作，由后端输出给前端。

`reader` 默认拥有：

- `results:view`
- `trace:view`

`admin` 默认拥有：

- `results:view`
- `trace:view`
- `agent:operate`
- `agent:company_research`
- `admin:*`

`UTEKI_LOCAL_ALL_PERMISSIONS=true` 会让当前调用者获得完整 `permissions`，但不改写持久化 `role`。这只用于本地开发；生产环境应保持 `false`，并用 `UTEKI_ADMIN_EMAILS` / `UTEKI_ADMIN_GITHUB_LOGINS` / `UTEKI_ADMIN_GITHUB_IDS` 显式授予 admin。

当 `UTEKI_AUTH_REQUIRED=false` 且未显式配置 `UTEKI_LOCAL_ALL_PERMISSIONS` 时，本地默认启用完整 permissions，方便调试 agent 运行。

后续订阅功能不应把订阅用户提升为 `admin`。订阅应作为独立 entitlement / tier 扩展 read scope，例如扩大可查看 run、artifact、历史范围、source detail 或高阶报告章节；操作 agent 和 admin 工具仍由 `agent:operate` / `admin:*` 控制。

### Agent Permission Map

API 层通过 `AGENT_PERMISSION_MAP` 做 agent 级授权。默认规则：

- 大多数 skill 使用通用 `agent:operate`。
- 当某个 skill 同时满足以下任一条件时，可以拆出专用 permission：
  - 运行成本显著高于普通 agent，或会消耗更高预算配额。
  - 输出是产品化 / tier-gated 报告，需要独立售卖或限额。
  - 涉及更高监管、投资决策、数据供应商许可或审计要求。
  - 前端需要把入口、历史记录、artifact 访问与普通 agent 分开授权。
- 专用 permission 必须只在后端 `AGENT_PERMISSION_MAP` 中作为权威判定；前端只能用 `/api/auth/me.permissions` 隐藏或禁用入口，不能作为安全边界。

`company_research_pipeline -> agent:company_research` 是第一条专用映射：
它会生成完整公司研究档案、调用多数据源并产出可审计 artifact，天然适合作为
后续订阅 / tier gating 的独立能力。`research_pipeline` 继续走
`agent:operate`，因为它仍属于通用研究链路。

## 安全要点

- bcrypt cost = 12（`bcrypt.gensalt(rounds=12)`）
- `verify_password` 永不抛异常 —— bad input / corrupt hash 一律返 `False`，避免 timing oracle 区分错误模式
- jwt_secret 必须 ≥ 32 char，配置层 (`core/config.py`) 校验
- prod 必须开 `Secure` cookie + HTTPS frontend（`UTEKI_FRONTEND_BASE=https://...`）
- access token 永远不持久化到 localStorage（前端只放 sessionStorage 镜像，给同 tab 客户端导航用）；refresh 永远 httpOnly cookie

## 不在本 spec

- 密码找回邮件 / MFA / 邮箱验证（明确 non-goal，见 change 001 proposal）
- 团队 workspace / 邀请（M4 后续 change）
- SAML / 企业 SSO
