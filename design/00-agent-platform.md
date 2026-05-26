# 00 · Agent 平台现状盘点

> 这是"现在是什么样"的快照，不是提案。基于 2026-05-26 代码状态。

## 一、分层心智模型

```
┌─────────────────────────────────────────────────────────────────┐
│  api/agent.py   ── HTTP 入口（SSE，Auth 网关）                   │
│   ↓ 注入 user_id、读 skill.recommended_limits()                  │
├─────────────────────────────────────────────────────────────────┤
│  AgentHarness   ── 编排层（agents/harness.py，~450 LOC）          │
│   · 6 项硬上限（steps/tools/wall/in/out/cost）                    │
│   · Run 生命周期：run_start → events → done                       │
│   · 双写 memory + run_store（每个 event 都持久化）                 │
│   · 注入 _tool_executor + artifacts → skill                       │
├─────────────────────────────────────────────────────────────────┤
│  BaseAgent (skill)  ── 意图层（agents/base.py）                   │
│   · yield AgentEvent（plan/step/tool_call/delta/...）             │
│   · 不做副作用（不直接调 tool、不写文件、不算预算）                │
│   · recommended_limits() 可声明更宽预算                            │
├──────────────┬──────────────────────────┬──────────────────────┤
│ Leaf skills  │ Pipeline meta-skills      │ Eval / Judge          │
│ research     │ research_pipeline         │ EvalRunner            │
│ earnings     │ (Planner→Research→        │ JudgeRunner           │
│ planner      │  Evaluator 带迭代)        │ drift_monitor         │
│ evaluator    │                           │                       │
│ qna/recap/   │ 通过 artifacts 通信        │                       │
│ screener     │ (文件即 IPC 协议)          │                       │
└──────────────┴──────────────────────────┴──────────────────────┘
                          ↓
┌─────────────────────────────────────────────────────────────────┐
│  Infrastructure（user_id 分区一致贯穿）                          │
│   · LLMRouter（anthropic/deepseek/openrouter/aihubmix + mock）   │
│   · ToolRegistry（7 个工具，统一 OpenAI/Anthropic spec）          │
│   · ArtifactStore（文件系统，data/runs/users/<uid>/runs/<sha>/）  │
│   · RunStore + Memory + EvalHistory（都按 user_id 分区）           │
│   · EvolutionStore（平台级共享，不分区）                          │
└─────────────────────────────────────────────────────────────────┘
```

## 二、最值得称道的 3 个设计决策

### 1. 意图与执行分离 — skill 是纯生成器

`BaseAgent` (`agents/base.py:38`) 只要求实现 `run()` yields AgentEvent。Skill **不调 tool、不写文件、不计预算、不读 store**。所有副作用都在 harness 里发生：

- skill yield `tool_call` 事件 → harness 调度 `ToolRegistry.run` → yield 回 `tool_result`
- skill yield `delta` → harness 累积进 `Run.summary[:200]`
- skill yield `usage` → harness 累积进 `usage_summary` + 即时跑 budget 检查
- skill 调 `self.artifacts.write("plan.md", ...)` → harness 注入的 `RunArtifacts` facade 已经 carry 了 run_id + user_id

**为什么牛**：
- skill 代码 testable、replayable
- 同一份 skill 实现可被多种 harness 复用（eval、compare、real chat）
- 预算/审计/隔离是平台职责，skill 改名变种都跑不丢

### 2. 文件即 Agent 间通信协议（artifact-as-IPC）

`RunArtifacts` facade (`artifacts/store.py:225`) 是 pipeline 的核心抽象。`ResearchPipeline._delegate()` 给每个 sub-skill **共享同一个 artifacts 实例**——所以 Planner 写 `sprint-contract.json` → Research 通过 `self.artifacts.read("sprint-contract.json")` 读到 → Evaluator 读同一份评判。

带来 4 个好处：
- **跨 session 状态**（断点续跑只要文件还在）
- **离线 inspect**（CLI/前端都能直接看 `plan.md`、`eval-report.json`）
- **跨语言互操作**（未来 iOS/Android 客户端读同样的 JSON）
- **单元可测**——给 evaluator 喂一个手工 `sprint-contract.json` 就能跑

### 3. 三层 guardrails — 平台 / skill / run

**平台级**（永远生效）：
- `_shared/guardrails.md` 被 `loader.py:43` 自动 prepend 进每个 skill 的 system prompt（"tools first, knowledge last"、"cite or flag"）
- `HarnessLimits` 默认 6 项硬上限（被实时检查，超即终止）

**Skill 级**（按需放宽）：
- `BaseAgent.recommended_limits()` (`agents/base.py:34`) 让 ResearchPipeline 声明自己的预算（最近 real-LLM 调试发现的硬需求）

**Run 级**（动态）：
- skill 可以 yield `await_review` 让 harness 加 tag、未来 hook 真审批
- 工具结果中的 `error` 也会被 harness 标记进 `final_status`

改 markdown 不动 Python（loader 自动重哈希、`EvolutionStore` 自动 bump 版本）。

## 三、3 个值得继续关注的张力点

### A. Harness 的"任何 error 事件即整 run error"语义过于严格

观察自 real-LLM smoke：pipeline 一个 sub-skill 偶发 error（被 pipeline 自身 catch 并继续），harness 仍把整个 run 标为 `status=error`，即便所有 artifacts 都成功 ship。当前的 workaround 是放宽预算让 error 不再触发，但**根因是 harness 把"任何 error 事件出现过"等同于"运行失败"**。

更准的语义可能是："error 事件存在 + 没有更晚的 successful artifact write" → soft-error。今天没做。

### B. `GeneratorExit` 在 SSE 提前断开时未在多层 async generator 链中干净传播

测试 reporter 中持续看到 `RuntimeError('async generator ignored GeneratorExit')`。`api/agent.py` 加了 try/finally + `agen.aclose()` 但只 cover 了最外层；harness.run 和 pipeline.run 各自的 sub-skill async generator 没有结构化清理。**功能不受影响**（数据 finalize 在正常退出路径上），但日志噪音 + 客户端中断时 run_store.finish 可能未达。

### C. 短期记忆 (`memory/in_memory.py`) 在生产部署日会丢失

`InMemoryStore` 是 dict-backed，进程一重启就空。Long-term `facts` 也只是关键词打分，没有向量检索。文档已经把 "Redis/Postgres + pgvector" 列为 future swap，但现在实际就是 mock。

## 四、骨架完成度评估

| 子系统 | 完成度 | 备注 |
|---|---|---|
| 意图层（skills + harness 契约） | 100% | 已稳定，3 个迭代周期内没改 BaseAgent |
| Tool 调度 | 100% | 7 个工具 + OpenAI/Anthropic 两种 spec 自动转 |
| LLM 路由 | 95% | 4 provider + mock + fallback；缺 streaming 重试 |
| Artifact IPC | 100% | 文件存储 + facade + 多用户分区 |
| Pipeline 编排 | 90% | 跑通了，迭代逻辑 OK；缺 self-evolution（M8 计划） |
| Eval / Judge | 95% | LLM-as-judge runner + 4 个 rubric + history scoping；缺 A/B 模型对比 |
| Drift monitor | 85% | 写好了但**没接通知**（log only） |
| 多租户 | 100% | M4 完成；存储、JWT 轮转、OAuth、隔离全部 E2E 验证 |
| Persistence | 50% | SQLite 用户表 ✓；run/memory 都还是 in-memory（dev OK，生产前必换） |
| Skill 自我进化（M8） | 0% | 设计存在（[`02-self-evolution-loop.md`](./02-self-evolution-loop.md)），未实现 |
| Context 压缩（M9） | 0% | 还没规划 |

## 五、下一步建议（按 ROI 排序）

1. **持久化 RunStore + Memory 到 SQLite**（接口已抽象，~1 天）—— 解决进程重启丢数据的最大风险
2. **修 GeneratorExit 链式传播**（中等复杂度，~0.5 天）—— 清理日志噪音 + 保证客户端断开时数据完整 finalize
3. **harness "soft-error" 语义重新设计**（讨论 + ~1 天）—— pipeline 的预期就是"局部失败继续往下走"
4. **drift_monitor 接 webhook**（已有路由架子，~0.5 天）—— 当前再好的趋势监控也只是日志
5. **M8 self-evolution**（多日，最高 ROI 长远）—— 让 evaluator 反过来改 SKILL.md，闭环。详见 [`02-self-evolution-loop.md`](./02-self-evolution-loop.md)

## 六、整体评价

**骨架完整、抽象清晰、测试给力**。

最大的"虚"：in-memory 持久化、未接通的通知通路。

最大的"实"：skill ↔ harness ↔ artifacts 三层抽象已经稳定到**可以加新 skill 不动 Python 平台代码**——研究领域扩张、工具集扩展、模型 provider 切换都不需要改 harness。
