# 013 · Tasks

5 PR,每个独立可发可回滚。PR α-γ 是后端;δ 是前端;ε 是 baseline 标注。
末尾每个 PR 都 e2e 跑过 81/81 再 push。

## PR α — Run 模型 deltas + RunFeedback 表(~半天)

> 完全独立的 schema 改动。落地后旧代码完全不感知。

- [ ] **Tα1** `runs/models.py` 加 `auto_score: float | None` + `score_breakdown: dict | None`
- [ ] **Tα2** `runs/sql_models.py` 加对应列(SQLite + Postgres 都用 SQLModel 自动建)
- [ ] **Tα3** 新建 `runs/feedback_models.py` 定义 `RunFeedback`(SQLModel,主键 `(user_id, run_id)`)
- [ ] **Tα4** `runs/feedback_store.py` 提供 `upsert` / `get` / `list_by_user` / `list_flagged`
- [ ] **Tα5** `auth/roles.py` 加 `PERM_ANNOTATE_RUNS = "runs:annotate"`,塞进 admin 的 permissions list
- [ ] **Tα6** `auth/deps.py` 加 `require_perm(name)` 依赖工厂(参数化版的 require_admin)
- [ ] **Tα7** e2e:新建 `tests/e2e/test_21_run_feedback_chain.py` 覆盖 upsert / 重写 / 没权限 403
- [ ] **Tα8** `./scripts/e2e.sh` 全过 → commit + push

## PR β — Outcome judge(~1 天)

- [ ] **Tβ1** `eval/judges/outcome.md` 写 rubric(用 007 的 frontmatter 格式),含 1-5 评分 + "Unknown" 逃生 + judge model 优先级
- [ ] **Tβ2** `eval/judges/dispatcher.py` —— `JudgeDispatcher.score(run_id)` 骨架,exception-isolated
- [ ] **Tβ3** outcome judge 实现:加载 run + summary + primary artifact → stream judge model → parse JSON `{score: int, rationale: str, unknown: bool}`
- [ ] **Tβ4** 写回 `run.score_breakdown["outcome"]`,**只是这一维**,cost 留空
- [ ] **Tβ5** `runs/store.py:finish()` 接钩子,`asyncio.create_task(dispatcher.score(...))` fire-and-forget
- [ ] **Tβ6** 新 settings:`UTEKI_RUN_EVAL_ENABLED`(默认 false,prod 上线再开)+ `JUDGE_TARGETS=["research","company_research_pipeline"]`
- [ ] **Tβ7** e2e 跑通(judge 默认 disabled,test 不受影响)
- [ ] **Tβ8** mock-LLM 模式下 judge **跳过**(因为整条 mock 链就是 placebo)

## PR γ — Cost discipline rule(~半天)

- [ ] **Tγ1** `eval/judges/cost.py` 实现 `cost_discipline(run, baseline)` 规则
- [ ] **Tγ2** `baseline` = 同 skill 近 30 天 p50 `cost_usd`,1h 内存缓存
- [ ] **Tγ3** dispatcher 同时调用 outcome + cost,聚合写回 `auto_score`(weighted: outcome 0.7, cost 0.3)
- [ ] **Tγ4** Run.auto_score 终于 not-null
- [ ] **Tγ5** e2e 全过

## PR δ — `/runs/[id]` rating 面板 + `/runs` score badge(~1 天)

- [ ] **Tδ1** `apps/web/lib/api.ts` 加 `setRunFeedback` / `getRunFeedback` 客户端
- [ ] **Tδ2** `apps/web/components/runs/RunRatingPanel.tsx` 新建:
  - 默认 collapsed,点开才展开
  - `canOperate(user, "runs:annotate")` gate(没权限直接 return null)
  - 👍/👎 切换 + notes textarea + 🚩 flag
  - **标完后才显示 auto 分**(`/feedback` 接口 GET 时,后端只有当 `existingFeedback` 时才回 score)
- [ ] **Tδ3** `apps/web/app/(app)/runs/[id]/view.tsx` 接入面板
- [ ] **Tδ4** `apps/web/app/(app)/runs/page.tsx` 列表加 `⭐ score` badge(只 annotator 看到)
- [ ] **Tδ5** URL 加 `?flagged=1` 过滤
- [ ] **Tδ6** 前端 typecheck 通过 → ship

## PR ε — Calibration baseline 标注(~1 天,纯人工)

> 不写代码,只是 PR α-δ 上线后,集中标 20 条作为日后 calibration 的真值。

- [ ] **Tε1**(我做)gem 出"明显失败"候选 10 条:`harness_status in (error, timeout)` 或 events 含 `max_steps_exceeded` 或 cost > p99
- [ ] **Tε2**(你做)从 `/runs?harness_status=ok` 随机挑 10 条
- [ ] **Tε3**(你做)20 条全标完,每条至少 1 句 notes
- [ ] **Tε4** 检查 baseline 平衡(👍 / 👎 大致 1:1,不要全偏一边)
- [ ] **Tε5** docs:在 `openspec/specs/evaluation/spec.md` 加一段记录"baseline 20 条标注时间 + κ 等待 Phase 2"

## 完成判据

- Phase 1 完成 = α-δ 都 ship + ε 标完 20 条
- `UTEKI_RUN_EVAL_ENABLED=true` 上 prod
- 看 `/runs` 列表每个 research 跑完都浮现 ⭐ 分
- 你标 20 条后 `/runs/[id]` 的 auto 分能正确显示
- e2e 81/81 全过

## Phase 2(留给下一个 change,不在 013)

- judge calibration cron(Cohen's κ)
- `/admin/review` 独立队列页
- trajectory judge(可选)
- `extra_permissions` field + admin UI 单独授权
- A/B 跨 skill_version 对比页

## 改动文件 inventory

| 文件 | PR | 改动 |
|---|---|---|
| `runs/models.py` | α | + 2 字段 |
| `runs/sql_models.py` | α | + 2 列 |
| `runs/feedback_models.py` | α | 新 |
| `runs/feedback_store.py` | α | 新 |
| `auth/roles.py` | α | + 1 permission |
| `auth/deps.py` | α | + require_perm() |
| `api/runs.py` | α | + 2 endpoints |
| `tests/e2e/test_21_run_feedback_chain.py` | α | 新 |
| `eval/judges/outcome.md` | β | 新 rubric |
| `eval/judges/dispatcher.py` | β | 新 |
| `runs/store.py` | β | finish() 接钩子 |
| `core/config.py` | β | + 2 settings |
| `eval/judges/cost.py` | γ | 新 |
| `apps/web/lib/api.ts` | δ | + 2 client functions |
| `apps/web/components/runs/RunRatingPanel.tsx` | δ | 新 |
| `apps/web/app/(app)/runs/[id]/view.tsx` | δ | 接面板 |
| `apps/web/app/(app)/runs/page.tsx` | δ | + score badge |
| `openspec/specs/evaluation/spec.md` | ε | + 一段 baseline 记录 |

总:**~ 8 个新文件 + 9 个改文件**,后端 ~400 行,前端 ~250 行。
