# 007 · LLM-as-judge Evaluator + Prompt-tuning Loop

## Problem

006 的 evaluator 用 regex / tool_call 检查能挑出**结构性**缺陷（"没含 PE 数字"、"没调 news_search"），但挑不出**质量**问题：
- 写作风格平庸（"AI slop"）
- 逻辑跳跃 / 论证缺环
- 数据相关性弱（调对了工具但用错了数字）
- 中文表达生硬

Anthropic 文章给的关键武器：
1. 让 LLM 作 judge（用**不同模型**评分，避免自评偏差）
2. 在 system prompt 里写"museum quality" 这类高杠杆指令，能从根上拔高输出

uteki 还缺：
- LLM-judge 实装（006 的 `llm_judge_score` 是占位）
- **Prompt-tuning loop 工作流**：改 prompt → 跑 eval 套件 → 对比 baseline → 推 v_n+1 / 回滚

## Solution

### 1. LLM-as-judge

`eval/judges/` 新模块，每个 judge 是一个 system prompt + rubric：

```
eval/judges/
├── correctness.md        # rubric: 数据是否被 tool 引用 / 论证是否成立
├── coverage.md           # rubric: 是否覆盖 spec 全部维度
├── style.md              # rubric: 中文流畅度 / "museum quality" 风格 / 避免 AI slop
└── cite_compliance.md    # rubric: 数字必须有 tool_result 出处
```

调 `eval_judge(rubric_name, draft, run_events, judge_model="aihubmix/claude-sonnet-4-5-20250929") -> JudgeScore`：

```python
class JudgeScore(BaseModel):
    rubric: str
    score_1_to_10: int
    pass_threshold: int                # 默认 7
    rationale: str
    specific_issues: list[str]
```

**关键约束**：judge_model **必须不同于** generator 的 model —— 避免"自己评自己"。
- DeepSeek 写的 → Claude 评
- Claude 写的 → DeepSeek 评

Evaluator skill（006）调用 `llm_judge_score` verifier 时，按 rubric 选 judge prompt，结果落入 eval-report.json。

### 2. Prompt-tuning loop

`scripts/tune-prompt.sh`：

```bash
./scripts/tune-prompt.sh skills/research/SKILL.md
```

行为：
1. 跑当前 eval 套件 → baseline pass_rate + 每 case judge_score 平均值
2. 提示用户编辑 SKILL.md（开 $EDITOR）
3. 保存后重跑 eval → 新结果
4. 输出对比表（baseline vs new）—— pass_rate / judge_score 各 rubric 差值
5. 询问 "keep / rollback / write changelog"
6. 选 keep → evolution_store 自动 bump 到 vN+1（因为 SHA 变了）
7. 选 rollback → git checkout SKILL.md 恢复

辅助：`/api/eval/run?skill=research&judges=correctness,style` —— 跑指定 rubric 集合并落库为 baseline 比较点。

### 3. 漂移告警

每天定时跑一次 eval；如果 pass_rate 比 7 天前 -10% 以上 → emit 一个 RemoteTrigger event 提醒用户（005.2 之后接通钉钉 / Slack webhook）。

## Non-goals

- **不**做完整 A/B 测试框架（只是 baseline 对比）
- **不**做评测数据集管理 UI（cases 还是 markdown / json 文件）
- **不**做实时 prompt 编辑 web UI（CLI 即可）
- **不**为评测改 harness（评测是 harness 之外的元工作流）

## 依赖

- **006-planner-evaluator-pipeline** 已落地（用它的 evaluator skill 作集成点）
- 不依赖 004 / 005.2

## 验收

1. `eval/judges/{correctness,coverage,style}.md` 三个 rubric 文件
2. `EvaluatorSkill` 的 `llm_judge_score` verifier 真接 LLM，跑出非空 JudgeScore
3. `scripts/tune-prompt.sh skills/research/SKILL.md` 跑通：baseline → 编辑 → 对比 → 决定
4. evolution 自动 bump 看到 SHA 变化
5. 跑 demo：故意让 research SKILL.md 加一行 "Always output a single bullet point and nothing else" → eval 全炸（structure / coverage / style 都失败），证明 judge 真在工作；rollback 后恢复
