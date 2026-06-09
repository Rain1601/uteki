# 012 · Tasks

5 PR × ~1 工作日。每个 PR 独立可发、独立可 rollback。PR α/β/γ 是技术准备；PR δ/ε 是发布动作。

## PR α — GCSArtifactStore + STORAGE_BACKEND（~1 day）

> 引入第二个 `ArtifactStore` 实现，让本地 dev 行为 100% 不变，prod 通过 env 切换。

### α.1 · 依赖 + skeleton

- [ ] **Tα1** 给 `services/api/pyproject.toml` 加 `google-cloud-storage>=2.18`
- [ ] **Tα2** `uv lock` + commit lockfile
- [ ] **Tα3** 新建 `services/api/src/uteki_api/artifacts/gcs_store.py` —— 继承 `ArtifactStore` ABC，骨架 + docstring 说明 layout 等价 LocalFile

### α.2 · 实现 GCSArtifactStore

- [ ] **Tα4** `_blob_path(run_id, name, user_id)` 复用 LocalFile 的 sha2 分片 + user partition 计算，返 `users/<uid>/runs/<sha2>/<run_id>/artifacts/<name>` 字符串
- [ ] **Tα5** `_manifest_blob_path(...)` 同理
- [ ] **Tα6** `write(...)` 实现：复用 LocalFile 的 `_strip_preamble` + `_validate_name` 校验路径；`blob.upload_from_string(body, content_type=content_type_for(kind))`；upsert manifest blob（last-write-wins，与 LocalFile 同语义）
- [ ] **Tα7** `read(...)` 实现：`blob.download_as_bytes()` + manifest blob 读取；不存在抛 `FileNotFoundError`（同 LocalFile 行为）
- [ ] **Tα8** `list(...)` 实现：读 manifest blob → parse JSON → 返 `Artifact` 列表
- [ ] **Tα9** `exists(...)` 实现：`blob.exists()`

### α.3 · backend 选择

- [ ] **Tα10** `core/config.py` 加 `storage_backend: str = "fs"` + `gcs_bucket: str = ""` 字段 + `UTEKI_STORAGE_BACKEND` / `UTEKI_GCS_BUCKET` env 绑定
- [ ] **Tα11** `artifacts/__init__.py` 加 `_build_default_store()` factory；`UTEKI_STORAGE_BACKEND=gcs` 走 GCSArtifactStore，否则 LocalFile
- [ ] **Tα12** `default_artifact_store` 改成 factory 返值

### α.4 · 测试

- [ ] **Tα13** 加 `services/api/tests/artifacts/test_gcs_store.py` —— 用 `google-cloud-storage` 的 `gcs-emulator` 或者 mock client：覆盖 write / read / list / exists 4 条 happy path + 跨 user 隔离 1 条
- [ ] **Tα14** 加 `services/api/tests/artifacts/test_store_parity.py` —— 同一份 input 走 LocalFile 和 GCS 两个 store，结果 byte-identical（manifest sort 后比较）
- [ ] **Tα15** 跑 `./scripts/e2e.sh` 确认 LocalFile path 全部通过（默认 backend 不变）

### α.5 · 验收

- [ ] **Vα1** 本地 `UTEKI_STORAGE_BACKEND=fs` 跑 → 用 `data/runs/...` 路径
- [ ] **Vα2** 本地 `UTEKI_STORAGE_BACKEND=gcs` + emulator 跑 → 用 gs:// 路径
- [ ] **Vα3** GCS 跨 user 读 → `FileNotFoundError` → API 404
- [ ] **Vα4** `pnpm typecheck` 干净（无 web 改动）


## PR β — Postgres + Cloud SQL connector + alembic（~1 day）

> 把 SQLite 当作 dev 子集对待；prod 跑 Postgres。引入 alembic 收摄 inline ALTER。

### β.1 · 依赖

- [ ] **Tβ1** `pyproject.toml` 加 `pg8000>=1.31` + `alembic>=1.13`
- [ ] **Tβ2** `uv lock` + commit

### β.2 · dialect compatibility audit

- [ ] **Tβ3** grep `services/api/` 所有 raw SQL（`text(...)` / `execute(...)` / `executescript(...)`）—— 列清单
- [ ] **Tβ4** 对照 §3.3 表过一遍，标 SQLite-only / 通用：当前已知是 0 处 SQLite-only，但需要确认
- [ ] **Tβ5** 若发现 `INSERT OR REPLACE` / `AUTOINCREMENT` / `pragma` 等 SQLite 专属：改成 SQLAlchemy ORM 写法或写两条 dialect 分支

### β.3 · alembic 引入

- [ ] **Tβ6** `services/api/alembic.ini` + `services/api/alembic/env.py` + 空 `versions/` 目录
- [ ] **Tβ7** `alembic revision -m "001_initial"` —— autogenerate 第一个 revision，包含当前 `SQLModel.metadata` 所有表 + 索引
- [ ] **Tβ8** 手动 review 生成的 migration，删除不必要 default 重声明
- [ ] **Tβ9** `alembic upgrade head` 在空 SQLite 上验证生成 schema 与 `SQLModel.metadata.create_all` 一致
- [ ] **Tβ10** `core/db.py:init_db()` 改成调 `alembic upgrade head`（保留 `_ensure_*_column` 作 fallback 一个 release cycle，但日志降级到 WARNING）

### β.4 · connection pool 配置

- [ ] **Tβ11** `core/db.py:_make_engine()` 给 Postgres URL 加 `pool_size=2, max_overflow=0, pool_recycle=1800, pool_pre_ping=True`；SQLite 维持现状
- [ ] **Tβ12** Cloud SQL unix socket URL 解析（`postgresql+pg8000://user:pass@/db?host=/cloudsql/<conn>`）跑通本地 dry-run

### β.5 · 测试

- [ ] **Tβ13** 加 `services/api/tests/conftest_postgres.py` —— optional postgres fixture，需 `UTEKI_TEST_DB_URL=postgresql://...` 才启动
- [ ] **Tβ14** 加 `services/api/tests/e2e/test_postgres_smoke.py` —— 跑 1 个 register + 1 个 chat run，验证 RunStore 在 Postgres 上工作
- [ ] **Tβ15** `make test.postgres`：拉本地 Postgres docker → `alembic upgrade head` → 跑 e2e suite
- [ ] **Tβ16** 默认 `./scripts/e2e.sh` 维持 SQLite，确保所有现有 81+ case 通过

### β.6 · 验收

- [ ] **Vβ1** 本地 `UTEKI_DB_URL=sqlite:///...` → alembic 升级 + 跑 e2e 全过
- [ ] **Vβ2** 本地 docker Postgres + alembic 升级 + e2e smoke 全过
- [ ] **Vβ3** `_ensure_*_column` 路径在 Postgres 上 dry-run 没错（即使 alembic 是主路径）


## PR γ — Dockerfile + Cloud Run 首次手工 deploy（~1 day）

> 用 gcloud CLI 把第一个 revision 推上去，证明镜像 + 服务能跑。还没 GCLB / 自定义域名。

### γ.1 · Dockerfile · api

- [ ] **Tγ1** 新建 `services/api/Dockerfile`：base `python:3.13-slim-bookworm` → install uv → copy `pyproject.toml` + `uv.lock` → `uv sync --frozen --no-dev` → copy `src/` → `CMD ["uvicorn", "uteki_api.main:app", "--host", "0.0.0.0", "--port", "8000"]`
- [ ] **Tγ2** `services/api/.dockerignore` 排除 `data/`, `tests/`, `*.md`, `__pycache__`
- [ ] **Tγ3** 本地 `docker build -t uteki-api -f services/api/Dockerfile services/api` 通过；`docker run -p 8000:8000 -e UTEKI_USE_MOCK_LLM=true uteki-api` 跑通 `/api/health`

### γ.2 · Dockerfile · web

- [ ] **Tγ4** 新建 `apps/web/Dockerfile`：multi-stage（builder = `node:24-bookworm-slim` + pnpm 安装 + `pnpm build`；runtime = `node:24-bookworm-slim` + 拷贝 `.next/standalone` + `.next/static` + `public`）→ `CMD ["node", "server.js"]`
- [ ] **Tγ5** 在 `apps/web/next.config.ts` 加 `output: "standalone"` 配置
- [ ] **Tγ6** 因 monorepo build context = 仓库根（pnpm workspace）；Dockerfile 用 `--filter` build 单 app
- [ ] **Tγ7** `apps/web/.dockerignore` 排除 `node_modules`, `.next/cache`, `*.md`
- [ ] **Tγ8** 本地 `docker build -t uteki-web -f apps/web/Dockerfile .` 通过；`docker run -p 3000:3000 uteki-web` 跑通 `/`

### γ.3 · GCP project bootstrap

- [ ] **Tγ9** `gcloud projects create uteki-prod-<suffix>` （或复用现有 owner project）
- [ ] **Tγ10** enable APIs：`run.googleapis.com sqladmin.googleapis.com storage.googleapis.com secretmanager.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com compute.googleapis.com dns.googleapis.com certificatemanager.googleapis.com`
- [ ] **Tγ11** create Artifact Registry repo `asia-east1-docker.pkg.dev/<project>/uteki/`
- [ ] **Tγ12** create Cloud SQL instance `uteki-pg`（Postgres 17, db-f1-micro, 10 GB SSD, asia-east1, **no public IP**, automated backup 开）
- [ ] **Tγ13** 在 Cloud SQL 上 `CREATE DATABASE uteki` + create user `uteki` with strong password
- [ ] **Tγ14** create GCS bucket `gs://uteki-artifacts/`（asia-east1, STANDARD, uniform IAM）
- [ ] **Tγ15** create 8 Secret Manager secrets（jwt / oauth client secrets / api keys / postgres url）—— 用 owner 准备好的 secret 值 `gcloud secrets create ... --data-file=`
- [ ] **Tγ16** create 2 service account：`uteki-api-sa`, `uteki-web-sa`；绑权限（见 design §2.4 + §5.3）

### γ.4 · 首次手工 deploy

- [ ] **Tγ17** `docker push asia-east1-docker.pkg.dev/<project>/uteki/api:v0`
- [ ] **Tγ18** `docker push asia-east1-docker.pkg.dev/<project>/uteki/web:v0`
- [ ] **Tγ19** `gcloud run deploy uteki-api` 完整 flag set（image / region / SA / env / secrets / cloud-sql-instances / memory / cpu / concurrency / timeout / min / max / ingress）
- [ ] **Tγ20** `gcloud run deploy uteki-web` 同 flag set（参 design §5）
- [ ] **Tγ21** 各自直拿到 `https://uteki-api-<hash>.run.app/api/health` 和 `https://uteki-web-<hash>.run.app/` 测一遍 200
- [ ] **Tγ22** OAuth flow 此刻不可用（callback URL 未配 prod 域名），跳过

### γ.5 · 验收

- [ ] **Vγ1** `docker build` 两个镜像本地通过
- [ ] **Vγ2** Cloud Run revision 各自 ready 状态
- [ ] **Vγ3** api 服务 `/api/health` 返 200 + 能连 Cloud SQL（log 里有 alembic migration 记录）
- [ ] **Vγ4** web 服务 `/` 返 200（即使没有 api 链接因为 fetch 用绝对路径会失败，主页能渲染就行）
- [ ] **Vγ5** 镜像大小：api < 500 MB / web < 300 MB（slim base + standalone）


## PR δ — GCLB + 自定义域 + Cloud Armor + 真实 OAuth callback（~1 day）

> 把 PR γ 推上去的两个独立 Cloud Run URL 隐藏到同一个 `https://your.domain.com` 下。OAuth 真正可用。

### δ.1 · 域名 + cert

- [ ] **Tδ1** 在 Cloud Domains 买（或转入）`your.domain.com`；启用 DNSSEC
- [ ] **Tδ2** create Cloud DNS managed zone for `your.domain.com`
- [ ] **Tδ3** create managed SSL cert `uteki-cert`，绑域名

### δ.2 · GCLB

- [ ] **Tδ4** create 2 Serverless NEG：`neg-uteki-web`（指 `uteki-web` service）+ `neg-uteki-api`（指 `uteki-api` service），都在 `asia-east1`
- [ ] **Tδ5** create 2 backend service：`backend-uteki-web` 指 `neg-uteki-web`、`backend-uteki-api` 指 `neg-uteki-api`
- [ ] **Tδ6** create URL map `uteki-urlmap`：default → `backend-uteki-web`；`/api/*` → `backend-uteki-api`
- [ ] **Tδ7** create target HTTPS proxy 绑 cert + URL map
- [ ] **Tδ8** create global forwarding rule + 静态 IP
- [ ] **Tδ9** A record `your.domain.com` → 静态 IP；等 cert provisioning 完成（~15 min）

### δ.3 · Cloud Run ingress 收紧

- [ ] **Tδ10** `gcloud run services update uteki-api --ingress=internal-and-cloud-load-balancing`
- [ ] **Tδ11** 同操作 `uteki-web`
- [ ] **Tδ12** 验证：直接访问 `*.run.app` URL 返 403/404（仅 GCLB 能进入）

### δ.4 · Cloud Armor

- [ ] **Tδ13** create security policy `uteki-armor`：rate_based_ban rule 100 req/min/IP + adaptive protection enabled
- [ ] **Tδ14** 绑到 `backend-uteki-web` + `backend-uteki-api`

### δ.5 · OAuth callback 配置

- [ ] **Tδ15** GitHub OAuth App settings：Authorization callback URL 加 `https://your.domain.com/api/auth/oauth/github/callback`（保留 localhost 那条不删）
- [ ] **Tδ16** Google OAuth client settings：Authorized redirect URI 加 `https://your.domain.com/api/auth/oauth/google/callback`
- [ ] **Tδ17** 更新 Secret Manager `uteki-jwt-secret`、`uteki-github-client-secret` 等到最终值；触发 `gcloud run services update --update-secrets=...` 重新 deploy api
- [ ] **Tδ18** Cloud Run api env 加 `UTEKI_OAUTH_CALLBACK_BASE=https://your.domain.com`（PR ε 之前用 update-env 即可）

### δ.6 · 验收

- [ ] **Vδ1** `https://your.domain.com/` → 200 web
- [ ] **Vδ2** `https://your.domain.com/api/health` → 200 api
- [ ] **Vδ3** `curl -v https://uteki-api-<hash>.run.app/api/health` → 403（ingress 收紧）
- [ ] **Vδ4** GitHub OAuth flow：点登录 → GitHub → 回 prod 域名 callback → access token 发出 → 跳 `/console`
- [ ] **Vδ5** Google OAuth flow 同
- [ ] **Vδ6** 非 owner GitHub login → 不发 token → 跳 `/?error=not_owner`（010 行为延续）
- [ ] **Vδ7** Cloud Armor 触发：用 `ab -n 200 -c 10` 单 IP 打 → 100 后开始 429


## PR ε — GitHub Actions CI/CD（~0.5 day）

> 把 PR γ 的手工 deploy 自动化。push to main → 自动 deploy + smoke + flip。

### ε.1 · Workload Identity Federation

- [ ] **Tε1** `gcloud iam workload-identity-pools create github --location=global`
- [ ] **Tε2** `gcloud iam workload-identity-pools providers create-oidc uteki ...`（绑 GitHub repo `<owner>/uteki`）
- [ ] **Tε3** create `deploy-sa@<project>.iam.gserviceaccount.com`
- [ ] **Tε4** 绑 `roles/run.developer` + `roles/iam.serviceAccountUser` + `roles/artifactregistry.writer` on project
- [ ] **Tε5** 允许 GitHub Actions impersonate `deploy-sa`：`gcloud iam service-accounts add-iam-policy-binding deploy-sa ...`

### ε.2 · GitHub Actions workflow

- [ ] **Tε6** 新建 `.github/workflows/deploy.yml`，骨架见 design §6.2
- [ ] **Tε7** add `workload_identity_provider` + `service_account` 到 `google-github-actions/auth@v2` step
- [ ] **Tε8** docker build × 2 + docker push × 2
- [ ] **Tε9** `gcloud run deploy --no-traffic --tag=rev-${SHA}` × 2
- [ ] **Tε10** smoke test step：curl revision-tagged URL × 2
- [ ] **Tε11** `gcloud run services update-traffic --to-revisions=rev-${SHA}=100` × 2
- [ ] **Tε12** failure 时 workflow exit non-zero —— 旧 revision 仍持有 100% traffic，自动 "rollback"

### ε.3 · rollback runbook

- [ ] **Tε13** 新建 `docs/runbook/rollback.md`：列 3 步：list revisions → 选 prev tag → update-traffic
- [ ] **Tε14** 列在 `README.md` 顶部 "Deploy" 章节链过去

### ε.4 · billing alert

- [ ] **Tε15** create Budget `uteki-prod-budget` $50/月，alert thresholds 50% / 80% / 100%
- [ ] **Tε16** 邮件通知 owner 邮箱

### ε.5 · 验收

- [ ] **Vε1** push 一个无关 typo commit 到 main → workflow 自动跑 → 新 revision 出现 + smoke 通过 + traffic 翻 100%
- [ ] **Vε2** 故意改坏 smoke test endpoint → workflow 失败 + traffic 没翻（旧 revision 仍 serve）
- [ ] **Vε3** 跑 rollback runbook 一遍：手工切回上一个 revision → `/api/health` 仍 200
- [ ] **Vε4** $5 阈值触发邮件（小心测：临时把 budget 改 $0.10 → 翻回 $50）


## 全局验收（V）

- [ ] **V1** `https://your.domain.com/` 公开 landing 渲染（010 公开 surface）
- [ ] **V2** `https://your.domain.com/console` 未登录 → redirect login
- [ ] **V3** Owner GitHub OAuth → 跳 `/console` → 触发一次 company_research_pipeline → trace + artifacts 全部出现
- [ ] **V4** 同 V3 标 run public → 公开 `/runs/<id>` 匿名可读
- [ ] **V5** 直接访问 `https://uteki-api-<hash>.run.app/...` → 403（ingress 锁住）
- [ ] **V6** Cloud Logging 看到 api 服务日志 + web 服务日志（structured fields 完整）
- [ ] **V7** Cloud SQL 有 1+ user / 1+ run row
- [ ] **V8** GCS bucket 有 `users/<uid>/runs/<sha2>/<run_id>/artifacts/...` 真实 blob
- [ ] **V9** Secret Manager 所有 8 secret 都被 api 服务 access 过（access count > 0）
- [ ] **V10** `gcloud run revisions list` 看到至少 2 个历史 revision（rollback 能力 ready）
- [ ] **V11** GCP Billing Budget 配 $50 月预算 + 邮件 alert
- [ ] **V12** rollback 演练：旧 revision 重置 100% traffic → 服务恢复 < 30s


## 时间盒

| PR | 估时 | commits | 关键依赖 |
|---|---|---|---|
| PR α (GCSArtifactStore) | 1 day | 4-5 | 010 已落 |
| PR β (Postgres + alembic) | 1 day | 4-5 | 独立 |
| PR γ (Dockerfile + 首 deploy) | 1 day | 5-6 | PR α + β |
| PR δ (GCLB + domain + OAuth) | 1 day | 4-5 | PR γ |
| PR ε (CI/CD) | 0.5 day | 2-3 | PR γ |
| **合计** | **4.5 day** | ~22 commits | — |


## 备注

- PR α + β 完全是技术准备，不动 prod；可以与 011 (async-run-queue) 并行
- PR γ 是单点决策：何时把第一个 image 真正推到 GCP
- PR δ 是 "公开发布" 时刻——之前所有 URL 仍是 `.run.app` hash 域名，δ 后才是真域名
- PR ε 是自动化收尾——少了它也能上线，只是后续手工 deploy 烦
- 若 owner 中途想暂停：PR α / β 可独立 merge；PR γ 之前没有任何 GCP 真实资源（除 project 元数据）
