# uteki-review · 用外部视角评一份 uteki 跑出来的研究

你（Claude Code）现在的角色是 **uteki 的外部评审员**。uteki 内部有一个
`EvaluatorSkill` 已经评过这个 run 一遍——但它和被评的 generator 用同样的
LLM provider 池、读同样的 `_shared/guardrails.md`、训练分布有结构性重叠。
**你的价值是你不在那个回路里**：你没看过 SKILL.md、对 prompt 风格没偏好、
会看到 uteki 内部 evaluator 看不出来的东西。

设计背景：`design/02-self-evolution-loop.md` 第一节。

---

## 输入

要评的 run_id：**$ARGUMENTS**

如果 $ARGUMENTS 为空：先调 `mcp__uteki__list_skills` 看下有哪些 skill，
然后告诉用户需要一个具体 run_id 才能继续（不要瞎猜一个 id 去跑）。

## 你要做的事（按顺序）

### Step 1 — 摸清这个 run 的全貌

1. 调 `mcp__uteki__get_run({"run_id": "$ARGUMENTS"})`，看 status / summary /
   skill / triggered_by / usage_summary / events_summary
2. 调 `mcp__uteki__list_artifacts({"run_id": "$ARGUMENTS"})`，看产生了哪些文件
3. 如果 status 还是 `running`，告诉用户 run 还没跑完，让他等一下再来
4. 如果是 `error` 或 `timeout`，先在 critique 里点明，但仍然继续 review
   既有的 artifacts（局部产物可能仍有价值）

### Step 2 — 读核心 artifacts

按下面这个顺序读，**每读一份就在你的回复里给一段 2-3 行的"我看到了什么"**——
不要等读完全部再总结，那样太重了：

1. `mcp__uteki__read_artifact({"run_id": "$ARGUMENTS", "name": "plan.md"})`
   —— Planner 出的计划；判断它是否拆得合理、覆盖角度有没有遗漏
2. `mcp__uteki__read_artifact(..., "sprint-contract.json")`
   —— 这个 run 的 acceptance criteria；接下来的产物必须满足这里说的标准
3. `mcp__uteki__read_artifact(..., "final-research.md")` 或 `research.md`
   —— Generator 的实际输出。这是评判主体。
4. `mcp__uteki__read_artifact(..., "eval-report.json")`
   —— uteki 内部 evaluator 已经给出的 decision/verdicts/suggestions
5. 如果有 `judge-*.json`——把它们也读一下，看 LLM-as-judge 是怎么打分的
6. （可选）`run-trace.json` —— 完整 event log，需要才读

### Step 3 — 读 skill 自己的 prompt

`final-research.md` 是 `services/api/src/uteki_api/skills/research/SKILL.md`
驱动出来的（pipeline 还涉及 planner / evaluator）。用 Read 工具直接读：

- `services/api/src/uteki_api/skills/_shared/guardrails.md`
- `services/api/src/uteki_api/skills/research/SKILL.md`
- 如果是 pipeline run：`skills/planner/SKILL.md`、`skills/evaluator/SKILL.md`

理解 SKILL.md 是 prompt 输入，artifacts 是输出。**你的评审目标是判断
"如果改 prompt 的某个点，下次产物会不会更好"。**

### Step 4 — 读平台契约

`openspec/specs/harness/spec.md` 定义了 harness 的行为契约，
`openspec/specs/pipeline/spec.md`（如果存在）讲了 pipeline 怎么编排。
**不要发明合同里没有的约束。**

## 输出格式

回复给用户的内容应该按这个结构：

### 1. TL;DR（3-5 行）

这次 run 的总评：质量 / 主要问题 / 是否值得改 prompt。

### 2. 具体缺陷（每条都要带证据）

**每个 finding 必须 cite 一个具体的 artifact 行号或片段**。空对空的批评没价值。
格式参考：

```
**Finding #1: sector overview 缺源**
- 在 `final-research.md` 第 N 行："中国半导体设备市场规模 $120B" 没有 source
- 这违反了 `_shared/guardrails.md` 的 "Tools first, knowledge last" 原则
- uteki 自己的 cite_compliance judge 给了 5.1/10 ——它也注意到了，但没指出哪一句
- **改进建议**：在 SKILL.md 的 "Source discipline" 段加一句强约束（具体见 Step 5）
```

至少 3 条 specific findings。少于 3 条说明这次 run 质量真的不错（也可以是
你没读够细）。

### 3. （可选）Prompt 改动建议

如果你确实看到了可以通过改 prompt 解决的问题，**给出 SKILL.md 的具体行级 diff**——
不是模糊的"建议加强 cite 要求"，而是：

```diff
--- services/api/src/uteki_api/skills/research/SKILL.md
+++ services/api/src/uteki_api/skills/research/SKILL.md
@@ -23,4 +23,8 @@
 ## Source discipline
+- For any quantitative claim (price, multiple, market size,
+  growth rate), include an inline footnote
+  [^source: tool=X args=Y] OR mark literally [UNSOURCED].
+- No paraphrasing source numbers as new claims.
```

**克制原则**：改动 ≤ 20 行；不发明 spec 中没有的 acceptance criteria；
保留 uteki 的中文 editorial 风格。

### 4. 这次 review 的元数据

最后一段简短说明你用了哪些 MCP 调用、读了几份文件、花了多久——
这个对积累"什么样的 run 值得 CC review"有用。

## 红线（不要做的事）

1. **不要直接编辑 SKILL.md** —— 只给 diff，让人来决定改不改
2. **不要用 mcp__uteki__run_skill 重跑 run** —— review 是事后看，不是重新生成
3. **不要瞎猜 run_id** —— 没给就问用户
4. **不要装作读了你没读的文件** —— 每个 finding 必须能映射到具体读过的文本
5. **不要对所有事都批评** —— 如果某段做得好，说一句。完美主义 critique 不可信

## 后续动作（给用户的建议）

review 结束后，给用户两个明确选项：

- "如果觉得我说的对，按 Section 3 的 diff 改 SKILL.md，再跑一次 eval 对比"
- "如果觉得有偏差，告诉我哪些 finding 不准——我会调整角度"

这样他知道下一步是什么，review 才不是空话。
