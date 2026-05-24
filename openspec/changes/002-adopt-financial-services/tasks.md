# 002 · Tasks

> 单位 ≤ 4h。按依赖顺序。

## Phase 1 — 基础设施

- [ ] **T1.1** 加 `THIRD_PARTY_NOTICES.md`，附 anthropics/financial-services commit hash + Apache-2.0 全文链接
- [ ] **T1.2** `scripts/fork-financial-services.sh` — 克隆指定 commit，按映射表抽取 markdown 到 uteki skills 目录，加 fork header
- [ ] **T1.3** `skills/loader.py` — `load_skill_markdown(name) -> (system_prompt, refs)`，含 guardrails 前置
- [ ] **T1.4** `skills/_shared/guardrails.md` — 写满 5 条公共防线（见 design.md）

## Phase 2 — Research skill 迁移

- [ ] **T2.1** 跑 fork 脚本拉 `market-researcher.md` 主 prompt + 4 个子技能 markdown
- [ ] **T2.2** `skills/research/skill.py` 改用 `load_skill_markdown("research")`；删除原 mock 字符串
- [ ] **T2.3** `current_signature()` 改用 SHA(prompt) 作 prompt 字段；启动后 evolution store 自动 bump 到 v2
- [ ] **T2.4** 验证：`make dev` → POST `/api/agent/chat` agent=research → harness 仍 ok（暂用 mock LLM，看 system prompt 已加载）

## Phase 3 — Earnings skill 新增

- [ ] **T3.1** 拉 `earnings-reviewer.md` 进 `skills/earnings/`
- [ ] **T3.2** `skills/earnings/skill.py` 实现 `EarningsSkill(BaseAgent)`
- [ ] **T3.3** 注册到 `default_skills`，更新 `/api/agents` 输出
- [ ] **T3.4** 前端 `/agents` 页确认显示

## Phase 4 — 新 event 类型 + 前端

- [ ] **T4.1** `schemas/events.py` 加 `await_review` / `unsourced` 到 `EventType`
- [ ] **T4.2** `components/agent/Trace.tsx` 加这两个事件的渲染（橙色"待审核"条 / 红色"未引用"高亮）
- [ ] **T4.3** harness 接受 `compliance_mode: bool` 构造参数；user-triggered + compliance_mode=true → `await_review` 暂停 run，写 `status="awaiting_review"`
- [ ] **T4.4** `/api/runs/{id}/approve` 接口，前端 run 详情页加"通过"按钮

## Phase 5 — Eval case + 真测

- [ ] **T5.1** 新增 `eval/cases/research-sector-primer.json`
- [ ] **T5.2** 新增 `eval/cases/research-cite-required.json`
- [ ] **T5.3** 在依赖 003 完成后（真 Claude），跑一次 `/api/eval/run`，记录 baseline pass_rate

## Phase 6 — 落 spec

- [ ] **T6.1** 整理 `openspec/specs/skills/spec.md`（skill 协议、loader 行为、guardrails 清单、event 类型）
- [ ] **T6.2** 移动本 change 目录到 `openspec/changes/archive/002-adopt-financial-services/`
