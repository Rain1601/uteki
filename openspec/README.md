# openspec — spec-driven change tracking

每个有架构影响的改动都先写一份 proposal，跑完落入 `specs/` 作为该 capability 的真相来源。

## 目录

```
openspec/
├── config.yaml                # 项目上下文 + 写作规则（给 AI 读）
├── changes/                   # 进行中 / 待审 / 已归档的变更
│   ├── <change-id>/
│   │   ├── proposal.md        # 为什么 + 高层方案
│   │   ├── design.md          # 怎么做（架构 / 字段 / 接口）
│   │   ├── tasks.md           # 执行清单（每条 ≤ 4h）
│   │   └── specs/             # 本次改动会动到的 spec 草稿
│   └── archive/<change-id>/   # 完成后挪进来
└── specs/                     # 各 capability 的当前真相
    └── <capability>/spec.md
```

## 何时写

| 改动类型 | 走 spec？ |
|---|---|
| 新增数据模型 / 新增 API 路由 / 新增 skill | ✅ 必须 |
| 改 harness 行为 / 改事件协议 / 改存储接口 | ✅ 必须 |
| 改 prompt / 改 tool 实现 / UI 调整 | ❌ 直接 PR |
| 升级依赖 / 改配置 / 修 typo | ❌ 直接 PR |

## 流程

1. 在 `changes/` 下开新目录，写 `proposal.md`
2. 跟 review 对齐后补 `design.md` + `tasks.md`
3. 实现：按 tasks.md 推进，每条做完打勾
4. 落地后把 `changes/<id>/specs/` 合并进 `specs/` 对应 capability
5. 整个 change 目录挪到 `changes/archive/<id>/`

## 现有 change

- `archive/001-tenant-and-auth/` — 多租户 + 用户系统
- `archive/002-adopt-financial-services/` — 引入 anthropics/financial-services 的 skill 内容（已落地，剩余 review/policy 拆入后续 change）
- `archive/003-anthropic-sdk-integration/` — 接入真实 LLM + usage/cost budget（已落地；真实 key 验证是 ops checklist）
- `archive/004-provenance-citation/` — run-scoped source catalog + citation validation（已落地）
- `archive/005-artifact-layer/` — Artifact 持久化 + await_review checkpoint（✅ M5 实施完）
- `archive/005-artifact-first-runs/` — run detail 以 artifacts 为主，final-report contract + backward-compatible replay（已落地）
- `archive/006-planner-evaluator-pipeline/` — Planner / Generator / Evaluator + Sprint Contract（✅ M6 实施完）
- `archive/006-company-research-pipeline/` — 从 uteki.open 迁移公司 7-gate 投研为 harness pipeline（已落地）
- `archive/007-llm-judge-and-prompt-tuning/` — LLM-as-judge + prompt-tuning loop（✅ M7 实施完）
- `archive/007-trace-diagnosis/` — 从 event trace 派生 failure/cost/tool/citation diagnosis（已落地）
- `archive/008-tool-governance/` — tool risk level + high-risk await_review 真拦截（已落地）
- `archive/009-company-deep-research-v2/` — 公司深研 peer 排序、资金管理、阶段能力 review（已落地）

> 005-007 三步落实 [Anthropic harness 设计原则](https://www.anthropic.com/engineering/harness-design-long-running-apps)：
> - **005** "文件作 agent 通信脊梁" → `services/api/src/uteki_api/artifacts/`
> - **006** "Planner / Generator / Evaluator 分工 + Sprint Contract" → `skills/{planner,evaluator,pipelines}/`
> - **007** "Evaluator 用 LLM-judge + prompt 比架构杠杆更大" → `eval/judges/`

## 已落地 specs（真相来源）

- `specs/harness/spec.md` — agent harness 哲学 + 不变量 + tool-use loop + skill injection
- `specs/artifacts/spec.md` — Artifact 协议（kind / 命名约定 / 路径安全 / 不变量）
- `specs/pipeline/spec.md` — Pipeline meta-skill + Sprint Contract + 嵌套 trace
- `specs/evaluation/spec.md` — LLM-as-judge 协议 + verifier async + EvalRecord history
- `specs/llm-routing/spec.md` — model id 协议 + provider 路由 + UsageDelta
- `specs/provenance/spec.md` — run-scoped SourceCatalog + `[src:N]` citation validation

## 待排队后续 change

目前无排队 change。
