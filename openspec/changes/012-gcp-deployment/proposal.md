# 012 · GCP 部署 — Cloud Run 同源单域 + Cloud SQL + GCS artifacts

## Problem

uteki 当前所有持久状态都在 dev 机器上：

- SQLite (`data/uteki.db`) — runs / users / refresh tokens / skill versions
- 本地文件系统 (`data/runs/users/<uid>/...`) — artifacts
- 进程内 secrets（`services/api/.env`）— JWT 密钥 / OAuth client secret / LLM API keys

010 完成后，产品形态已经定型——**单 owner 公开展示 + 私有 console**。下一步就是上 prod。问题是从哪上、怎么上。

不上 prod 的代价：

- OAuth 回调写死 `http://localhost`，外人访问不到
- 没有 HTTPS，OAuth provider 拒绝注册 production callback
- SQLite 进程内文件锁——任何 multi-instance 部署立刻数据竞争
- artifacts 落本地磁盘——容器重启全丢
- secrets 在 `.env` 里——没有 rotation、没有访问审计

候选目标平台筛过两轮：

| 平台 | 取舍 |
|---|---|
| **Vercel (web) + Render/Fly (api)** | Vercel edge / ISR / image opt 对 dashboard 应用零增益；跨域 cookie + CORS 配 owner-only mutation 流程必踩坑 |
| **Vercel (web+api Functions)** | FastAPI streaming + 10 分钟 pipeline 与 serverless function 时长 / cold start 不匹配 |
| **AWS ECS Fargate + RDS + S3** | $20-30/月起步，配置面积大，无 owner 现成 credit |
| **Fly.io** | 简单但不在 owner 现有云生态里，observability 要重搭 |
| **GCP Cloud Run + Cloud SQL + GCS** | owner 有 Google Developer Program Premium，$299/年订阅含 $550 GCP credit，加上 cert 后另 $500 一次性，覆盖个人规模 30+ 月；Cloud Run scale-to-zero 适配低流量 owner 站点；统一 Cloud Logging |

owner 已经付了 $299，credit 不用作废。选 GCP。

## Solution

把 010 拆好的 `web` + `api` 两个 deployable 各自打成容器镜像，跑在 **同一个域名** 下两个 Cloud Run service：

```
your.domain.com/        → uteki-web   (Next standalone, Node 24)
your.domain.com/api/*   → uteki-api   (FastAPI + uvicorn, Python 3.13)
```

同源由 **Cloud HTTPS Load Balancer + URL map** 实现：一个 GCLB IP，按 path prefix 路由到两个 Serverless NEG。前端 fetch `/api/...` 走相对路径——和 dev 完全一致，无 CORS、无跨域 cookie。

数据层：

- **Cloud SQL Postgres 17 (db-f1-micro)** 替代 SQLite — `UTEKI_DB_URL=postgresql+pg8000://...`
- **GCS bucket** 替代 LocalFileArtifactStore — `UTEKI_STORAGE_BACKEND=gcs` + `UTEKI_GCS_BUCKET=uteki-artifacts`
- **Secret Manager** 替代 `.env` — 8 个 secret 通过 `--set-secrets` flag 注入 Cloud Run

CI/CD：

- Cloud Build（trigger on push to `main`）→ 2 个镜像 → Artifact Registry
- Cloud Run revision deploy with `--no-traffic` → smoke test on revision URL → flip 100% if pass
- 保留前 2 个 revision，rollback = `gcloud run services update-traffic --to-revisions=PREV=100`

### 为什么同源（而非子域 + CORS）

010 的鉴权模型重度依赖 **httpOnly refresh cookie**——access token 在 sessionStorage、refresh 永远在 cookie 里。子域方案要做：

1. cookie domain = `.your.domain.com`（不能 host-only）
2. SameSite=None + Secure（跨子域必备）
3. API CORS allow-list 显式列 web 域，`credentials: true`
4. preflight OPTIONS 加白名单
5. CSP / Sec-Fetch-Site 规则要单独验

同源方案这五个全是 zero-config——cookie host-only 即可，CORS header 直接不发，preflight 不存在。维护面积小一个量级。代价是要配 GCLB，但 GCLB 只配一次。

### 为什么不是 Kubernetes / GKE

owner 单人项目、个位数 QPS、scale-to-zero 是真实需求。GKE Autopilot 起步价 ~$72/月（control plane fee），Cloud Run scale-to-zero idle 接近 $0。当流量上到要 GKE 的时候再迁，今天不迁。

### 为什么不是多区域

owner 用户在亚洲，访问者也大概率在亚洲。`asia-east1`（台湾）单区域足够。多区域要 Cloud SQL HA tier（贵 ~3x）+ multi-region GCS（贵 ~2x）+ traffic distribution，不在 MVP scope。

### 为什么 Postgres 而非 Cloud Firestore / Spanner

uteki schema 是关系型——`User`/`AuthIdentity`/`RefreshToken`/`Run`/`SkillVersion` 已经是 SQLModel + 外键。Firestore 要重写所有 store；Spanner 起步贵且无 free tier credit 覆盖。Postgres 是零迁移成本路径。

## Non-goals

- **不**上 Kubernetes / GKE — Cloud Run 满足规模
- **不**做多区域 / HA — 单区域 + 每日备份够用
- **不**自管 DNSSEC — 用 Cloud Domains 一键托管
- **不**做蓝绿 / canary 流量分层 — Cloud Run 内置 `--no-traffic` + revision 切换够用
- **不**做自管 Redis / 任何 cache layer — 010 没有这个需求；如未来 011 async run queue 要 Redis 再加
- **不**做 CDN 前置 — 静态资源走 Next standalone bundle + Cloud Run built-in cache headers
- **不**做 WAF custom rule 全面建模 — Cloud Armor 只起 default DDoS shield + 简单 rate limit
- **不**做 SOC2 / PCI 合规 — owner 单租户 + 公开展示，无 PII 收集
- **不**改本地 dev 路径 — `make dev` 还是 SQLite + LocalFileArtifactStore + Next rewrite 假同源

## Dependencies

**依赖**：

- **010** — 010 是单 owner 公开展示模型；012 的 prod cleanup 假设 fresh data start（无 demo 数据），单一 OWNER 账号在启动期创建
- **001** — User / AuthIdentity / RefreshToken 表结构沿用（无 schema 改动，只是 SQLite → Postgres）

**被依赖**：

- **011** (async-run-queue, in-flight) — 011 引入 `run_events` 表 + 可能引入分布式 worker。012 选择 Postgres 而非 SQLite 让 011 多 instance fan-out 成为可能（虽然 011 MVP 仍是单进程 asyncio task）
- 未来 self-evolution 自动重启 / cron-driven scheduled runs — 都要先有稳定的 prod 跑道

## Risks

| 风险 | 处理 |
|---|---|
| **Cloud Run cold start**：首次请求或 idle 后 ~2-5s 启动延迟 | api 服务可选配 `min-instances=1`（~$8/月增量），web 保持 min=0；前端 loading state 覆盖冷启动窗 |
| **Cloud SQL connection storm**：Cloud Run 每个 instance 一个连接池，scale 上去时连接数线性涨 | 用 Cloud SQL Auth Proxy 共享或 SQLAlchemy `pool_size=2, max_overflow=0` 限单 instance 连接数；db-f1-micro 上限 25 conn |
| **OAuth callback URL 切换**：dev 是 `http://localhost`，prod 是真实 https 域名 | env 驱动 `UTEKI_OAUTH_REDIRECT_BASE`；GitHub / Google OAuth app 注册 2 个 callback URL（localhost + prod）共存 |
| **Postgres ALTER TABLE pattern**：`core/db.py` 的 `_ensure_*_column` 在 SQLite 上跑过，Postgres 上语法兼容但要复测 | PR β 强制跑 `pytest --use-postgres` smoke；alembic 取代 inline ALTER 的迁移列在 future PR |
| **Secret Manager rotation 时 Cloud Run env 不会自动 refresh**：旋转 secret 需要新 Cloud Run revision | 文档化：rotation = `gcloud run services update --update-secrets=...`（触发新 revision）；MVP 暂不做自动 rotation |
| **Cloud Build trigger 失败导致 prod 卡住**：偶发 quota 或 image push 失败 | rollback 命令文档化 + 保留 2 个旧 revision 永远可秒回 |
| **GCS 跨用户读漏出**：bucket-level objectAdmin 给 api SA，应用层做 ownership check；若代码 bug 跳过 check，理论上能跨 user 读 | PR α GCSArtifactStore 强制走和 LocalFile 同一份 `_owner_id(run_id, user)` 入口；E2E 复用 010 的跨用户隔离 case |
| **首次部署 OAuth callback domain mismatch**：在 GitHub / Google 改 callback 前 prod 域名跑通，导致登录死循环 | 部署顺序文档化：先 GCLB + 域名 ready → 再 GitHub/Google console 加 callback → 再翻 100% traffic |
| **owner 配 OWNER_EMAILS typo**：自己也登不进 prod | OAuth callback 在校验失败时 log 完整 identity；gcloud SSH 进 Cloud SQL 改表是 escape hatch |
| **GCP credit 烧光后 owner 没切付费**：服务 24h 内自动停 | GCP billing alert 设 $5 / $10 / $50 三档；每月 statement 月初邮件 |
| **同源 GCLB 配错导致 `/api/*` 路由到 web**：表面看是 web 报 404，实际是 URL map 写错 | smoke test step 显式 curl `/api/health` + `/`，分别 assert 200 + 不同 X-Cloud-Run-Service header |

## 改 vs 重做

考虑过把 web + api 合并成一个 Cloud Run service：

- 优势：1 个 service 而非 2 个，少配一次 NEG
- 劣势：web 是 Node、api 是 Python，合并需要 multi-stage Dockerfile 或反向代理 sidecar；scaling 不独立（web 流量峰值会拉起 api instance 烧 LLM 配额担保）；日志和 metric 全混在一起；任一边的 release 都重启另一边

不合并。2 个 service 是正确的 deployment boundary，和 010 的 `apps/web` + `services/api` monorepo 边界对齐。

考虑过用 Cloud Run Jobs 而非 Cloud Run Services 跑 api 的长 pipeline——拒绝，Jobs 不接 HTTP 入口、不能给 web 当 backend；011 解决长 pipeline 用的是 async queue + event log，不需要 Jobs。

## 时间盒预算

5 PR × ~1 工作日 = ~4.5 天，分散到 1 周走完。Cost：上线后约 $5-12 / 月（含 Cloud SQL ~$8、Cloud Run idle ~$0、GCS ~$0.5、Secret Manager ~$0.5、GCLB ~$18 minimum forwarding rule fee……GCLB 是大头）。Credit 覆盖 30+ 月。

GCLB minimum fee 是唯一不能 scale-to-zero 的成本，是同源方案的明面代价。子域方案可以省掉这 $18——但前述 5 项 cookie / CORS 复杂度足以抵消。
