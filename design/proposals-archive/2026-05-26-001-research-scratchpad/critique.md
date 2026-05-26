# /uteki-review · run `fe448bf59604`

> Verbatim output of the first `/uteki-review` invocation on 2026-05-26.
> See [`./README.md`](./README.md) for context.

> skill: `research_pipeline` · model: deepseek + aihubmix · 105s · status=ok · iteration 0 of 3

## 1. TL;DR

这个 run 在 uteki 内部判定**5/6 通过**（只挂 C6 字数），两个 LLM 判官都给了 8-9/10 高分。**但是 final-research.md 实际上是 15KB 的 agent 内心独白**，包含多轮起草、字数估算、"Hmm let me think" 之类的内部思考，真正的成稿被埋在最后一段表格里。这是一个 **uteki 内部 evaluator 完全没看见的产品级缺陷**——更糟的是，C1/C3 还因为 verifier 设计错误"假性通过"。**值得改 prompt**：根因在共享 guardrails 没有"只写交付物、不写思考过程"这条约束，让 5 个 skill 全都暴露在同样的风险下。

## 2. 具体缺陷（5 条，每条带证据）

### **Finding #1: scratchpad 全部落盘成"final"产物** 🔴 highest severity

- `final-research.md` 头 40 行原文：

  > "I need to start by pulling the data from tools for the Chinese semiconductor equipment sector. Let me identify the key players and gather data."
  > ...
  > "Hmm, let me count. That's going to be over 800 probably with the table. Let me think of a better approach"
  > ...
  > "Let me carefully check each criterion: **C1** - ... ✅ **C2** - ... ✅"

- 也就是说：**agent 把它的元思考（数 token、自我评分对照表、多轮重写尝试）直接写进了交付物文件**。真正的中文研究框架在文件最末几屏才出现，混在 4-5 个 draft 版本中间。
- `_shared/guardrails.md` 第 89-99 行 "Output format" 段落规定了"用 Markdown + ## 标题 + 表格 + 引用"，但**完全没说"只写最终交付物，不写思考过程"**。
- 这不是 prompt-injection、不是模型笨——是**guardrails 漏了一条约束**，研究类 skill 全都暴露。

### **Finding #2: C1 verifier 被英文单词假性通过** 🟡

- sprint-contract.json 第 14 行：

  ```json
  "verifier": "regex_in_text",
  "args": {"pattern": "(\\d{6}\\.(SH|SZ)|[A-Z]{2,5})"}
  ```

- eval-report.json 报告 C1 通过，但 `"notes": "matched 1187 occurrence(s); sample: need, to, start"`——**1187 个匹配**，样本是 "need" / "to" / "start"。这些是 agent 思考过程里的英文，**不是股票代码**。
- 根因：`[A-Z]{2,5}` 这个 OR 分支会匹配任何 2-5 字母大写串。"PE"、"PB"、"TODO"、"SMIC" 全算。verifier 在做"找到字母就算"，而不是"找到符合规则的股票代码"。

### **Finding #3: C6 verifier 用了不可能匹配的 regex** 🟡

- sprint-contract.json 第 40 行：`"pattern": "^.{500,800}$"`，没有 DOTALL / MULTILINE flag。
- `.` 默认不匹配换行——任何包含 `\n` 的 markdown 永远不会作为整体被 500-800 长度匹配。
- eval-report.json 报告 C6 失败，原因 `"no match for pattern '^.{500,800}$'"`——而**实际正文长度根本无从知晓**（regex 没真的在数字数）。
- 这条不只是误报；它意味着 **evaluator 的"revise" 决策建立在错误信号上**。如果 C6 写对了，可能其他几条已经全过、决策会变成 approve——那个不发现 scratchpad 问题的"approve"更危险。

### **Finding #4: LLM 判官有结构性盲区** 🔴

- judge-correctness.json 的 rationale 原文：

  > "The only minor gap is that revenue/profit figures **mentioned in the thinking section** were not included in the final draft"

- judge-cite_compliance.json 的 rationale 原文：

  > "**the draft includes a table** with data sourced from tools"

- 两个判官都隐式假设"thinking section"和"final draft"是文件里**两个分开的区域**——判官只对"draft 区域"打分，把外面的内心独白当背景噪音。
- 但**这种 "draft 段落"在文件里不存在**——文件就是一整团思考流。判官**幻想了一个干净的 draft 给自己打分**，所以给出 9/10 + 8/10 高分。
- 这两条 rubric 没有约束 judge 评估"整个交付物是否就绪发表"，只约束了"如果你能找到 draft，draft 里的引用对不对"。这是 rubric 设计层级的盲区。

### **Finding #5: evaluator 给了对的决策但理由错了** 🟢 confirming

- eval-report.json `"decision": "revise"`，唯一未过是 C6（字数）。
- 但**真正应该触发 revise 的缺陷（scratchpad 落盘）没有任何 criterion 在测**——deterministic verifier 测的是结构标记、LLM judge 测的是引用规范。
- 如果偶然 final-research.md 体积恰好让 C6 的破 regex 通过了一次（比如 agent 这次写得短一点没换行），整个 evaluator 会给 approve——而内容质量却没有改善。
- **这是关键警报**：内部 evaluator 的"对"和"错"在统计意义上是脱钩的。

## 3. 建议的 prompt diff

最有 ROI 的一次改动——加在共享 guardrails 里，所有 skill 受益。**改动 12 行**，保留中英风格：

```diff
--- a/services/api/src/uteki_api/skills/_shared/guardrails.md
+++ b/services/api/src/uteki_api/skills/_shared/guardrails.md
@@ -89,6 +89,18 @@
 ## 5. Output format

+### 5a. 交付物只装"成品"，不装"过程"
+
+你写到 artifact 文件（`final-research.md` / `eval-report.json` / 任何
+`self.artifacts.write(...)`）的内容**必须只包含读者要看的最终版本**——
+不能包含你的草稿、字数估算、自我评分对照表、"让我重写一次"之类的过程
+话。读者拿到的是交付物，不是你的工作日志。
+
+检查方法：把你打算写到文件里的内容贴出来，问自己"如果我是分析师只读
+这个文件，我会看到一份完整研究 / 干净判定 / 可发表草稿吗？"如果答案是
+"我会先看到一段思考再看到答案"——**只保留答案那段，把前面的全删掉再写**。
+
+思考过程应当通过 `thinking` 事件流，不是 artifact 内容。
+
 - Final answer in Markdown.
 - Top-level `##` headers map to the plan's named steps.
 - Numbers belong in tables, not in narrative.
```

**为什么放这里、为什么这么写**：

- 放 `_shared/guardrails.md` → 5 个生产 skill 全覆盖，不止 research
- 用中文写正文 → 跟 `addendum_zh.md` 风格一致；guardrails 已经是中英混排
- 加了**自检方法**那一段 → 模型按规则去自我检查比纯禁令有效得多
- 提及 `thinking` event → 给模型留了一个"思考可以去哪里"的合法出口

**配套的 verifier 修复**（不算在 SKILL diff 里，但需要做）：

1. sprint-contract.json 生成时，C1 的 regex 收紧到 `\b\d{6}\.(SH|SZ)\b`（去掉 `[A-Z]{2,5}` 那个 OR 分支）。
2. C6 改成在 verifier 里 `len(text)` 取数，不要用 regex 数行数。
3. 给 `correctness` / `cite_compliance` 这两个 judge rubric 加一句首要约束："**整个文件**作为单一交付物评分。如果文件包含思考/草稿/重写，是缺陷而非附加内容。"

## 4. 这次 review 的元数据

- 用了 5 次 MCP 调用：1 list_artifacts + 4 read_artifact (plan.md, sprint-contract.json, final-research.md, eval-report.json, 2 judges) + 2 Read for SKILL.md + guardrails.md
- 读了 ~20KB 文本（其中 final-research.md 一份就 15KB）
- ~7 分钟，单 review session 成本 ~0
- 真正"贵"的是 finding #4——uteki 自己的 LLM judges 不会发现这个，因为 rubric 本身有结构性盲区。需要靠外部 reviewer 才能看到这一层。

---

## 后续动作（按 ROI 排序）

1. **接受 guardrails diff** → 重启 API → 跑同一个 prompt 再 review 一次。如果 final-research.md 还是 scratchpad，那就是 guardrails 没起作用，要 debug prompt composition。
2. **修 C1/C6 regex** → 重跑同样的 case → 看 pass_rate 是否下降（**期望下降**，因为之前的"通过"是假阳性）。
3. **拓宽 judge rubric** → 让 correctness / cite_compliance 评估"整个文件 as deliverable"。
4. **如果以上都做了**：把这次 critique 落成 `evolution/proposals/2026-05-26-001/` 作为 self-evolution loop 的第一份真实样本。

**给你两个明确选项**（per slash command 结尾）：

- **A**："我接受你说的，apply 这个 guardrails diff + 修 verifier，再跑同样的 prompt 对比"
- **B**："finding 哪条不准——我调整角度"

A 路径估计 30 分钟（diff + reload-skills + 重跑 + 二次 review）。
