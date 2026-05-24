# 006 · Design

## 三个新 skill

### `skills/planner/` — Planner

System prompt：
> You are the Planner. Given a 1-2 sentence user intent, expand it into a research spec.
> Be **ambitious about scope, vague about implementation** — let the Generator decide *how*.
> Always emit `plan.md` + `sprint-contract.json` artifacts.

Workflow:
1. yield plan event with high-level steps
2. write `plan.md` artifact (human-readable spec)
3. write `sprint-contract.json` artifact:
   - intent / scope / acceptance_criteria / max_iterations
4. emit `await_review` if compliance_mode (M5 默认跳过)

Acceptance criteria 由 planner 凭 system prompt 自由发明；模板示例：
- 至少含 X 个公司名 + ticker
- 估值段必须含具体 PE/PB 数字
- 调用工具 N 次（针对必要的数据点）

### `skills/evaluator/` — Evaluator

System prompt：
> You are the Evaluator. You are **skeptical by default**.
> ...
> Read the sprint contract's acceptance criteria one by one. For each criterion,
> run the named verifier against the draft and the run trace. Output a JSON
> verdict + actionable feedback. Approve only if all *must* criteria pass.

Workflow:
1. read `sprint-contract.json` + `draft-*.md` + access run.events
2. for each criterion, call the verifier:
   - `regex_in_text(pattern, target)` —— mock 实现：Python re.search
   - `tool_call_in_run(tool_name)` —— 查 run.events 里有没有
   - `numeric_in_range(name, lo, hi)` —— 从 draft 抓数字
   - `llm_judge_score(rubric, min_score)` —— **占位**，007 真接 LLM
3. write `eval-report.json`：
   ```json
   {
     "decision": "approve" | "revise" | "reject",
     "verdicts": [{"criterion_id": "C1", "passed": true, "notes": "..."}],
     "suggestions": ["explicitly include PE for top 3 names", ...]
   }
   ```

`decision="revise"` → pipeline 回 generator 跑下一轮，把 suggestions 喂进去。

### `skills/pipelines/research_pipeline.py` — Meta-skill

不是普通 BaseAgent；继承 `BaseAgent` 但自己**调用其他 skill**。需要 harness 支持"sub-skill 复用同一 run"。

最简实现：直接在 pipeline 内部 import + 调 skill 的 `run()`，把 yield 的事件包装一层（`subagent_start` / `subagent_end`）后透传给 harness。Tool executor 共用 harness 注入的；artifacts 共用同一 run。

```python
class ResearchPipeline(BaseAgent):
    name = "research_pipeline"
    
    async def run(self, messages):
        # Phase 1: Planner
        yield AgentEvent(type="subagent_start", data={"name": "planner"})
        async for ev in self._delegate("planner", messages):
            yield ev
        yield AgentEvent(type="subagent_end", data={"name": "planner"})

        contract = json.loads((await self.artifacts.read("sprint-contract.json"))[1])
        
        for iteration in range(contract["max_iterations"]):
            # Phase 2: Generator
            yield AgentEvent(type="subagent_start", data={"name": "research", "iteration": iteration})
            async for ev in self._delegate("research", messages, contract=contract):
                yield ev
            yield AgentEvent(type="subagent_end", data={"name": "research"})

            # Phase 3: Evaluator
            yield AgentEvent(type="subagent_start", data={"name": "evaluator"})
            async for ev in self._delegate("evaluator", messages):
                yield ev
            yield AgentEvent(type="subagent_end", data={"name": "evaluator"})

            report = json.loads((await self.artifacts.read("eval-report.json"))[1])
            if report["decision"] == "approve":
                break
            # else: append eval suggestions to messages, loop
            messages.append(ChatMessage(role="user",
                content=f"Evaluator suggests revisions:\n{report['suggestions']}"))
```

`_delegate(name, messages, **kwargs)` —— 取目标 skill instance，注入 tool_executor + artifacts（同 harness），调 `.run()` 异步迭代 yield 上来。

## 新事件类型

```python
EventType = Literal[..., "subagent_start", "subagent_end", ...]
```

前端 Trace 把 subagent_start/end 之间的事件**缩进显示**，做成嵌套树。

## SkillRegistry 调整

`SkillRegistry.register` 加 metadata：

```python
default_skills.register(
    ResearchPipeline(),
    description="完整研究流水线：Planner → Generator → Evaluator → 迭代",
    version="v1",
    default_tools=[],  # pipeline 不直接用 tools
    default_model="anthropic/claude-sonnet-4-6",
    kind="pipeline",   # 新字段
)
```

`SkillEntry.kind: Literal["skill", "pipeline"] = "skill"`。

## API

无新端点；走 `agent="research_pipeline"`。`/api/agents` 自动展示。

## 关键文件

**新建**：
- `services/api/src/uteki_api/skills/planner/` (SKILL.md + __init__.py)
- `services/api/src/uteki_api/skills/evaluator/` (SKILL.md + __init__.py + `verifiers.py`)
- `services/api/src/uteki_api/skills/pipelines/__init__.py`
- `services/api/src/uteki_api/skills/pipelines/research_pipeline.py`
- `services/api/src/uteki_api/eval/cases/research-pipeline-end-to-end.json`

**修改**：
- `services/api/src/uteki_api/skills/__init__.py` —— 注册新 skills + pipeline
- `services/api/src/uteki_api/skills/research/__init__.py` —— 接受可选 contract 参数（如果存在 contract，把 acceptance_criteria 拼进 prompt）
- `services/api/src/uteki_api/skills/registry.py` —— `SkillEntry.kind`
- `services/api/src/uteki_api/schemas/events.py` —— 加 subagent_start / subagent_end
- `apps/web/components/agent/Trace.tsx` —— 缩进渲染 subagent block

## 重要复用

- 005 的 `RunArtifacts` —— planner / evaluator / pipeline 都用
- M3 的 `_tool_executor` —— sub-skill 复用同一 executor
- `tools/` 不动 —— evaluator 的 verifiers 是独立模块，不进 ToolRegistry（不暴露给 generator LLM）
