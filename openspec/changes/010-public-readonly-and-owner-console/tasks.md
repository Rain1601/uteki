# 010 · Tasks

## PR 1 — Backend: visibility + permissions + prompt protection（~8h）

### Phase 1.1 · data model + migration
- [ ] **T1.1** `runs/models.py` 加 `visibility: str = Field(default="private", index=True)` + Literal type guard
- [ ] **T1.2** alembic migration：加列 + 加索引
- [ ] **T1.3** `runs/store.py` SqliteRunStore.list 加 `visibility_filter: str | None = None` 参数 + WHERE 子句
- [ ] **T1.4** `runs/store.py` 加 `set_visibility(run_id, user_id, visibility)` method

### Phase 1.2 · auth dependencies
- [ ] **T1.5** `auth/deps.py` 新增 `optional_user()`（无 / 错 token 返 None）
- [ ] **T1.6** `auth/deps.py` 新增 `require_owner()`（非 owner 403）+ `is_owner()` helper
- [ ] **T1.7** `core/config.py` 加 `owner_emails: str` + `owner_github_logins: str` env，list-property helpers
- [ ] **T1.8** `users/store.py` 加 `ensure_owner_user()`（启动期跑，从第一个 owner email 建用户）
- [ ] **T1.9** lifespan 用 `ensure_owner_user()` 替换 `ensure_demo_user()`

### Phase 1.3 · route 迁移
- [ ] **T1.10** 所有现有 GET routes（agents / runs / artifacts / evals / compare）从 `current_user` 换 `optional_user`，内部按 is_owner 决定过滤逻辑
- [ ] **T1.11** 所有 mutation routes（agent/chat / triggers / admin / evolution / runs visibility）换 `require_owner`
- [ ] **T1.12** `api/runs.py` 新增 `POST /:id/visibility`（单条）+ `POST /visibility/bulk`（多条）
- [ ] **T1.13** `api/runs.py` GET routes 的 visibility 过滤 + 404 逻辑（private + anon → 404）
- [ ] **T1.14** `api/artifacts.py` 先 lookup parent run，按 run.visibility 决定 access

### Phase 1.4 · 序列化层 prompt 脱敏
- [ ] **T1.15** 新建 `api/_serialize.py`：`serialize_skill_version(v, *, is_owner)` + `serialize_proposal(p, *, is_owner)`
- [ ] **T1.16** `api/agents.py` 所有 GET 用 `serialize_skill_version` wrap response
- [ ] **T1.17** `api/evolution.py` 所有 proposal GET 用 `serialize_proposal` wrap
- [ ] **T1.18** Audit harness：grep `system_prompt` 在 `agents/harness.py` 和 `runs/store.py` 出现的位置，确认 events 落盘**不存 system message**（必要时修）

### Phase 1.5 · public_description
- [ ] **T1.19** `skills/registry.py` 给 `SkillEntry` 加 `public_description: str = ""` 字段 + `to_dict()` 暴露
- [ ] **T1.20** `skills/__init__.py` 给 10 个 skill 全部写好 `public_description`（技术准确风格，列流程 + 工具 + 模型 + 产物）

### Phase 1.6 · 删 register
- [ ] **T1.21** 删 `POST /api/auth/register` route + 相关 schema
- [ ] **T1.22** 删 `POST /api/auth/login`（email+pw）route — OAuth-only
- [ ] **T1.23** OAuth callback 内加 owner check：成功 → token + redirect `/console`；失败 → delete identity + redirect `/?error=not_owner`

### Phase 1.7 · 测试
- [ ] **T1.24** `tests/e2e/test_visibility_filtering.py`：private run / unlisted / public，匿名访问的 3 种行为
- [ ] **T1.25** `tests/e2e/test_owner_allowlist.py`：non-allowlist OAuth callback → no token issued
- [ ] **T1.26** `tests/e2e/test_prompt_redaction.py`：anon GET skill version → prompt empty，owner → full
- [ ] **T1.27** `tests/e2e/test_bulk_visibility.py`：批量 endpoint
- [ ] **T1.28** 跑 `./scripts/e2e.sh` 确认 81+ 个 case 全过


## PR 2 — Console UI: 改名 + visibility 控件 + isOwner gating（~4h）

- [ ] **T2.1** `apps/web/app/(app)/` 整目录 mv 到 `apps/web/app/(console)/`
- [ ] **T2.2** 所有现有 page 的 internal link `/runs/...` `/agents/...` 等加 `/console` 前缀（grep+sed）
- [ ] **T2.3** `(console)/layout.tsx` server-side fetch `/api/auth/me`，非 owner → `redirect("/")`
- [ ] **T2.4** `lib/auth.ts` 暴露 `useAuth()` hook 返 `{ user, isOwner }`
- [ ] **T2.5** `(console)/runs/page.tsx` 加 checkbox 多选列 + 顶部 filter 下拉 + bulk action bar
- [ ] **T2.6** 复用 / 新建 `components/ui/VisibilityChip.tsx`：3 档 chip + onChange callback
- [ ] **T2.7** `(console)/runs/[id]/view.tsx` header 加 segmented control（3 档）
- [ ] **T2.8** 所有写按钮（Trigger / Re-run / Edit / Approve / Visibility toggle）外层加 `{isOwner && (...)}`
- [ ] **T2.9** `(console)/agents/[name]/page.tsx` 保持现状（prompt 渲染保留）
- [ ] **T2.10** 现 `/tasks` page 路径移到 `/console/admin/triggers`，加面包屑


## PR 3 — Public surface（~8h）

- [ ] **T3.1** 新建 `apps/web/app/(public)/layout.tsx`：顶 nav（uteki / Live runs / Skills / About / Sign in），无 sidebar
- [ ] **T3.2** `(public)/page.tsx` 落地：hero copy + 最近 5-10 个 public runs 实时 feed + featured skills
- [ ] **T3.3** `(public)/runs/page.tsx`：public runs 列表（filter by skill + ticker + status），无写控件
- [ ] **T3.4** `(public)/runs/[id]/page.tsx`：复用 `components/agent/Trace.tsx` 渲染 events + artifacts；无 visibility / 写按钮；header 写"Read-only · view source on GitHub"
- [ ] **T3.5** `(public)/agents/page.tsx`：skill 卡片 grid，链到 `/agents/[name]`
- [ ] **T3.6** `(public)/agents/[name]/page.tsx`：渲染 `public_description`（非 `prompt`）+ tools + model + 最近 public runs
- [ ] **T3.7** `(public)/about/page.tsx`：手写一段「uteki 是啥、为什么做、agent 框架介绍、研究边界声明」
- [ ] **T3.8** `(public)/layout.tsx` 顶 nav 的 "Sign in" 按钮 → `/login`（OAuth-only），登录成功跳 `/console`
- [ ] **T3.9** root `/` page.tsx → 重定向到 `(public)/page.tsx`（route group 不影响 URL，但要确保默认 `/` 指公开首页）
- [ ] **T3.10** `(public)` 所有 page 加 `<meta name="robots" content="..." />` —— 公开 runs 允许 indexable，admin / login 加 noindex


## PR 4 — Public surface polish + SEO + copy（~4h）

- [ ] **T4.1** `(public)/layout.tsx` 加 footer：copyright / 框架 GitHub link / "Last deployment: <date>"
- [ ] **T4.2** Landing hero：bespoke 文案（不是 console 那套 editorial "Trigger.Harness.Skill.Run."），改成 outsider-friendly 的 "An investment-research agent that <does X>"
- [ ] **T4.3** Featured-skill cards in landing：手 curate 3-4 个最值得展示的 skill（company_research_pipeline / earnings / research）
- [ ] **T4.4** Real-time runs feed：用 `useEffect` poll 或 SSE 拉新 public runs，10s 一次刷新
- [ ] **T4.5** Open Graph meta：每个 public run 详情页带 OG title + description（"NVDA Q4 investment memo by uteki · 2026-06"）+ thumbnail
- [ ] **T4.6** Sitemap.xml + robots.txt
- [ ] **T4.7** About 页加 "Agent capabilities" matrix（哪些 skill / tools / 数据源）+ "What you won't see"（明确告知 prompt 不公开 + 私密 runs 不公开）


## PR 5 — GCP 部署（~4h）

- [ ] **T5.1** Dockerfile for `services/api/` (Python 3.13 + uv + uvicorn standalone)
- [ ] **T5.2** Dockerfile for `apps/web/` (Node + pnpm + Next standalone build)
- [ ] **T5.3** `cloudbuild.yaml`：push to main → build 2 images → push Artifact Registry → deploy 2 Cloud Run services
- [ ] **T5.4** 新建 `services/api/src/uteki_api/artifacts/gcs_store.py`（继承 `ArtifactStore` ABC，用 `google-cloud-storage` SDK）
- [ ] **T5.5** `STORAGE_BACKEND=gcs` env 触发用 GCS 替代 LocalFileArtifactStore
- [ ] **T5.6** 切 Postgres：`DATABASE_URL=postgresql+pg8000://...`，alembic upgrade head 一次
- [ ] **T5.7** Secret Manager 挂：`UTEKI_JWT_SECRET` / `GITHUB_CLIENT_SECRET` / `GOOGLE_CLIENT_SECRET` / `OWNER_EMAILS` / `OWNER_GITHUB_LOGINS` / `ANTHROPIC_API_KEY` / `DEEPSEEK_API_KEY`
- [ ] **T5.8** OAuth callback URLs 在 GitHub / Google console 加 prod 域名
- [ ] **T5.9** 自定义域名 → Cloud Run 域名映射（自动 TLS）
- [ ] **T5.10** Cloud Run 实例 min=0（scale to zero），max=10
- [ ] **T5.11** 部署前 cleanup：`rm -rf data/` + 跑 alembic 重建 schema
- [ ] **T5.12** Smoke test：访问 `/` 看到 landing；登录走 GitHub OAuth 成功跳 `/console`；triggers 一次 run；run 在 `/console/runs` 出现；标 public → 出现在 `/runs`；anon 直接访问能看见


## 验收（V）

- [ ] **V1** 匿名访问 `uteki.com/runs/private-id` → 404
- [ ] **V2** 匿名访问 `uteki.com/runs/unlisted-id` → 完整可读
- [ ] **V3** 匿名访问 `uteki.com/runs` → 列表只有 public，不含 unlisted
- [ ] **V4** 匿名访问 `uteki.com/agents/research` → 看到 `public_description`，看不到 SKILL.md 文本
- [ ] **V5** Owner GitHub OAuth 登录 → 跳 `/console`，能看到全部 run / prompt / 写按钮
- [ ] **V6** 非 owner GitHub login（任何其他 GitHub 账号）→ callback 后不发 token，跳 `/?error=not_owner`
- [ ] **V7** Owner 在 `/console/runs` 多选 5 个 → bulk 切 public → 5 个秒切 + 立刻出现在 `/runs`
- [ ] **V8** 网络 inspector 检查匿名 `GET /api/agents/research`：response body 里 `prompt: ""` 而非全文
- [ ] **V9** `./scripts/e2e.sh` 全部 81+ case 过
- [ ] **V10** `pnpm typecheck` 干净
- [ ] **V11** GCP 部署：访问 `https://<your-domain>/` 返公开 landing；`https://<your-domain>/console` 未登录 → redirect login
- [ ] **V12** $5 cost budget 设好（GCP Billing Budget），任何超额触发邮件 alert


## 时间盒估算

| PR | 估时 | 拆 commit 数 |
|---|---|---|
| PR 1 | 8h | 7-8 commits（按 Phase 拆）|
| PR 2 | 4h | 3-4 commits |
| PR 3 | 8h | 4-5 commits |
| PR 4 | 4h | 3-4 commits |
| PR 5 | 4h | 5-6 commits |
| **合计** | **28h ≈ 3.5 工作日** | ~25 commits |
