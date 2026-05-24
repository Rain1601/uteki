# 007 · Design

## LLM Judge

### Rubric 文件

Markdown，YAML frontmatter + 评分细则：

```markdown
---
name: correctness
applies_to: ["research", "earnings"]
pass_threshold: 7
judge_model_preference: ["aihubmix/claude-sonnet-4-5-20250929", "deepseek/deepseek-reasoner"]
---

# Correctness rubric

Score 1-10 on whether the draft's claims are supported by tool_result content.

## 10 — every claim cites a tool or marks [UNSOURCED]
## 7  — most claims sourced; minor gaps
## 4  — over half claims unsourced and not marked
## 1  — fabricates numbers
```

### Judge runner

```python
# eval/judges/runner.py
class JudgeRunner:
    def __init__(self, llm_router: ModelRouter): ...
    
    async def judge(
        self,
        rubric_name: str,
        draft_text: str,
        run_events: list[AgentEvent],
        avoid_model: str | None = None,         # don't let the generator self-grade
    ) -> JudgeScore: ...
```

实现：
1. load rubric markdown
2. 选 judge model：从 `judge_model_preference` 里挑第一个不是 `avoid_model` 的
3. 构造 prompt：rubric + draft + run trace 摘要（不全塞，只塞 tool_call/tool_result/usage）
4. 调 LLM，要求 JSON 结构化输出（response_format=json_schema）
5. 解析返回 `JudgeScore`

### Evaluator skill 集成

`skills/evaluator/verifiers.py` 的 `llm_judge_score(rubric_name, **ctx)` 实装：

```python
async def llm_judge_score(rubric_name, draft_text, run_events, generator_model):
    judge = await default_judge_runner.judge(
        rubric_name,
        draft_text,
        run_events,
        avoid_model=generator_model,
    )
    return judge.score_1_to_10 >= judge.pass_threshold, judge
```

## Prompt-tuning loop (CLI)

`scripts/tune-prompt.sh`：

```bash
#!/bin/bash
# Usage: tune-prompt.sh <skill_md_path>
# 1. baseline = run eval, capture
# 2. open $EDITOR
# 3. on save, re-run eval
# 4. print diff table
# 5. interactive: keep / rollback / abort

PATH_MD="$1"
[ -z "$PATH_MD" ] && exit 1

BASELINE=$(curl -s -X POST localhost:8000/api/eval/run | jq .)
echo "── baseline ──"; echo "$BASELINE" | jq '{pass_rate, results: [.results[] | {case_id, scores}]}'

cp "$PATH_MD" "$PATH_MD.bak"
$EDITOR "$PATH_MD"

# Restart api to reload skill loader cache
curl -s -X POST localhost:8000/api/admin/reload-skills

NEW=$(curl -s -X POST localhost:8000/api/eval/run | jq .)
echo "── new ──"; echo "$NEW" | jq '{pass_rate, results: [.results[] | {case_id, scores}]}'

read -p "Decision? (keep / rollback / quit): " D
case "$D" in
  keep)     rm "$PATH_MD.bak" ;;
  rollback) mv "$PATH_MD.bak" "$PATH_MD" ;;
  *)        echo "left .bak in place" ;;
esac
```

需要新端点 `/api/admin/reload-skills` 把 `load_skill_prompt` 的 lru_cache 清掉，否则改了 markdown 也不重新加载。

## 漂移告警

```python
# eval/drift_monitor.py
async def check_drift():
    today = await run_eval()
    week_ago = await load_baseline_from(timedelta(days=7))
    if today.pass_rate < week_ago.pass_rate - 0.10:
        # emit RemoteTrigger to user-configured webhook (默认 console.log)
```

挂 cron（M0 已有 triggers/registry.py 的 CronTrigger）。

## 关键文件

**新建**：
- `services/api/src/uteki_api/eval/judges/__init__.py`
- `services/api/src/uteki_api/eval/judges/runner.py` — JudgeRunner
- `services/api/src/uteki_api/eval/judges/{correctness,coverage,style,cite_compliance}.md`
- `services/api/src/uteki_api/eval/drift_monitor.py`
- `services/api/src/uteki_api/api/admin.py` — `/admin/reload-skills`
- `scripts/tune-prompt.sh`

**修改**：
- `services/api/src/uteki_api/skills/evaluator/verifiers.py` —— 实装 llm_judge_score
- `services/api/src/uteki_api/skills/loader.py` —— 加 reload helper（清 lru_cache）
- `services/api/src/uteki_api/main.py` —— 挂 admin router
- `services/api/src/uteki_api/triggers/registry.py` —— 注册 daily drift cron

## 重要复用

- 005 的 RunArtifacts —— judge 自身的 prompt + 结果都写为 artifact 留痕
- 006 的 EvaluatorSkill —— llm_judge_score 即接入点
- M1 的 ModelRouter —— judge_model 通过同套路由

## 不在本 change 的

- 评测数据集 web UI
- A/B test 框架
- 多用户的 evaluation runs 隔离（M4 多租户落地后再说）
- 自动 prompt 优化（让 LLM 自己改 prompt）—— 在 hermes background_review 风格里可考虑
