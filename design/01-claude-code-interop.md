# 01 · uteki ↔ Claude Code 互操作 — 设计空间

> uteki 是投研 agent，Claude Code 是开发用的通用 agent。两个 agent 之间能怎么协作？

## 一、设计空间的三个方向

分清 "caller / callee" 关系，设计空间立刻干净：

| 方向 | uteki 角色 | Claude Code 角色 | 技术抓手 | 实现成本 | 解锁的能力 |
|---|---|---|---|---|---|
| **A: uteki → CC** | caller | 工具/子代理 | Claude Agent SDK 或 `claude` CLI 包成 `Tool` | 低 | 用 CC 的通用能力（长文、grep、shell）补 uteki 工具栈 |
| **B: CC → uteki** | 域内服务 | 决策者/操作员 | uteki 暴露 **MCP server** | 中 | CC 拿到 uteki 全部 skill 能力，做"人 + CC + uteki"的三方协作 |
| **C: 闭环** | 被评者 + 被改者 | 外部评审 + 改写器 | MCP + slash command + 自我进化文件流 | 高 | uteki 自我演化，用 CC 当外部 evaluator——详见 [`02-self-evolution-loop.md`](./02-self-evolution-loop.md) |

## 二、方向 A：uteki 把 Claude Code 当工具用

最不性感但最快上手。Claude Code 的优势是它**已经会读长文档、grep 代码、跑 shell**——这些技能 uteki 自己实现一遍是浪费。

### 具体接入路径

```python
# services/api/src/uteki_api/tools/claude_code.py
class ClaudeCodeTool(Tool):
    name = "claude_code"
    description = "Delegate to Claude Code for long-doc analysis, repo grep, ..."

    async def run(self, prompt: str, working_dir: str | None = None) -> ToolResult:
        # Option 1: subprocess + claude CLI
        proc = await asyncio.create_subprocess_exec(
            "claude", "-p", prompt,
            cwd=working_dir, stdout=PIPE, stderr=PIPE,
        )
        # Option 2: Claude Agent SDK (Python) — cleaner, structured messages
        # from claude_agent_sdk import query
        # async for msg in query(prompt=prompt): ...
```

注册进 `default_registry`，把 `claude_code` 加进某些 skill 的 `DEFAULT_TOOLS`。这一步基本不动 uteki 架构——skill 只 yield `tool_call`，harness 调度，CC 就是又一个工具。

### 适合用 CC 而不是 uteki 自己 tool 的场景

- "读这份 200 页 10-K 找经营性现金流变动的脚注"——CC 的 Read tool 可以分段处理
- "在 github.com/owner/repo 里找所有提到 'cuda kernel' 的 commit"——CC 已经知道怎么调 gh
- "拿到这家公司的开源依赖列表，逐个查 CVE"——CC 会自然地组合多个 tool

### 不适合的场景

- 需要金融领域 prompt（uteki 自己的 SKILL.md + guardrails 更精准）
- 需要严格的 cite-or-flag 纪律（CC 没有 uteki 的引用约束）
- 高频小调用（subprocess 启动成本高）

## 三、方向 B：Claude Code 把 uteki 当 MCP server 用

**这是最该投入的方向**。把 uteki 现有的 skill catalog（research / earnings / pipeline / evaluator）一次性变成 Claude Code 的工具，几乎不用改 uteki 内部代码。

### MCP server 暴露面（建议从 5 个工具起步）

```
mcp__uteki__list_skills          → 当前 registry
mcp__uteki__research             {question, model?} → {run_id, summary, artifacts[]}
mcp__uteki__run_pipeline         {question} → {run_id, plan, draft, eval-report}
mcp__uteki__get_run              {run_id} → 完整 Run + events
mcp__uteki__read_artifact        {run_id, name} → 文件正文
```

### 技术选型

- FastAPI 已经在，最简单是用 `mcp-server-fastapi` 之类的 adapter
- 或者写一个独立的 `services/api/src/uteki_api/mcp/server.py`，与 HTTP API 共用 `default_skills` / `default_run_store` / `current_user`

### 这一步之后能做的事

用 Claude Code 在终端：

```
> 我想看半导体设备板块，请用 uteki 出一份框架，然后你审一下
[CC] 调 mcp__uteki__run_pipeline(question="半导体设备板块研究框架")
     → 拿到 run_id = "ab12cd34"
[CC] 调 mcp__uteki__read_artifact(run_id, "final-research.md")
     → 读到 markdown
[CC] 我看 sector overview 段没引用具体数据点，估值水平的 "PE 30x" 没源
     → 建议重跑：要求每个数字都附 [^source: ...]
[CC] 调 mcp__uteki__run_pipeline(...) 加约束
```

这是 **agent 互相 review** 的最低成本实现。Claude Code 不需要懂金融——它只需要会读 markdown、识别缺源、提改进意见。

### 三个复杂点（值得想清楚再动手）

1. **MCP 没有 user 概念**——uteki 的多租户契约依赖 `Depends(current_user)`。最直接的办法：MCP server 进程启动时绑定一个固定 user（dev 用 demo@local；prod 给 CC 分配一个 service account），所有 MCP 调用都以这个 user 身份操作。隔离边界往外推一层（这台 CC 实例就是这个 user）。

2. **SSE 不友好**——MCP 工具调用是 request/response，不是 streaming。所以 `mcp__uteki__run_pipeline` 不能流式回 deltas，而是"启动 → 返回 run_id → CC 主动 poll get_run"。或者改成阻塞到 done 才返回（pipeline 一般 2 分钟，可以接受）。

3. **预算上下文丢失**——CC 的对话上下文 + uteki 一次 run 的 markdown 可能很大。MCP 工具返回内容会塞进 CC 的 context window。建议 `read_artifact` 默认只返回前 N 字 + summary，CC 显式要求才返回全文。

## 四、方向 C：闭环 self-evolution

把 CC 拼成 uteki 的**外部 evaluator**——满足 Anthropic 的 "Evaluator must use a different model" 原则的极致版本（不只是不同模型，是不同**架构** + 不同**工具栈** + 不同**视角**）。

这个方向太重要，已经拆出独立文档 → [`02-self-evolution-loop.md`](./02-self-evolution-loop.md)。

简要说：
- uteki 跑 run → 产 artifacts
- 触发 CC 子进程，喂给它 artifacts + SKILL.md + spec
- CC 输出 critique + SKILL.md 的 diff + rubric 的 diff
- 人审 → apply → A/B → 人再审 → adopt or rollback
- 全程留痕，可回放、可 rollback

为什么用 CC 做这个特别有价值：
- **uteki 的 `Evaluator` skill 是 in-process**——它读同一份 run-trace、用同一个 LLM provider 池、guardrails.md 也是它训练上下文的一部分。它的盲点是结构性的。
- **Claude Code 是真正的"外人"**——它没看过 SKILL.md，对你 prompt 风格没偏好，会指出你内部 evaluator 看不出来的问题。
- **闭环的"自我进化"在 uteki 内部很难做**（让 evaluator 改 prompt 然后让自己用，meta 风险大），但用 CC 做就变得正常——CC 给建议，人审，人合并。

## 五、可执行的"第一刀"

如果只能投一周，按这个顺序：

1. **写一个最小 MCP server**（方向 B），暴露 `list_skills` + `research` + `get_run` + `read_artifact`。绑定 `demo@local`，跳过 auth 复杂度。**这一步让 CC 立刻能用 uteki**。
2. **在 CC 这边写 `.claude/commands/uteki-review.md` slash command**，预填好"读 run_id 的所有 artifacts + 对应 SKILL.md，输出 critique"的 prompt 模板。**这一步让 CC 立刻能 review uteki**。
3. **跑两次 real-LLM pipeline，让 CC review 结果**——人在循环里看 CC 的 critique 质量。如果质量 OK，再考虑把这步自动化到方向 C。

方向 A 留到真有"CC 比 uteki 自己工具好"的具体场景再做。它是 nice-to-have，不是 unlock。

## 六、何时回到这份文档

- 决定要投资某个方向时 → 把对应方向拆成 `openspec/changes/<NNN>-...` 提案
- 三个方向都跑通后 → 这份文档归档（或并入更大的"agent ecosystem"文档）
- 出现第四个方向（例如 uteki 反过来 host 一个 CC sub-agent）→ 在这里补一栏
