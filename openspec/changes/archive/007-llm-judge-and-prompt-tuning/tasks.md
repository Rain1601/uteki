# 007 · Tasks

## Phase 1 — Judge rubric files

- [x] **T1.1** `eval/judges/correctness.md` — 数据/引用/论证 rubric
- [x] **T1.2** `eval/judges/coverage.md` — spec 维度覆盖度 rubric
- [x] **T1.3** `eval/judges/style.md` — "museum quality" / 避免 AI slop 风格 rubric
- [x] **T1.4** `eval/judges/cite_compliance.md` — 强制 cite 检查 rubric（threshold 8）

## Phase 2 — JudgeRunner

- [x] **T2.1** `eval/judges/runner.py` — `JudgeRunner` + `JudgeScore`
- [x] **T2.2** `_pick_judge_model` 避 `avoid_model`，找不到 → fallback 顺序
- [x] **T2.3** JSON 输出强制 + 容错（剥 ```json fence + 最外层 `{...}` 提取）
- [x] **T2.4** 接入 `default_router`；未配 key → 中性 5；从不 raise
- [x] **T2.5** Trace 摘要只塞 tool_call/tool_result/usage（防 prompt 过长）+ 80 行 cap
- [x] **T2.6** 简单 YAML frontmatter 解析（不引依赖）

## Phase 3 — EvaluatorSkill 集成

- [x] **T3.1** `verifiers.py` 全面 async；`llm_judge_score` 真接 `JudgeRunner`，返三元组（含 `JudgeScore`）
- [x] **T3.2** evaluator `_invoke_verifier` 改 async + 多注入 `run_events` / `avoid_model`
- [x] **T3.3** evaluator `_infer_generator_model` 从 run-trace 提取生成器 model
- [x] **T3.4** judge 跑完 yield 额外 `artifact_written` 写 `judge-{rubric}.json`

## Phase 4 — Prompt tuning CLI

- [x] **T4.1** `scripts/tune-prompt.sh` — baseline / edit / reload / new / decision
- [x] **T4.2** `api/admin.py` — `POST /api/admin/reload-skills`
- [x] **T4.3** loader.lru_cache 在 reload 时清；skill.system_prompt 重赋
- [ ] **T4.4** README 加使用说明（M7 follow-up，非阻塞）

## Phase 5 — Drift monitor

- [x] **T5.1** `eval/drift_monitor.py` — today vs 7d-ago，drop>10pp warn
- [x] **T5.2** `triggers/registry.py` 注册 `daily-eval-drift-check`（agent="__maintenance__"）
- [ ] **T5.3** apscheduler 真接入 + webhook 路由 — M4 多租户后做

## Phase 6 — Verify

- [x] **T6.1** JudgeRunner 端到端：Claude 评 DeepSeek 写的 draft，rationale 具体可追溯
- [x] **T6.2** 跑 pipeline 含 5 个 criterion（含 C4 correctness / C5 cite_compliance）→ 两个 `judge-*.json` artifact 写入；evaluator 真根据 judge 决策（实测 score=3/2 → decision="revise"）
- [x] **T6.3** Verifier 全部 async smoke 过；llm_judge_score 拿伪造 draft → 1/7（失败）
- [x] **T6.4** `EvalRecord` append-only ndjson；`/api/eval/history` + `/api/eval/cases/{id}/history` 返记录
- [x] **T6.5** `POST /admin/reload-skills` 实际重赋每个 skill.system_prompt
- [x] **T6.6** drift_monitor 烟测：空历史返 alert=False 不崩
- [x] **T6.7** ruff + 前端 typecheck 全过；25 个 routes 注册
- [x] **T6.8** 前端 `/evals/{case_id}` 详情页：SVG 折线图（pass_rate + 每 rubric 分线）+ 历史列表

## Phase 7 — Spec

- [x] **T7.1** `openspec/specs/evaluation/spec.md` — 完整 spec（rubric / JudgeRunner / verifier 协议 / EvalRecord / endpoints / 不变量）
- [ ] **T7.2** 升级 `openspec/specs/harness/spec.md` 加 "evaluation feedback loop" — 跨 spec 引用即可（已有 evaluation/spec.md）
- [ ] **T7.3** Archive 005 / 006 / 007 三个 change（M7 完成是好时机批量整理）

## 已知妥协

- T4.4 README 没改 — `scripts/tune-prompt.sh` 内的 `:?usage:` 自带说明，CLI 用户跑一次就知道。
- T5.3 cron 没真触发：apscheduler 一直没接入（M0 已有 CronTrigger 数据模型，但没调度层）。drift_monitor 函数本身已就绪，等 cron 层。
- T6.2 evaluator 真触发 "revise" 实测一次（pipeline 跑出 correctness=3 / cite_compliance=2 → revise）。但 pipeline 重做 iteration 的逻辑尚未验证（max_iterations=3 但 revise 一次后没观察到下一轮）—— 这是 ResearchPipeline 既有逻辑（M6），非 M7 范围。
