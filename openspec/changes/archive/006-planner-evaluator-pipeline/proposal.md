# 006 · Planner / Generator / Evaluator + Sprint Contract

## Problem

Anthropic 文章核心洞察：**Generator 不会评判自己**。

> "Agents tend to respond by confidently praising the work—even when, to a human observer, the quality is obviously mediocre... tuning a standalone evaluator to be skeptical turns out to be far more tractable than making a generator critical of its own work."

uteki 当前 research 和 earnings 都是单 skill 把所有事做完——它写完研报，没人挑刺。M2 引入 `[UNSOURCED]` 防线后偶有用，但本质上 LLM 还是自评。

引入**显式三角色分工**：

- **Planner**：把一句话需求扩成结构化的 spec（含 acceptance criteria）
- **Generator**：拿 spec 跑工具循环，产出 draft
- **Evaluator**：用 spec 的 acceptance criteria 逐条挑 draft 的毛病，必要时回退给 generator 重做

## Solution

新增 3 个独立 skill + 1 个 meta-skill 把它们编排起来：

```
skills/
├── planner/        # 一句话 → spec.md + acceptance-criteria.json
├── evaluator/      # draft + criteria → eval-report.json
├── research/       # 已有，承担 generator 角色
├── earnings/       # 已有
└── pipelines/
    └── research_pipeline.py    # meta-skill: planner → research → evaluator → loop
```

**Sprint Contract** = 一份 JSON artifact，明确：

```json
{
  "sprint_id": "1",
  "intent": "中国半导体设备板块的行业框架",
  "scope": ["市场规模", "玩家份额", "估值", "风险"],
  "acceptance_criteria": [
    {"id": "C1", "must": "包含至少 3 个公司名 + 对应 ticker", "verifier": "regex_in_text"},
    {"id": "C2", "must": "估值段必须含具体 PE 或 PB 数字", "verifier": "regex_in_text"},
    {"id": "C3", "must": "至少 1 次 news_search 调用", "verifier": "tool_call_in_run"},
    {"id": "C4", "must": "风险段至少 4 条独立条目", "verifier": "regex_in_text"}
  ],
  "max_iterations": 3
}
```

Generator 看 contract 工作；evaluator 用 verifier（一类 mock evaluator 函数：regex_in_text / tool_call_in_run / numeric_in_range / llm_judge_score）逐条打分；不达标 → 把 verdict + 改进建议回写到 contract，generator 看着改。

## Non-goals

- **不**支持 N 个 sprint 串行（Anthropic 后来去掉了 sprint 概念；我们也走单 sprint contract）
- **不**让 evaluator 用 Playwright（不是 UI 任务；用 regex + tool_call_in_run 这两条做主力 verifier）
- **不**改前端核心组件结构（multi-skill pipeline 在前端就显示成嵌套 trace）
- **不**做并行 sub-skill（串行就够）

## 依赖

- **005-artifact-layer**：sprint-contract / spec / draft / eval-report 都是 artifact
- 不依赖 004 / 007

## Risks

- **Iteration loop 失控**：硬性 `max_iterations=3`；超过 → emit `error(reason="iteration_budget_exhausted")` + 当前最好的 draft 仍写入 artifact
- **Evaluator 自己也犯错**：用 "skeptical" prompt template + 复用 hermes 的 background-review 风格。M5+ 的 follow-up 接 LLM-as-judge（在 007）
- **Generator skill 改动**：research / earnings 改造为 generator 角色——保留对外 `agent=research` API 兼容（直接用 research 时仍走单 skill；走 pipeline 时调 `research_pipeline`）

## 验收硬指标

跑一次 research_pipeline：
- 产出 `plan.md`、`sprint-contract.json`、`draft-brief.md`、`eval-report.json` 4 个 artifact
- 至少触发一次 generator 重做（evaluator 拒绝第一版）
- 最终回答比单独跑 research skill 更结构化、引用更完整
