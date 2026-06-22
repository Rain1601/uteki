# 015 · Tasks

7 PR,每个独立可发可回滚。PR α-γ 是数据 + backend,δ 是前端(UI 第一版 MVP 是 Screen 3),
ε-ζ 是 Backtest + Trends 后做。

每个 PR 末尾跑 `./scripts/e2e.sh` 全过(目标 84+/84+ 不掉绿)再 push。

---

## PR α — Schema + Suite CRUD(~半天)

> 完全独立的 schema 改动,落地后旧代码不感知。

- [ ] **Tα1** `eval/bench_models.py` 定义 `BenchmarkSuite` + `BenchmarkRun` SQLModel
- [ ] **Tα2** `eval/bench_store.py` 提供 `create_suite` / `list_suites` / `get_suite` / `update_queries` / `delete_suite` / `create_bench_run` / `list_bench_runs`
- [ ] **Tα3** `core/db.py` 加迁移(SQLModel 自动建表 + 兼容 SQLite + Postgres)
- [ ] **Tα4** `api/admin.py` 新 section 加 5 个 suite CRUD endpoint(全 `Depends(require_admin)`)
- [ ] **Tα5** Seed `mega-cap baseline` suite(10 ticker × 1 句问题)写到 startup lifespan
- [ ] **Tα6** e2e `tests/e2e/test_24_eval_bench_chain.py`:create → list → get → update → delete + 401/403
- [ ] **Tα7** `./scripts/e2e.sh` 全过 → commit + push

## PR β — Structural metrics + 接入 JudgeDispatcher(~1 天)

> Layer 1 落地,bench-triggered 和正常 prod run 都跑。

- [ ] **Tβ1** `eval/metrics/structural.py` 实现 7 个 structural 指标 + 单元测试(`test_structural_metrics.py`)
- [ ] **Tβ2** `eval/metrics/__init__.py` export 一个 `compute_structural(run_id, artifacts) -> dict` 入口
- [ ] **Tβ3** `eval/judges/dispatcher.py` 在原有 outcome judge 后追加 structural 调用,把结果写进 `Run.score_breakdown["structural"]`
- [ ] **Tβ4** 给 4 个新 LLM rubric axis 写 prompt(`eval/judges/rubric_axes.py`),仍走 outcome judge 框架
- [ ] **Tβ5** e2e `test_25_structural_metrics_chain.py`:跑一条 mock run → score_breakdown 出现 7 个 structural 字段
- [ ] **Tβ6** unit:在 PR α 的 BenchmarkRun 表里跑完一条假 run,确认 metrics_summary 聚合正确
- [ ] **Tβ7** `./scripts/e2e.sh` 全过 → commit + push

## PR γ — Mode A/B 触发 + 并发 fan-out + 聚合(~1.5 天)

> bench run 的执行 layer。深度依赖 PR α + β。

- [ ] **Tγ1** `eval/bench_runner.py` 实现 `run_mode_b(suite, version)` 单次 fan-out 10 run(T=0, N=1)
- [ ] **Tγ2** `eval/bench_runner.py` 实现 `run_mode_a(suite, version_a, version_b)` fan-out 60 run(N=3,T=prod)
- [ ] **Tγ3** 利用刚修的 `SkillRegistry.create()` 做并发安全 fan-out,`asyncio.gather` 限制并发到 5
- [ ] **Tγ4** Aggregate 函数:数值 median / 分类 mode / bool majority,写回 `BenchmarkRun.metrics_summary`
- [ ] **Tγ5** Sample storage 策略 b:跑完 N=3 后只保留 median run 的 artifact,其它两条只留 RunStore + auto_score(artifact_store.delete_run(non_median_ids))
- [ ] **Tγ6** `POST /api/admin/eval/run` endpoint(body: suite_id + mode + versions),返回 bench_run_id 立即,fan-out 在 background task
- [ ] **Tγ7** Cron entry: weekly Mode A on production version (`apscheduler` 或 fastapi-utils repeat_every)
- [ ] **Tγ8** e2e `test_26_bench_runner_chain.py`:Mode B/A 都跑完 + 聚合 + 存储策略验证
- [ ] **Tγ9** real-llm 抽测一次 Mode B(10 run × $0.25 = $2.5)确认串起来
- [ ] **Tγ10** `./scripts/e2e.sh` + real-LLM smoke → commit + push

## PR δ — Screen 3 (A/B Compare) MVP(~1.5 天)

> 第一版可演示 UI。前 3 PR 把数据准备好了,这步 wire 前端。

- [ ] **Tδ1** `apps/web/app/(app)/eval-bench/compare/page.tsx` 主页面
- [ ] **Tδ2** Suite selector + version_a / version_b dropdown(数据从 `/api/admin/eval/suites` 拉)
- [ ] **Tδ3** "Run Mode A" 按钮 → POST `/api/admin/eval/run` → 跳到 bench_run detail
- [ ] **Tδ4** Bench run detail 渲染:5 维矩阵(structural / behavioral / citation / judge / cost)
- [ ] **Tδ5** Per-query 钻取表格 + 点击行打开 v_a vs v_b 双 run 的 side-by-side 文本对比(复用 /runs 详情组件)
- [ ] **Tδ6** "Approve & ship" 按钮:仅记录决策,不动 prompt(写到 BenchmarkRun.metrics_summary["approved_by"])
- [ ] **Tδ7** "Reject" 按钮同样只记录
- [ ] **Tδ8** Loading 状态(bench 跑 50min 期间页面要可用)+ 错误状态 + 空状态
- [ ] **Tδ9** apps/web typecheck 全过
- [ ] **Tδ10** prod smoke + commit + push

## PR ε — Backtest layer(~1.5 天)

> 给我们的 BUY/AVOID 装上 ground truth。最慢见效但最有价值的 layer。

- [ ] **Tε1** `prediction/models.py` + `prediction/store.py`(新表 `prediction`)
- [ ] **Tε2** `tools/market_history.py`:yfinance batch 历史价拉取(单个 helper,~50 行,unit tested)
- [ ] **Tε3** finish_run hook:company_research_pipeline 完成时 → 读 verdict.json → 写一行 Prediction(含 t0_price)
- [ ] **Tε4** `prediction/scoring_cron.py`:daily cron,扫 t0+30/90/180d 已到的预测,更新 outcomes(含 vs SPY)
- [ ] **Tε5** `GET /api/admin/eval/backtest` endpoint:aggregate hit rate by action × by version
- [ ] **Tε6** `GET /api/admin/eval/predictions` endpoint:per-prediction list with drill-down
- [ ] **Tε7** Backfill 脚本(`scripts/backfill_predictions.py`):扫所有已存在的 company run,补 Prediction 记录(supercedes PR ε baseline 标注)
- [ ] **Tε8** e2e + 拉 30 条历史 GOOGL run 做 backfill 抽测
- [ ] **Tε9** commit + push

## PR ζ — Screen 6 (Backtest UI) + Widget(~1 天)

> backtest UI + 在 /skills 页面挂状态条。

- [ ] **Tζ1** `apps/web/app/(app)/eval-bench/backtest/page.tsx` 主页面
- [ ] **Tζ2** Hit rate by action × by version 表格 + 趋势小图
- [ ] **Tζ3** Per-prediction 表格 + 点开看原 run
- [ ] **Tζ4** ⚠ 提醒区:展示 N 条同模式失败预测 + "open as draft prompt-tuning task" 按钮(只记录到 admin notes,不写 prompt)
- [ ] **Tζ5** `apps/web/components/skills/PromptChangeStatus.tsx` widget — 显示 unverified 状态条 + 跑 bench 按钮
- [ ] **Tζ6** `/skills/[name]` 页面顶部挂上 widget
- [ ] **Tζ7** typecheck + prod smoke + commit + push

## PR η — Screen 1 (Overview) + Screen 5 (Trends)(~1 天)

> 第二批 UI,补全工作台 — Overview 屏 + 时间序列图。

- [ ] **Tη1** `/eval-bench/page.tsx` Overview 屏:套件 list + 最近 prompt 改动队列 + 一键跑
- [ ] **Tη2** `/eval-bench/suites/[id]/page.tsx` Suite detail:edit queries + 历史 bench run 列表
- [ ] **Tη3** `/eval-bench/trends/page.tsx`:Recharts 时间序列 + 多 metric 切换
- [ ] **Tη4** Recharts 依赖添加(若还没装)
- [ ] **Tη5** typecheck + prod smoke + commit + push

## PR θ — Screen 4 (Single-run metrics breakdown)(~0.5 天)

> /runs/[id] 详情页加 metrics tab,把单 run 度量解构展示出来。

- [ ] **Tθ1** 右栏加新 tab "Metrics breakdown"
- [ ] **Tθ2** 渲染 structural 7 项 + judge 5 项 + bench context(如果这条 run 来自 bench)
- [ ] **Tθ3** prod smoke + commit + push

---

## 跨 PR 的约束

- 每个 PR **不能**改 prompt 文件(eval workbench 只读)
- 每个 PR 都跑 `./scripts/e2e.sh` 全过
- 每个 PR 末尾跑一次 real-LLM smoke(Mode B / 单条 GOOGL),~$0.25,确认串起来
- 所有 admin endpoint 严格 `Depends(require_admin)`
- 用户身份必须穿透到 backtest 和 prediction,即使 bench-triggered 的 run 也要标 system uid

---

## 时间总览

| PR | 工作量 | 累计 |
|---|---|---|
| α schema + suite CRUD | 0.5d | 0.5d |
| β structural metrics + judge axes | 1d | 1.5d |
| γ Mode A/B runner + 聚合 | 1.5d | 3d |
| δ Screen 3 A/B Compare MVP | 1.5d | 4.5d |
| ε Backtest layer | 1.5d | 6d |
| ζ Screen 6 Backtest UI + widget | 1d | 7d |
| η Screen 1/2/5 Overview + Trends | 1d | 8d |
| θ Screen 4 single-run breakdown | 0.5d | 8.5d |

**总计 8.5 工作日 ≈ 2 周** —— 跟 013 (5 PR) 同量级。

## 里程碑

- **PR δ done**:第一版 demo 可演示 — 选 v3 vs v4 → 看 A/B 矩阵 → 决策
- **PR ε done**:回测数据开始累积,但要等 30/90/180 天才能看 hit rate
- **PR η done**:工作台 6 屏齐备
- **PR θ done**:工作台全部完成,GA 给 admin
