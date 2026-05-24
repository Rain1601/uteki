# 006 · Tasks

## Phase 1 — Planner

- [x] **T1.1** `skills/planner/SKILL.md` —— "ambitious about scope, vague about implementation"
- [x] **T1.2** `skills/planner/__init__.py` —— PlannerSkill；走 LLM；产出 plan.md + sprint-contract.json
- [x] **T1.3** 注册到 default_skills（kind="skill"）

## Phase 2 — Evaluator + verifiers

- [x] **T2.1** `skills/evaluator/verifiers.py` —— 4 个 verifier 函数（regex_in_text / tool_call_in_run / numeric_in_range / llm_judge_score 占位）
- [x] **T2.2** `skills/evaluator/SKILL.md` —— "skeptical by default" + 引用 hermes review prompt 风格
- [x] **T2.3** `skills/evaluator/__init__.py` —— EvaluatorSkill；读 contract + draft，跑 verifier，写 eval-report.json
- [x] **T2.4** 注册

## Phase 3 — Pipeline meta-skill

- [x] **T3.1** `skills/pipelines/research_pipeline.py` —— ResearchPipeline；调 planner → research → evaluator → loop（max 3 iters）
- [x] **T3.2** `SkillEntry.kind` 字段；注册 pipeline
- [x] **T3.3** `_delegate(skill_name, ...)` —— 共用 tool_executor / artifacts

## Phase 4 — Research skill 接受 contract

- [x] **T4.1** research skill 检测 `self.artifacts` 中是否有 sprint-contract.json；存在 → 把 acceptance_criteria 拼进 system prompt 之前
- [ ] **T4.2** earnings 同理（可选；本 change 主要保 research）—— 留作 follow-up

## Phase 5 — Events

- [x] **T5.1** `schemas/events.py` 加 subagent_start / subagent_end
- [x] **T5.2** `apps/web/components/agent/Trace.tsx` 缩进渲染

## Phase 6 — Eval case

- [x] **T6.1** `eval/cases/research-pipeline-end-to-end.json` —— 跑 pipeline，期望 4 个 artifact 都存在

## Phase 7 — Verify

- [x] **T7.1** `agent=research_pipeline` 一次端到端跑通 + 5 个 artifact 全部产生（plan.md, sprint-contract.json, final-research.md, run-trace.json, eval-report.json）
- [x] **T7.2** evaluator revise/reject/approve 三条路径均通过 stand-alone 单元测试验证（pipeline 端到端两次都 approve，说明 planner + research 合作良好；reject 路径需 stand-alone 测试触发）
- [x] **T7.3** /runs/[id] 前端能看到嵌套 trace + 4+ 个 artifact（缩进通过 depth × 16px marginLeft 实现）

## Phase 8 — Spec

- [x] **T8.1** `openspec/specs/pipeline/spec.md` —— pipeline 协议
- [x] **T8.2** `openspec/specs/harness/spec.md` —— 加 "sub-skill delegation" 段
- [ ] **T8.3** 移到 archive —— 待 release 时统一处理
