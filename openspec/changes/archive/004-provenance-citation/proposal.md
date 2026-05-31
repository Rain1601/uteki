# 004 · Provenance and citation reliability

## Problem

uteki 的 harness 已经能运行 skill、调度 tool、写 run、产出 artifact，但投研可信度还缺一层明确的来源协议：

- `tool_result` 里有数据，但没有统一的 source id，final answer 不能稳定追溯到具体来源。
- 当前 guardrails 要求 "cite or flag"，但运行时没有统一的 `SourceCatalog` 去验证 `[src:N]` 是否存在。
- `eval` 可以读 trace 和 artifacts，但没有标准化的 `source-catalog.json` 作为事实来源。
- `uteki.open` 已经有一套可迁移的 provenance 资产：`DataPoint`、`SourceCatalog`、`CitationParser`、fetcher registry、orphan citation check。它们应该被适配进 uteki harness，而不是按旧业务 API 原样搬运。

这会直接影响后续 `company_research_pipeline`：公司投研报告里的数字、新闻、同行对比、估值判断必须能解释"从哪里来"。

## Solution

新增 `provenance` capability，作为 run-scoped 来源目录和 citation 校验层。

核心设计：

1. 引入 `DataPoint`
   - 表示一个可引用的数据事实。
   - 记录 `source_type`、`source_url`、`publisher`、`published_at`、`fetched_at`、`confidence`、`excerpt`。

2. 引入 `SourceCatalog`
   - 每个 run 一个 catalog。
   - tool 或 skill 注册 DataPoint，catalog 分配稳定的 `[src:N]` id。
   - catalog 序列化为 `source-catalog.json` artifact。

3. 引入 `CitationParser`
   - 解析 `[src:1]`、`[src:1,3]`、`[src:none]`。
   - 检测 orphan citations，也就是模型引用了不存在的 source id。

4. 适配 harness / artifacts
   - harness 注入 run-scoped provenance facade，类似 `RunArtifacts`。
   - skill 可以通过 facade 注册来源，也可以由 tool result 自动注册。
   - run 结束前确保 `source-catalog.json` 已写入 artifact。

5. 适配 evaluator
   - evaluator 读取 `source-catalog.json` + `final-report` / `final-research.md`。
   - citation 合法性成为可机械验证的 criterion。

## Reuse from uteki.open

允许迁移并改写以下文件中的设计与实现：

- `/Users/rain/PycharmProjects/uteki.open/backend/uteki/domains/agent/provenance/datapoint.py`
- `/Users/rain/PycharmProjects/uteki.open/backend/uteki/domains/agent/provenance/catalog.py`
- `/Users/rain/PycharmProjects/uteki.open/backend/uteki/domains/agent/provenance/citation_parser.py`
- `/Users/rain/PycharmProjects/uteki.open/backend/uteki/domains/agent/provenance/registry.py`

迁移原则：

- 迁移数据模型和校验逻辑。
- 不迁移旧版业务 API。
- 不保留旧版 `CompanyToolExecutor` 的 if/else dispatch 结构。
- 适配新版 `uteki_api.tools.Tool` / `ToolRegistry` / `AgentHarness`。

## Key files touched

- `services/api/src/uteki_api/provenance/` — 新 capability。
- `services/api/src/uteki_api/agents/harness.py` — 注入 provenance facade，run finish 前写 catalog artifact。
- `services/api/src/uteki_api/tools/base.py` — 允许 tool result 携带 source metadata。
- `services/api/src/uteki_api/skills/evaluator/verifiers.py` — 新增 citation verifier。
- `services/api/src/uteki_api/eval/judges/cite_compliance.md` — 使用 catalog-aware rubric。
- `apps/web/components/agent/Artifacts.tsx` — 后续可高亮 `source-catalog.json`。
- `openspec/specs/provenance/spec.md` — 新真相来源。
- `openspec/specs/harness/spec.md` / `openspec/specs/artifacts/spec.md` — 补充 provenance 交互。

## Non-goals

- 不做 company 7-gate pipeline 迁移；那是后续 `006-company-research-pipeline`。
- 不做真实数据源接入；本 change 只定义 source/citation 协议和 mock/现有 tools 的适配。
- 不做前端 citation chip 渲染；本 change 只保证 catalog artifact 和 validation。
- 不做 tool permission policy；那是后续 `008-tool-governance`。
- 不做 artifact-first run detail 大改；那是后续 `005-artifact-first-runs`。

## Risks

- **过度侵入 harness**：provenance 必须像 artifacts 一样是注入对象，不能让 harness 变成业务逻辑层。
- **source id 稳定性**：source id 只保证 run 内稳定，不保证跨 run 稳定。
- **tool result 兼容性**：旧 tools 只返回 `ToolResult(data=...)`，不能一次性要求所有 tool 都注册 DataPoint。需要渐进式适配。
- **LLM 引用不稳定**：模型可能仍然编造 `[src:N]`，所以 citation parser 必须能 neutralize / report，而不是让 run 崩溃。

