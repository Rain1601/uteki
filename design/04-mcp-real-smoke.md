# 04 · MCP server real-CC smoke — 验证步骤 + 实测结果

> Status: **as of 2026-05-26**. MCP server stdio handshake + tool dispatch
> 在真 `claude` 客户端环境下已验证。

## 一、最小验证手册（4 步，60 秒）

适用：你在一台新机器上 clone 了 repo，想确认 MCP 链路是通的。

```bash
# 0. 前置：确保 uv 安装了所有依赖
make setup

# 1. 启动 uteki API 在匿名模式（MCP MVP 暂时通过 demo@local 兜底）
cd services/api
UTEKI_AUTH_REQUIRED=false UTEKI_USE_MOCK_LLM=true \
  uv run uvicorn uteki_api.main:app --port 8000 &

# 2. 把 MCP server 注册给 Claude Code（一次性，project-local scope）
cd /path/to/uteki
claude mcp add uteki --scope local -- "$(pwd)/scripts/uteki-mcp.sh"

# 3. 确认健康
claude mcp list
#  应该看到：
#    uteki: /path/to/uteki/scripts/uteki-mcp.sh  - ✓ Connected
```

## 二、协议层验证（无需 claude CLI）

如果 `claude` 不在 PATH 上、或者你想绕过 CC 直接验证 server，用 raw JSON-RPC：

```bash
(
  echo '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"1"}}}'
  echo '{"jsonrpc":"2.0","method":"notifications/initialized","params":{}}'
  echo '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
  echo '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"uteki_list_skills","arguments":{}}}'
  sleep 2
) | ./scripts/uteki-mcp.sh 2>/dev/null
```

预期：3 个 JSON 响应（id=1 initialize 返回 serverInfo；id=2 tools/list 返回 5 个 tool；
id=3 tools/call 把当前 registry 8 个 skill 列出来）。

## 三、实测结果（2026-05-26）

### ✅ 协议层完全通

- initialize → 返回 `{name: "uteki", capabilities: ["experimental", "tools"]}`
- tools/list → 返回 5 个 tools，required-field schema 全对：
  - `uteki_list_skills` (required=[])
  - `uteki_run_skill` (required=["skill", "question"])
  - `uteki_get_run` (required=["run_id"])
  - `uteki_list_artifacts` (required=["run_id"])
  - `uteki_read_artifact` (required=["run_id", "name"])
- tools/call uteki_list_skills → 走通 MCP → HTTP → registry，返回 8 个 skill：
  - `research@v2, earnings@v1, recap@v1, screener@v1, qna@v1, planner@v1, evaluator@v1`
  - `research_pipeline@v1`（kind=pipeline）
- `claude mcp list` 显示 `uteki: ... - ✓ Connected`

### ⚠️ 不能从 Claude Code 内部 spawn 一个 claude 子进程来跑 smoke

实测发现：在 CC 当前会话里执行 `claude -p "..."` 会让子进程**继承当前会话的 system instructions**——
具体观察到的问题：

- 子进程触发了用户 global `CLAUDE.md` 里的"完成响应后 afplay 提示音"指令
- 子进程没调任何 uteki tool，反复调 Bash 去 `afplay`
- 4 turns 用完 max-turns，未实际验证 uteki MCP 调用
- 但成本花掉了 $0.28（Opus）

**含义**：自动化 real-CC smoke test 不能简单 `claude -p` —— 至少需要：
- 隔离的 env（不继承父 CLAUDE.md）
- 或更窄的 `--allowedTools` 限制
- 或者就**只在 fresh terminal session** 里手动跑

工程上的 take-away：用上文 §二 的 JSON-RPC 验证 server 层；**真正的 CC↔uteki 交互测试要在
真实终端**——这是手工 smoke，不是 CI 测试。

## 四、推荐的手工 smoke 脚本

在一个 fresh terminal session 里（**不**是 CC 内部）：

```
$ claude
> Use uteki_list_skills to enumerate the registered skills, then briefly
  describe what 'research_pipeline' does based on its description field.

[CC 应该会]
[tool] mcp__uteki__list_skills → 拿到 8 skill
[answer] research_pipeline is a meta-skill that orchestrates Planner →
        Research → Evaluator with up to 3 iterations, version v1, kind=pipeline.
```

只要这一步通了，方向 B（CC 作为 caller 用 uteki）就已经 unlock。

下一档加大输入：

```
> Use uteki to run a small 'qna' query asking "what is FOMC", then read the run summary.

[CC 应该会]
[tool] mcp__uteki__run_skill(skill="qna", question="what is FOMC")  → run_id
[tool] mcp__uteki__get_run(run_id=...)  → status: ok, summary: "..."
[answer] 总结 qna 给的回答
```

`qna` 是最便宜的 skill（无 sub-agent、mock 直出），适合做"工具链路全通"判断。

## 五、未解决的事

- **claude 内的 claude smoke** —— 见上文，暂时绕开。Long term 可能要给 CC 提供
  "spawn child CC with clean env" 的能力，但不在 uteki 范畴
- **service-account auth** —— 现在 MCP server 依赖 `UTEKI_AUTH_REQUIRED=false`。
  Prod 需要一个非 demo 的 service user + token，或者从 env 注入 token
- **stream events through MCP** —— 当前是 client polling get_run。streaming
  可行但 MCP SDK 的 server-initiated notification 还没探
- **MCP resources/prompts** —— 我们只暴露了 tools。把常用查询封装成 resources
  （比如 `uteki://recent-runs?since=24h`）可能让 CC 体验更顺
