# 001 · 多租户 + 用户系统

## Problem

uteki 当前所有数据无 owner：runs、watchlist、tasks、memory 全部全局共享。无法支持多用户使用、无法做 SaaS、无法做合规留痕、无法支持 GitHub / Google 登录。

## Solution

引入 User + AuthIdentity 模型；为所有 user-owned 数据加 `user_id` 列；所有 API 路由通过 FastAPI `Depends(current_user)` 强制鉴权；前端拆 `(auth)` / `(app)` 两个路由组。

支持的登录方式（按优先级）：

1. 邮箱 + 密码
2. GitHub OAuth
3. Google OAuth

一个 User 可绑多个 Identity（同邮箱即合并）。

## Non-goals

- **不**实现完整 RBAC / 权限组。MVP 只有"自己看自己数据"
- **不**实现 SSO / SAML / OIDC enterprise
- **不**实现密码找回邮件流程（先打"管理员重置"占位）
- **不**实现 MFA / 2FA

## 依赖

无。是其他 change 的前置（memory v2 / curator 等都需要 user 作为 partition key）。

## Risks

- **现有数据无 owner**：迁移期所有现存 run / watchlist 归到 dev user "demo@local"。生产部署前需要清空。
- **CORS + cookie**：refresh token 走 httpOnly cookie，需要 SameSite / Secure 配置；前后端跨域要先调通。
- **OAuth 回调 URL**：dev 本地是 `http://localhost:3000`，prod 是真实域名，需要环境变量切换。
