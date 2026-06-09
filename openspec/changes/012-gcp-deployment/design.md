# 012 · Design

> 目标读者：未来的 owner 在 ~12 个月后需要 rotate secret / 升 SQL tier / 迁区域时，能从这份文档完全 reconstruct 当前架构。

## 1. 目标架构

```
                  ┌─────────────────────────────────────────────────────────┐
   DNS A record   │                                                          │
   你域名 ──→     │  Cloud HTTPS Load Balancer  (asia-east1)                │
                  │  ├── managed SSL cert (Cloud-managed, auto-renew)       │
                  │  ├── Cloud Armor policy (DDoS + simple rate limit)      │
                  │  └── URL map:                                            │
                  │        /api/*  ──→  backend-uteki-api                   │
                  │        /*      ──→  backend-uteki-web                   │
                  │                                                          │
                  │   两个 backend service 都是 Serverless NEG —— 直接绑    │
                  │   到 Cloud Run service 名，不暴露公网 ingress。         │
                  └────┬────────────────────────────────┬───────────────────┘
                       │                                │
                       ▼                                ▼
            ┌──────────────────────┐         ┌──────────────────────┐
            │  Cloud Run · web      │         │  Cloud Run · api      │
            │  uteki-web            │         │  uteki-api            │
            │  Next 16 standalone   │         │  FastAPI + uvicorn    │
            │  Node 24 (slim)       │         │  Python 3.13 (slim)   │
            │  port 3000            │         │  port 8000            │
            │  mem 512 MB, cpu 1    │         │  mem 1 GB, cpu 1      │
            │  min 0, max 3         │         │  min 0, max 5         │
            │  concurrency 80       │         │  concurrency 8        │
            │  timeout 300s         │         │  timeout 900s         │
            │  SA: web-sa@...       │         │  SA: api-sa@...       │
            └──────────────────────┘         └──────┬───────────────┘
                                                    │
                                  ┌─────────────────┼──────────────────────┐
                                  │                 │                       │
                                  ▼                 ▼                       ▼
                       ┌────────────────┐  ┌────────────────┐    ┌────────────────────┐
                       │  Cloud SQL      │  │  GCS bucket    │    │  Secret Manager     │
                       │  Postgres 17    │  │  uteki-        │    │  8 secrets, version │
                       │  db-f1-micro    │  │   artifacts    │    │  pinned per Cloud   │
                       │  10 GB SSD      │  │  STANDARD      │    │  Run revision       │
                       │  asia-east1     │  │  asia-east1    │    │                      │
                       │  no public IP   │  │  uniform IAM   │    │                      │
                       │  via SQL Auth   │  │                │    │                      │
                       │  Proxy / connect│  │                │    │                      │
                       └────────────────┘  └────────────────┘    └────────────────────┘
```

### 1.1 单域同源的 cookie / CORS 后果

- httpOnly refresh cookie：`Domain=your.domain.com`（host-only，无 `.your.domain.com`），`Path=/`，`SameSite=Lax`，`Secure`
- API CORS：**不发任何 `Access-Control-Allow-*` header**——同源请求不触发 preflight，浏览器直接允许
- web 端 fetch：`fetch('/api/runs')`（相对路径），credentials 走默认 `same-origin`
- 010 的 `optional_user` / `require_owner` / `_owner_id` 全部沿用，不改一行

### 1.2 为什么 `concurrency` 设这两个值

- web concurrency=80 — Next standalone 是无状态 SSR，单 instance 撑 80 并发 ~300 MB
- api concurrency=8 — FastAPI 一旦带 LLM streaming + tool execution，单请求峰值 200+ MB；超并发会触发 Cloud Run OOM kill。也是 010 owner 单人触发的实际峰值预算

## 2. GCS Artifact Store

### 2.1 路径方案

```
gs://uteki-artifacts/
└── users/
    └── <safe(user_id)>/                  # 与现有 LocalFile 同 layout
        └── runs/
            └── <sha2(run_id[:2])>/
                └── <run_id>/
                    ├── artifacts/<name>
                    └── manifest.json
```

**完全镜像 `data/runs/users/...`**。理由：

1. 不动任何 application-layer 路径计算（`_artifact_path` / `_manifest_path`）—— `GCSArtifactStore` 只是把 `Path` 拼接换成 `bucket.blob(...)` 调用
2. M4 invariant `_owner_id(run_id, user)` 检查 → 跨用户读 → `FileNotFoundError`（GCS 对应 `404 Not Found`）→ API 404 — 链路无变化
3. 未来想从 GCS 把单个 user 整体 dump 出来 = `gsutil rsync gs://uteki-artifacts/users/<uid>/ ./backup/`，路径自解释
4. 未来想做 multi-bucket per-user 也只需要 `bucket_for(user_id)` 一个 hook，路径方案不变

### 2.2 接口

`GCSArtifactStore` 继承 `services/api/src/uteki_api/artifacts/store.py:ArtifactStore` ABC，**接口签名零改动**。等价方法映射：

| `LocalFileArtifactStore` 操作 | `GCSArtifactStore` 实现 |
|---|---|
| `_artifact_path(...).parent.mkdir(parents=True)` | no-op（GCS 没有目录） |
| `tmp.write_bytes(body); os.replace(tmp, path)` | `blob.upload_from_string(body, content_type=...)` — GCS upload 本身原子 |
| `path.read_bytes()` | `blob.download_as_bytes()` |
| `path.exists()` | `blob.exists()` — 但每次走 GCS 是网络 round trip；后续可加进程内 LRU |
| `manifest.json` read/write | 同样 `blob.upload_from_string(json.dumps(...))` — last-write-wins |

### 2.3 manifest race condition

LocalFile 上 `manifest.json` 通过 `os.replace` 原子；多并发 write 是 last-write-wins（M4 invariant）。GCS 同样 last-write-wins——`upload_from_string` 单 blob 是 strongly consistent，但两个并发 upload 谁后写谁赢，会丢中间状态。

010 + 011 架构下：**一个 run 只有一个 worker 任务**——manifest 不可能并发写。这个约束就是保护机制。

如果未来 011 演化到分布式 worker，每个 sub-skill 一个 worker 共享 run_id，那时要么：

- (a) 改成 per-artifact metadata 一个 blob，没有 shared manifest
- (b) 用 GCS object metadata 替代 `manifest.json`（GCS blob 自带 custom metadata 字段）

(b) 是更干净的方向；本 change 不做，留 TODO。

### 2.4 权限模型

api 的 Cloud Run service account `uteki-api-sa@<project>.iam.gserviceaccount.com` 上绑：

```
roles/storage.objectAdmin    on  bucket  uteki-artifacts/
roles/cloudsql.client        on  project (for SQL connector)
roles/secretmanager.secretAccessor  on  each of 8 secrets
roles/logging.logWriter      on  project (auto)
```

**bucket-level objectAdmin**，应用层强制 `_owner_id(run_id, user)` 做 ownership check。**不**用 condition-IAM 做 `users/<user_id>/*` per-user 隔离——理由：

1. condition-IAM 写起来复杂，且 owner 单租户场景下与应用层 check 完全冗余
2. 010 单 owner 模型下，所有 artifact 实际属同一个 `OWNER.id`——per-user IAM 没有授权对象差异
3. MVP 阶段：**ownership = 应用层 check**；prod 上线后若加多用户场景再加 IAM condition

### 2.5 backend 切换

`services/api/src/uteki_api/artifacts/__init__.py` 改成：

```python
def _build_default_store() -> ArtifactStore:
    backend = os.getenv("UTEKI_STORAGE_BACKEND", "fs").lower()
    if backend == "gcs":
        from uteki_api.artifacts.gcs_store import GCSArtifactStore
        return GCSArtifactStore(bucket_name=settings.gcs_bucket)
    return LocalFileArtifactStore()

default_artifact_store: ArtifactStore = _build_default_store()
```

dev `.env` 不动 → `UTEKI_STORAGE_BACKEND` 缺失 → `fs` → LocalFile。prod Cloud Run env：`UTEKI_STORAGE_BACKEND=gcs` + `UTEKI_GCS_BUCKET=uteki-artifacts`。

## 3. SQLite → Postgres

### 3.1 URL switch

dev:
```
UTEKI_DB_URL=sqlite:///data/uteki.db
```

prod:
```
UTEKI_DB_URL=postgresql+pg8000://uteki:<password>@/uteki?host=/cloudsql/<project>:asia-east1:uteki-pg
```

unix socket 路径 `/cloudsql/...` 是 Cloud Run + Cloud SQL connector 内置约定——Cloud Run 自动 mount，不需要 sidecar Proxy 进程。

### 3.2 driver

`pg8000` 是纯 Python，无 binary build，Cloud Run cold start 友好。生产用 `pg8000` 已经验证过——比 `psycopg2-binary` cold start 快 ~300ms。

### 3.3 dialect compatibility audit

`core/db.py` 有 3 处 inline `ALTER TABLE`（M4 / M1.9 / 010 历史遗留）：

- `_ensure_user_role_column` — `ALTER TABLE "user" ADD COLUMN role VARCHAR(16) DEFAULT 'reader'`
- `_ensure_run_assessment_columns` — 3 个 `ALTER TABLE run ADD COLUMN ...`
- `_ensure_run_visibility_column` — `ALTER TABLE run ADD COLUMN visibility ...` + `CREATE INDEX IF NOT EXISTS ...`

Postgres 兼容性：

| 语句 | SQLite | Postgres | 行动 |
|---|---|---|---|
| `ALTER TABLE x ADD COLUMN y VARCHAR(16) DEFAULT '...'` | ✓ | ✓ | 无需改 |
| `CREATE INDEX IF NOT EXISTS ix_run_visibility ON run (visibility)` | ✓ | ✓ (PG 9.5+) | 无需改 |
| `UPDATE run SET ... WHERE harness_status = 'running'` | ✓ | ✓ | 无需改 |
| `"user"` 引号（reserved keyword in PG） | ✓ | ✓ | 无需改（已加引号） |

inline ALTER 路径目前可以直接跑 Postgres——但仍然脆弱。**PR β 同时引入 alembic 正式 migration**，把这 3 个 ensure 函数收摄成第一个 alembic revision，未来 schema 改动一律走 alembic。inline ensure 保留一个 release cycle 作 fallback。

### 3.4 Cloud SQL Auth Proxy / native connector

两个选项：

| 方式 | 描述 | 选择 |
|---|---|---|
| **Cloud SQL Auth Proxy sidecar** | 在 Cloud Run 旁起一个 proxy 进程，本地 TCP 转发 | ✗ Cloud Run 不支持 sidecar，需要 multi-process container |
| **Cloud SQL Python Connector + IAM auth** | 应用代码用 `google-cloud-sql-connector` 库直连 | 可选，需改 SQLAlchemy creator |
| **Cloud Run built-in `--add-cloudsql-instances`** | 自动 mount unix socket `/cloudsql/<INSTANCE>` | ✓ 选这个 |

第三个最简单：deploy 时加 `--add-cloudsql-instances=<project>:<region>:<instance>`，应用代码 db_url 改 unix socket host 即可。IAM auth 留给 future hardening。

### 3.5 Connection pool

```python
engine = create_engine(
    db_url,
    pool_size=2,
    max_overflow=0,
    pool_recycle=1800,  # Cloud SQL idle 终止 ~10 min；preempt
    pool_pre_ping=True, # NAT 后断线后第一次 query 自动 reconnect
)
```

Cloud Run 单 instance × 单 worker (uvicorn default) × `pool_size=2` × max instances 5 = 上限 10 conn。db-f1-micro max 25 → 有余裕。

## 4. Secret Manager

8 个 secret，每个一个 Secret，多 version：

| Secret 名 | 用途 | rotation 频率 |
|---|---|---|
| `uteki-jwt-secret` | HS256 JWT signing (`UTEKI_JWT_SECRET`) | 12 月 |
| `uteki-github-client-secret` | GitHub OAuth (`GITHUB_CLIENT_SECRET`) | 不主动 rotate |
| `uteki-google-client-secret` | Google OAuth (`GOOGLE_CLIENT_SECRET`) | 不主动 rotate |
| `uteki-anthropic-key` | `ANTHROPIC_API_KEY` | 6 月 |
| `uteki-openai-key` | `OPENAI_API_KEY` | 6 月 |
| `uteki-deepseek-key` | `DEEPSEEK_API_KEY` | 6 月（optional，不配也能跑） |
| `uteki-aihubmix-key` | `AIHUBMIX_API_KEY` | 6 月（optional） |
| `uteki-postgres-url` | 完整 `UTEKI_DB_URL` 含 password | 跟 SQL user password rotation 一起 |

Cloud Run deploy 时：

```
--set-secrets=\
  UTEKI_JWT_SECRET=uteki-jwt-secret:latest,\
  GITHUB_CLIENT_SECRET=uteki-github-client-secret:latest,\
  ...
```

**`:latest` 不会自动 refresh**——env 在 instance 启动时一次性注入。rotation 流程：

1. `gcloud secrets versions add uteki-jwt-secret --data-file=new.txt`
2. `gcloud run services update uteki-api --update-secrets=UTEKI_JWT_SECRET=uteki-jwt-secret:latest` → 触发新 revision
3. 老 revision 仍然持有老 secret，traffic 切到新 revision 后老 revision idle → 自动 scale-to-zero

不主动 rotate 的 secret 出问题时 = `versions add` 新版本 + 一次 `services update` 走 step 2。

## 5. Cloud Run 服务定义

### 5.1 uteki-api

```yaml
# 通过 gcloud deploy 配置，不维护 yaml；这里写等价配置
service: uteki-api
region: asia-east1
image: asia-east1-docker.pkg.dev/<project>/uteki/api:<sha>
service_account: uteki-api-sa@<project>.iam.gserviceaccount.com
ingress: internal-and-cloud-load-balancing   # 只接 GCLB；不直接公网暴露
allow_unauthenticated: true                  # 实际鉴权在应用层（JWT）

container:
  port: 8000
  command: ["uvicorn", "uteki_api.main:app", "--host", "0.0.0.0", "--port", "8000"]
  memory: 1Gi
  cpu: 1
  concurrency: 8
  timeout: 900s            # pipeline 最长 ~10 min

scaling:
  min: 0
  max: 5

cloud_sql_instances:
  - <project>:asia-east1:uteki-pg

env_vars:
  UTEKI_AUTH_REQUIRED: "true"
  UTEKI_USE_MOCK_LLM: "false"
  UTEKI_STORAGE_BACKEND: "gcs"
  UTEKI_GCS_BUCKET: "uteki-artifacts"
  UTEKI_RUN_STORE: "sqlite"   # 注：环境 var 名沿用，实际后端按 db_url 走 PG
  UTEKI_OAUTH_REDIRECT_BASE: "https://your.domain.com"
  UTEKI_FRONTEND_BASE: "https://your.domain.com"
  UTEKI_OAUTH_CALLBACK_BASE: "https://your.domain.com"
  UTEKI_DEFAULT_MODEL: "deepseek/deepseek-chat"
  OWNER_EMAILS: "<owner email>"
  OWNER_GITHUB_LOGINS: "<owner github>"

secrets:
  UTEKI_JWT_SECRET: uteki-jwt-secret:latest
  UTEKI_DB_URL: uteki-postgres-url:latest
  GITHUB_CLIENT_SECRET: uteki-github-client-secret:latest
  GOOGLE_CLIENT_SECRET: uteki-google-client-secret:latest
  ANTHROPIC_API_KEY: uteki-anthropic-key:latest
  OPENAI_API_KEY: uteki-openai-key:latest
  DEEPSEEK_API_KEY: uteki-deepseek-key:latest
  AIHUBMIX_API_KEY: uteki-aihubmix-key:latest
```

### 5.2 uteki-web

```yaml
service: uteki-web
region: asia-east1
image: asia-east1-docker.pkg.dev/<project>/uteki/web:<sha>
service_account: uteki-web-sa@<project>.iam.gserviceaccount.com
ingress: internal-and-cloud-load-balancing
allow_unauthenticated: true

container:
  port: 3000
  command: ["node", "server.js"]   # Next standalone 输出
  memory: 512Mi
  cpu: 1
  concurrency: 80
  timeout: 300s

scaling:
  min: 0
  max: 3

env_vars:
  NODE_ENV: "production"
  # web 不知道 api 在哪——所有 fetch 都是相对路径 /api/*
  # GCLB 把 /api/* 路由到 api service，对 web 透明
  NEXT_PUBLIC_SITE_URL: "https://your.domain.com"

# web 无 secret 需求；OAuth client_id 走 NEXT_PUBLIC env（公开）
# 真正敏感的 client_secret 在 api 那边
```

### 5.3 service account 隔离

- `uteki-api-sa` — 有 SQL / GCS / Secret Manager 权限
- `uteki-web-sa` — 只有 `roles/logging.logWriter`；不能读 SQL、不能读 GCS、不能读任何 secret

哪怕 web container 被攻破，攻击者拿不到 db creds 或 LLM API key。

## 6. CI/CD

### 6.1 Cloud Build (option A — GCP native)

```yaml
# cloudbuild.yaml
steps:
  # 1. build api image
  - name: gcr.io/cloud-builders/docker
    args: ['build', '-f', 'services/api/Dockerfile', '-t',
           'asia-east1-docker.pkg.dev/$PROJECT_ID/uteki/api:$SHORT_SHA',
           'services/api']

  # 2. build web image
  - name: gcr.io/cloud-builders/docker
    args: ['build', '-f', 'apps/web/Dockerfile', '-t',
           'asia-east1-docker.pkg.dev/$PROJECT_ID/uteki/web:$SHORT_SHA',
           '.']  # web build 要读 monorepo 根

  # 3. push both
  - name: gcr.io/cloud-builders/docker
    args: ['push', 'asia-east1-docker.pkg.dev/$PROJECT_ID/uteki/api:$SHORT_SHA']
  - name: gcr.io/cloud-builders/docker
    args: ['push', 'asia-east1-docker.pkg.dev/$PROJECT_ID/uteki/web:$SHORT_SHA']

  # 4. deploy api revision, no traffic
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    args: ['gcloud', 'run', 'deploy', 'uteki-api',
           '--image=asia-east1-docker.pkg.dev/$PROJECT_ID/uteki/api:$SHORT_SHA',
           '--region=asia-east1', '--no-traffic',
           '--tag=rev-$SHORT_SHA']

  # 5. deploy web revision, no traffic
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    args: ['gcloud', 'run', 'deploy', 'uteki-web',
           '--image=asia-east1-docker.pkg.dev/$PROJECT_ID/uteki/web:$SHORT_SHA',
           '--region=asia-east1', '--no-traffic',
           '--tag=rev-$SHORT_SHA']

  # 6. smoke test against revision URLs (--tag exposes them)
  - name: gcr.io/cloud-builders/curl
    args: ['-f', '-sS', 'https://rev-$SHORT_SHA---uteki-api-<hash>.run.app/api/health']
  - name: gcr.io/cloud-builders/curl
    args: ['-f', '-sS', 'https://rev-$SHORT_SHA---uteki-web-<hash>.run.app/']

  # 7. flip 100% traffic on both
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    args: ['gcloud', 'run', 'services', 'update-traffic', 'uteki-api',
           '--region=asia-east1', '--to-revisions=rev-$SHORT_SHA=100']
  - name: gcr.io/google.com/cloudsdktool/cloud-sdk
    args: ['gcloud', 'run', 'services', 'update-traffic', 'uteki-web',
           '--region=asia-east1', '--to-revisions=rev-$SHORT_SHA=100']

options:
  machineType: E2_HIGHCPU_8
timeout: 1200s
```

### 6.2 GitHub Actions (option B — 我们选这个)

owner 已经在 GitHub 上，Cloud Build 是额外 vendor lock-in 面。**用 GitHub Actions + `google-github-actions/auth` (Workload Identity Federation)**——免 service-account-key json 文件，安全。

`.github/workflows/deploy.yml` 骨架：

```yaml
on:
  push: { branches: [main] }
jobs:
  build-and-deploy:
    permissions:
      id-token: write   # Workload Identity Federation 需要
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: google-github-actions/auth@v2
        with:
          workload_identity_provider: projects/<num>/locations/global/workloadIdentityPools/github/providers/uteki
          service_account: deploy-sa@<project>.iam.gserviceaccount.com
      - uses: google-github-actions/setup-gcloud@v2
      - run: gcloud auth configure-docker asia-east1-docker.pkg.dev
      - run: docker build -f services/api/Dockerfile -t asia-east1-docker.pkg.dev/<project>/uteki/api:${GITHUB_SHA::7} services/api
      - run: docker build -f apps/web/Dockerfile -t asia-east1-docker.pkg.dev/<project>/uteki/web:${GITHUB_SHA::7} .
      - run: docker push asia-east1-docker.pkg.dev/<project>/uteki/api:${GITHUB_SHA::7}
      - run: docker push asia-east1-docker.pkg.dev/<project>/uteki/web:${GITHUB_SHA::7}
      - run: |
          gcloud run deploy uteki-api --image=... --no-traffic --tag=rev-${GITHUB_SHA::7} --region=asia-east1
          gcloud run deploy uteki-web --image=... --no-traffic --tag=rev-${GITHUB_SHA::7} --region=asia-east1
      - run: |
          curl -fsS https://rev-${GITHUB_SHA::7}---uteki-api-<hash>.run.app/api/health
          curl -fsS https://rev-${GITHUB_SHA::7}---uteki-web-<hash>.run.app/
      - run: |
          gcloud run services update-traffic uteki-api --to-revisions=rev-${GITHUB_SHA::7}=100 --region=asia-east1
          gcloud run services update-traffic uteki-web --to-revisions=rev-${GITHUB_SHA::7}=100 --region=asia-east1
```

`deploy-sa@` 是专门为部署而建的 service account，绑：

- `roles/run.developer`
- `roles/iam.serviceAccountUser`（impersonate `uteki-api-sa` / `uteki-web-sa`）
- `roles/artifactregistry.writer`

不绑 SQL / GCS / Secret Manager 权限——deploy-sa 不需要碰数据。

### 6.3 Rollback

```bash
# 找到上一个稳定 revision tag
gcloud run revisions list --service uteki-api --region asia-east1

# 一键回滚（保留前 2 个 revision 一直可用）
gcloud run services update-traffic uteki-api \
  --to-revisions=<prev-rev>=100 \
  --region=asia-east1

# 同操作对 web
```

无需重 build、无需重 push、无需新 secret。是 GCP 同源单 service 方案的最大运维红利。

## 7. DNS + Load Balancer

### 7.1 域名链路

- owner 在 Cloud Domains 买 `your.domain.com`（或从外部 registrar 转入）
- Cloud DNS 托管 zone
- A record `your.domain.com` → GCLB 的 anycast IP
- GCLB 配 managed SSL cert，cert 名 `uteki-cert`，绑域名 `your.domain.com`
- cert auto-renew，60 天自动

### 7.2 URL map

```
host: your.domain.com
default_service: backend-uteki-web
path_matcher:
  - path: /api/*
    service: backend-uteki-api
```

backend service 是 Serverless NEG，直接绑 Cloud Run service 名，**无 CDN**（dashboard 静态资源体积小，不必）。如未来加 marketing 站点静态页可加 CDN 在前面。

### 7.3 Cloud Armor

basic policy 绑到两个 backend service：

```
rules:
  - priority: 1000
    action: rate_based_ban
    rate_limit: 100 req / min per IP
    ban_duration: 600s
  - priority: 2147483647 (default)
    action: allow
adaptive_protection:
  layer_7_ddos_defense: enabled
```

owner 流量极低，100 req / min per IP 给爬虫和外部好奇访问足够。MVP 不做 WAF rule（SQL injection / XSS）——010 后端用 Pydantic 强 schema + SQLModel，不存在 raw query 注入面。

## 8. 本地 dev 不动

为了让 010 + 012 不互相阻塞，**本地 dev 完全不感知 prod**：

| 概念 | dev | prod |
|---|---|---|
| 同源 | Next rewrites 把 `/api/*` 转 `http://localhost:8000/api/*` | GCLB URL map |
| DB | `sqlite:///data/uteki.db` | `postgresql+pg8000://...?host=/cloudsql/...` |
| Artifact | `LocalFileArtifactStore("data/runs")` | `GCSArtifactStore("uteki-artifacts")` |
| Secret | `services/api/.env` 明文 | Secret Manager `--set-secrets` |
| OAuth callback | `http://localhost:8000/api/auth/oauth/<p>/callback` | `https://your.domain.com/api/auth/oauth/<p>/callback` |
| auth_required | `false`（demo user fallback） | `true` |
| owner check | `OWNER_EMAILS` 配本地邮箱也行 | 配真实 owner |
| mock LLM | `true` | `false` |

`make dev` 行为 100% 不变；唯一新增物是 `UTEKI_STORAGE_BACKEND=fs`（缺失即 fs，无需配）和 `UTEKI_OAUTH_CALLBACK_BASE=http://localhost:8000`（缺失则 fallback 到现有 `UTEKI_OAUTH_REDIRECT_BASE`，向后兼容）。

## 9. Cost 估算

| 项 | 单价 | 用量假设 | 月成本 |
|---|---|---|---|
| Cloud Run uteki-api | $0 idle + $0.024 / vCPU-hr active | 100 active hr / 月 | ~$2.4 |
| Cloud Run uteki-web | $0 idle + $0.024 / vCPU-hr active | 50 active hr / 月 | ~$1.2 |
| Cloud SQL db-f1-micro | $7.67 / 月 always-on | 10 GB SSD = +$1.7 | ~$9.4 |
| GCS uteki-artifacts STANDARD | $0.02 / GB-month + $0.005 / 10k ops | 5 GB + 50k ops | ~$0.13 |
| Secret Manager | $0.06 / version-month + $0.03 / 10k access | 8 secret × 2 ver + 5k access | ~$1.0 |
| Cloud HTTPS LB forwarding rule | $18 / 月 minimum | always-on | $18.0 |
| Cloud Armor (default) | included | — | $0 |
| Cloud Logging | 50 GB / 月 free; 之后 $0.5/GB | <10 GB | $0 |
| Artifact Registry | $0.10 / GB-month | 2 GB | $0.2 |
| Cloud Build | 120 build-min / 天 free | <50 min / 天 | $0 |
| **合计** | | | **~$32 / 月** |

$299/年 Premium 包含 $550 GCP credit + cert 后另 $500 → **$1050 credit / ~$32 月 ≈ 32 月覆盖**。

GCLB $18 是最大单笔——同源方案的明面代价。子域方案这一项可以省掉，但前述 cookie / CORS / preflight 复杂度交换。owner 选的是后者复杂度。

## 10. 故障模式

### 10.1 Cloud Run cold start

- 实测 api cold start ~3-5s（uvicorn + SQLAlchemy + pydantic 全量 import）
- 缓解：`gcloud run services update uteki-api --min-instances=1` → +~$8 / 月 → cold start 永远不出现
- MVP 不开 min-instances；prod 用一段时间后视体感再决定

### 10.2 Cloud SQL connection storm

- 场景：流量峰值同时拉起 5 个 api instance × `pool_size=2` × `pool_pre_ping` reconnect = 10+ 并发 conn
- db-f1-micro max_connections=25——理论安全，但 reconnect storm 会撞 burst
- 缓解：`pool_recycle=1800` 让 idle conn 主动断；`pool_pre_ping=True` 让断线自动 reconnect；监控 `pg_stat_activity` 看实际使用

### 10.3 Secret rotation 时 Cloud Run 没拿到新值

- 见 §4 — rotation 必须伴随 `gcloud run services update --update-secrets` 一次，触发新 revision
- 易遗忘点：`versions add` 后只改 Secret Manager 而 Cloud Run 仍跑旧 revision
- 加 op runbook：rotation = 2 步骤，缺一不可

### 10.4 GCS 写后立刻读

- GCS 是 strongly consistent（since 2020）——`upload_from_string` 完成后 `download_as_bytes` 必然看到新值
- 不需要 retry / eventual-consistency wait

### 10.5 跨 region 灾备

- MVP 不做。Cloud SQL automatic backup 默认开（7 天保留 + PITR 7 天），GCS 加 daily lifecycle archive 到 NEARLINE。owner 单租户、低流量，灾备恢复目标 24h RPO / 4h RTO 够用
- 跨 region 升级路径：Cloud SQL → HA tier 切多区域 + GCS bucket → multi-region 复制，应用零改动

### 10.6 OAuth callback 死循环

- 场景：在 GitHub 上漏配 callback URL，OAuth flow 跳 prod，provider 直接 400
- 缓解：部署前 dry-run 一次 OAuth flow（`scripts/oauth-smoke.sh`）；alert 配 5xx error rate threshold

## 11. 备选方案 (alternatives considered)

### 11.1 单一 Cloud Run service (web+api 合并)

- 优势：少配一次 NEG / URL map / SA
- 劣势：multi-language container 烦；scaling 不独立；release coupling
- 决定：拒绝 — 2 service 是正确边界

### 11.2 子域 + CORS（`app.domain` + `api.domain`）

- 优势：省 GCLB $18/月；DNS 直绑各自 Cloud Run domain mapping
- 劣势：cookie SameSite=None + Secure；preflight / `Access-Control-Allow-Credentials`；CSP frame-ancestors 复杂化；本地 dev 要么也跨域要么 dev/prod 不一致
- 决定：拒绝 — owner 的 mutation 流程依赖 httpOnly cookie，同源是质量更高的方案；$18/月 credit 充裕
- **诚实保留**：当 GCLB 真的成为瓶颈或预算约束变紧时，可以退回子域方案，cookie 改 `Domain=.your.domain.com` + 一次性 CORS 配置——不是单向门

### 11.3 GKE Autopilot

- 优势：scale + 自由度高
- 劣势：$72/月 control plane fee 起步，单 owner 流量远不需要
- 决定：拒绝 — 烧 credit

### 11.4 Cloud Functions (Gen 2) for api

- 优势：更便宜 idle / 更细 billing
- 劣势：FastAPI streaming + SSE 在 Cloud Functions 上是 second-class；timeout 上限 9 min 不够某些 pipeline
- 决定：拒绝 — Cloud Run 是 functions 的超集

### 11.5 Fly.io / Railway / Render

- 优势：deploy 体验更顺
- 劣势：不用 owner 现有 GCP credit；observability 要重搭
- 决定：拒绝 — credit 不用就过期

### 11.6 Vercel for web + GCP for api

- 优势：Vercel deploy 体验最好
- 劣势：跨域 cookie 复杂；observability 分裂；owner 实际不用 Vercel edge features
- 决定：拒绝 — 010 cookie 流程是核心架构假设

## 12. Open questions

- **min-instances=1 何时开**：cold start 体感 vs $8/月 增量。先 min=0 跑 2 周看真实体感
- **alembic 是否本 change 引入**：本 change 列入 PR β 的 stretch；不阻塞主线，3.4 节 inline ensure 仍是 fallback
- **是否上 Vertex AI / Gemini provider 集成**：owner 有 Google 生态 credit，加 `vertexai/` 到 `llm/router.py` 大概 1 PR；本 change 不做但留 hook
- **owner 是否要 Cloud Identity-Aware Proxy 在 `/console` 前面**：IAP 是企业 SSO 替代品；010 的 owner allowlist 已够用，不加 IAP；如未来 staff 多人需要再加
- **Cloud Logging retention**：默认 30 天免费；超过要付费；当前 owner 流量 30 天足够
- **是否启用 Cloud Trace / Cloud Profiler**：免费额度内可启；MVP 不打开，先看 Cloud Logging trace ID 关联是否足够
- **prod 数据备份策略**：Cloud SQL 自动 backup 已开；GCS 是否加 daily snapshot 到独立 bucket？依赖访问者数据敏感度（010 单 owner 模型下其实没有用户 PII，不紧迫）

## 13. 跨 change 影响

- **001 (auth)**：OAuth callback base 从写死改 env 驱动；JWT secret / OAuth client secret 走 Secret Manager 而非 `.env`——auth spec 增量见 `specs/auth/spec.md`
- **010 (public surface)**：单 owner 模型在 prod 第一次实跑；OWNER_EMAILS / OWNER_GITHUB_LOGINS env 来自 Secret Manager 或 plain env（plain env 即可，非 secret 性质）
- **011 (async run queue)**：011 + 012 双轨进行。011 引入的 `run_events` 表自动跟随 Postgres，无额外迁移。如果 012 先落，011 落时只需要在 alembic 加一个 revision
- **artifacts spec**：新增 `GCSArtifactStore` 是 `ArtifactStore` ABC 的第二个实现，路径方案 100% 等价 LocalFile——见 `specs/storage/spec.md`
- **storage spec**：partition 表加 `STORAGE_BACKEND` 维度行
