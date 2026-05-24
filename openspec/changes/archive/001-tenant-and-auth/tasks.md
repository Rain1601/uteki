# 001 · Tasks

## Phase 1 — DB foundation

- [ ] **T1.1** 加依赖：sqlmodel、alembic、bcrypt、pyjwt
- [ ] **T1.2** `core/db.py` — engine + `get_db()` session 依赖
- [ ] **T1.3** alembic init，第一个 migration 建 user / auth_identity / refresh_token 三表
- [ ] **T1.4** `make db.migrate` / `make db.reset` 命令

## Phase 2 — User + Password auth

- [ ] **T2.1** `users/models.py` — User / AuthIdentity / RefreshToken SQLModel
- [ ] **T2.2** `users/store.py` — UserStore (create / get_by_email / list)
- [ ] **T2.3** `users/password.py` — bcrypt hash / verify
- [ ] **T2.4** `auth/jwt.py` — encode / decode / refresh rotation 含 family
- [ ] **T2.5** `auth/deps.py` — `current_user` dependency
- [ ] **T2.6** `api/auth.py` — register / login / refresh / logout / me
- [ ] **T2.7** smoke test: 注册 → 登录 → 拿 token → 调 `/api/me` 返自己

## Phase 3 — 现有 store 加 user_id

- [ ] **T3.1** Run 模型加 `user_id`；RunStore.list/get/create 全部加参数
- [ ] **T3.2** 把 InMemoryRunStore 切到 SqliteRunStore（events 用 JSON 列）
- [ ] **T3.3** `api/runs.py` 加 `Depends(current_user)`，过滤 `user_id=user.id`
- [ ] **T3.4** `api/agent.py` `chat` 把 user 传入 harness，harness 构造 Run 时填 user_id
- [ ] **T3.5** `api/compare.py` 同上
- [ ] **T3.6** `api/eval.py` 走 system user（eval 是平台级，不属于某人）
- [ ] **T3.7** memory 改 SqliteMemory，加 user_id 分区

## Phase 4 — Frontend 鉴权

- [ ] **T4.1** 把现有页面全部搬进 `app/(app)/`，加 `(app)/layout.tsx`：服务端读 cookie，无 user → redirect /login
- [ ] **T4.2** `app/(auth)/login/page.tsx` + `register/page.tsx`（暖深炭灰 editorial 风格延续）
- [ ] **T4.3** `lib/auth.ts` — token store / refresh hook / logout
- [ ] **T4.4** Sidebar 底部加 user pill（avatar + name + logout dropdown）
- [ ] **T4.5** 所有 `fetch` 加 `credentials: "include"`，401 自动 refresh
- [ ] **T4.6** `lib/api.ts` 的 fetch 用统一 wrapper 注入 Authorization header

## Phase 5 — OAuth

- [ ] **T5.1** `auth/oauth/github.py` — authorize URL 构造、callback 处理、CSRF state
- [ ] **T5.2** `api/auth.py` 加 `/oauth/github/{start,callback}`
- [ ] **T5.3** 前端 `/login` 加 "Continue with GitHub" 按钮
- [ ] **T5.4** Google 同上（`auth/oauth/google.py` + `/oauth/google/{start,callback}` + 按钮）
- [ ] **T5.5** dev 文档写清 GitHub / Google OAuth App 申请步骤

## Phase 6 — 落 spec

- [ ] **T6.1** `openspec/specs/auth/spec.md` — 鉴权契约 + token lifecycle + OAuth flow
- [ ] **T6.2** `openspec/specs/users/spec.md` — User / AuthIdentity 协议
- [ ] **T6.3** `openspec/specs/storage/spec.md` — store 接口 + user_id partition 约定
- [ ] **T6.4** 移到 archive
