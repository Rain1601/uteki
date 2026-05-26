# 02 · Self-Evolution Loop — 用 Claude Code 当外部 reviewer

> Status: **proposal** · 提议详尽到可以拆 change 落地，但还没拆。
> 关联：[`01-claude-code-interop.md`](./01-claude-code-interop.md) 方向 C 的展开

## 一、为什么这个 loop 值得做

把 Claude Code 拼成 uteki 的**外部 evaluator + prompt 改写器**，得到的是真正的 self-improving 闭环：

- **uteki 内部的 `EvaluatorSkill` 是 in-process** —— 读同一份 run-trace、用同一个 LLM provider 池、`guardrails.md` 也是它训练上下文的一部分。它的盲点是结构性的。
- **Claude Code 是真正的"外人"** —— 没看过 SKILL.md、对 prompt 风格没偏好，会指出 uteki 内部 evaluator 看不出来的问题。
- **让 uteki 内部 agent 改自己的 prompt 然后自己用** —— meta 风险大。
- **让 CC 改 prompt，人审，机器执行** —— 跟 PR review 同构。

## 二、关键洞见：复用现有 openspec 心智模型

整个流程不引入新概念，而是把 uteki 既有的零件拼起来：

| 这个 loop 的部分 | 复用 uteki 既有的 |
|---|---|
| Proposal 的目录结构 | `openspec/changes/<NNN>/` 的同构 |
| status 状态机 | `Run.status` 概念扩展 |
| skill 版本管理 | `EvolutionStore.record(SkillVersion)` |
| prompt hash 自动 bump | `compute_signature()` + `load_skill_prompt.cache_clear()` |
| A/B 评测 | `EvalRunner.run_all()` 跑两次（pre/post），对比 `EvalReport.pass_rate` |
| 历史趋势 | `default_eval_history` 加一个 `"system:evolution"` 分区 |
| 通知 | 接通 drift_monitor 已留的 webhook 接口 |
| 多租户隔离 | `Depends(current_user)` + 未来 RBAC |

## 三、状态机：一个 Proposal 的完整生命周期

```
                    ┌─────────────────────────────────────────┐
                    │                                         │
                    ▼                                         │
   [triggered]──→[snapshotting]──→[briefing]──→[spawning]──→[generating]
                                                                  │
                                                                  ▼
                    ┌───────────────────────────────┐    [validating]
                    │                               │           │
                    ▼                               │     ┌─────┴─────┐
              [invalidated]◀──────[CC output bad]───┘     │           │
                    │                                    OK         BAD
                    │                                     │           │
              [discarded]                                 ▼           │
                                                  [pending_review]    │
                                                         │            │
                            ┌────────────┬───────────────┼────────┐   │
                            ▼            ▼               ▼        ▼   │
                       [rejected]   [edit_then_apply] [accepted]  [deferred]
                                                          │
                                                          ▼
                                                    [applying]
                                                          │
                                                  ┌───────┴───────┐
                                                 OK             FAIL
                                                  │               │
                                                  ▼               ▼
                                              [a_b_eval]     [apply_failed]
                                                  │
                                       ┌──────────┼──────────┐
                                       ▼          ▼          ▼
                                   [adopted]  [rolled_back] [inconclusive]
```

四个**人类决策门**：
- **G1 = pending_review → accepted/rejected/edit/deferred**（操作员评审）
- **G2 = a_b_eval → adopted/rolled_back**（操作员看 A/B 数据决定）
- **G3 = apply_failed / inconclusive → manual investigation**（异常分支）
- **G4 = trigger 是手动还是自动**（系统配置层面，但每次触发都记审计）

## 四、详细时序

```
┌──────┐       ┌──────────┐    ┌────────────┐    ┌──────────┐      ┌──────┐
│ User │       │  uteki   │    │ Proposals  │    │ Claude   │      │Oper- │
│      │       │ Backend  │    │   Store    │    │ Code     │      │ ator │
└──┬───┘       └────┬─────┘    └─────┬──────┘    └────┬─────┘      └──┬───┘
   │                │                │                │                │
   │ chat(...)      │                │                │                │
   ├───────────────▶│                │                │                │
   │  run_id=R1     │                │                │                │
   │◀───────────────┤  ┌─ pipeline runs ─┐            │                │
   │                ├──┤plan→research→eval├─▶         │                │
   │                │  └─ artifacts.* ────┘            │                │
   │                │  pass_rate=0.6                  │                │
   │                │                │                │                │
   │           ┌────┴────┐ ① trigger │                │                │
   │           │ trigger │ (auto: pass_rate<0.7,      │                │
   │           │ rules   │  /api/admin/review/R1)     │                │
   │           └────┬────┘                            │                │
   │                │                │                │                │
   │                ├── ② create     │                │                │
   │                │  proposal_id   │                │                │
   │                │  =P-2026-001   │                │                │
   │                ├───────────────▶│                │                │
   │                │                │  status:      │                │
   │                │                │  triggered    │                │
   │                │                │                │                │
   │                │ ③ snapshot     │                │                │
   │                │  artifacts/    │                │                │
   │                │  SKILL.md      │                │                │
   │                │  specs/        │                │                │
   │                │  rubrics/      │                │                │
   │                ├───────────────▶│ status:        │                │
   │                │                │ snapshotting   │                │
   │                │                │ → briefing     │                │
   │                │                │                │                │
   │                │ ④ build brief.md + workdir/     │                │
   │                │   spawn CC subprocess           │                │
   │                ├────────────────────────────────▶│                │
   │                │                │                │ status:        │
   │                │                │                │ generating     │
   │                │                │                │                │
   │                │                │                │ uses Read,     │
   │                │                │                │ Grep, Edit on  │
   │                │                │                │ a *snapshot    │
   │                │                │                │ worktree*      │
   │                │                │                │                │
   │                │                │                │ produces:      │
   │                │                │                │ - critique.md  │
   │                │                │                │ - patch.diff   │
   │                │                │                │ - rubric.diff  │
   │                │ ⑤ collect output                │ - meta.json    │
   │                │◀───────────────────────────────┤                │
   │                │                │                │                │
   │                │ ⑥ validate     │                │                │
   │                │  - diffs apply │                │                │
   │                │  - rubric YAML │                │                │
   │                │  - markdown ok │                │                │
   │                │                │                │                │
   │                │ ⑦ commit       │                │                │
   │                ├───────────────▶│ status:        │                │
   │                │                │ pending_review │                │
   │                │                │                │                │
   │                │ ⑧ notify       │                │                │
   │                ├────────────────────────────────────────────────▶│
   │                │                │                │                │
   │                │                │                │   ⑨ G1: review │
   │                │                │                │   browse diff  │
   │                │                │                │   read critique│
   │                │                │                │                │
   │                │ ⑩ accept       │                │                │
   │                │◀────────────────────────────────────────────────┤
   │                │                │                │                │
   │                │ ⑪ apply patch  │                │                │
   │                │  + cache_clear │                │                │
   │                │  + version bump│                │                │
   │                ├───────────────▶│ status: applying → a_b_eval     │
   │                │                │                                 │
   │                │ ⑫ rerun eval cases with R1's input,              │
   │                │   compare to baseline                            │
   │                │                                 │                │
   │                │ ⑬ surface A/B  │                │                │
   │                ├────────────────────────────────────────────────▶│
   │                │                                 │ G2: adopt or  │
   │                │                                 │ roll back     │
   │                │ ⑭ decision     │                │                │
   │                │◀────────────────────────────────────────────────┤
   │                │                │                │                │
   │                │ ⑮ if rollback: │                │                │
   │                │  reverse patch │                │                │
   │                │  + version bump│                │                │
   │                ├───────────────▶│ status:        │                │
   │                │                │ adopted /      │                │
   │                │                │ rolled_back    │                │
```

## 五、人类决策门（4 道）

每一道门都需要**显式动作 + 留痕**，不能默认行为。

### G1: 触发策略（系统配置层）

谁能触发 external review？三种模式并存：

| 模式 | 谁触发 | 谁记录 | 谁审 G2 |
|---|---|---|---|
| **manual** | 操作员点 UI 按钮 | user_id | 同一操作员 |
| **scheduled** | cron（每 N 小时扫描最近 runs） | "system:cron" | 值班操作员 |
| **drift-triggered** | drift_monitor 检测 pass_rate 跌 ≥ 10pp 自动触发 | "system:drift_monitor" | 值班操作员 |

**drift-triggered 是最有意思的**——把 uteki 自己的质量监控接到了 CC 的改进提案。但这条线需要 **rate limit**，否则一次质量抖动会产生 N 个并行 proposal 互相覆盖。建议：每个 skill 同时最多一个 in-flight proposal，新触发的进 queue 等。

### G2: Proposal 评审（最关键的一道门）

操作员看到的不是一份 markdown，而是一个结构化对比视图：

```
┌─ Proposal P-2026-001  (skill: research v2 → v3-proposed) ─────────────┐
│                                                                       │
│  Triggered: 2026-05-26 14:32  by system:drift_monitor                 │
│  Source run: R1 (case=research-sector-primer, pass_rate=0.6)          │
│  Snapshot:  skill_hash=ab12cd34  spec_hash=ef56...  rubric_hash=...   │
│                                                                       │
│  ──── critique.md (CC's analysis) ────────────────────────────────    │
│  ## Cite-compliance failures (3 of 8 sections)                        │
│  - "Sector overview" introduces "$120B market" without source         │
│  - "Competitive landscape" PE ratios floated without [^source]        │
│  - ...                                                                │
│                                                                       │
│  ──── patch.diff (SKILL.md) ──────────────  diff statline: +12 -3    │
│  --- SKILL.md (current)                                               │
│  +++ SKILL.md (proposed)                                              │
│  @@ -23,4 +23,8 @@                                                    │
│   ## Source discipline                                                │
│  +- For any quantitative claim (price, multiple, market size,         │
│  +  growth rate), you MUST include an inline footnote                 │
│  +  [^source: tool=X args=Y] OR the [UNSOURCED] flag literally.       │
│  +- No interpretive paraphrases of source numbers.                    │
│  ...                                                                  │
│                                                                       │
│  ──── rubric.diff (eval/judges/cite_compliance.md) ── statline: +5 -0│
│  ...                                                                  │
│                                                                       │
│  ──── CC's invocation metadata ──────────                             │
│  model: claude-opus-4-7  tokens: 18432 in / 2891 out                  │
│  duration: 47s  tool_uses: Read×8, Grep×3, Write×3                    │
│  cost: $0.31                                                          │
│                                                                       │
│  ──── Actions ──────────                                              │
│  [Accept] [Reject] [Edit then accept] [Defer] [Discard]               │
│  Reason (required if reject/discard): _______________                 │
└───────────────────────────────────────────────────────────────────────┘
```

操作员的决策原料：
- CC 的诊断质量（critique.md 读起来站得住吗？）
- diff 的克制度（CC 是不是动了太多？）
- 元数据（CC 用了多少 token、跑了多久——长时间+多 token 可能意味着 CC 在挣扎）

### G3: A/B 评判结果

```
┌─ A/B Result for P-2026-001 ──────────────────────────────────┐
│                                                              │
│   Cases evaluated: 4 (the full eval/cases/ set)              │
│                                                              │
│              baseline (v2)    proposed (v3-proposed)         │
│   pass_rate     0.50              0.75    ↑ +25 pp           │
│   judge: corr    7.2               7.8    ↑                  │
│   judge: cite    5.1               8.4    ↑↑ (the target)    │
│   judge: style   6.8               6.5    ↓ slight regr      │
│   cost/run      $0.04             $0.06    ↑ +50%            │
│   latency       45s                52s     ↑                 │
│                                                              │
│   Sample size: 4 cases × 1 run each (low confidence)         │
│   Suggested: rerun with 3× sample before adopting            │
│                                                              │
│   [Adopt] [Roll back] [Rerun with bigger sample]             │
└──────────────────────────────────────────────────────────────┘
```

注意几个设计选择：
- **cite_compliance 是改动的 target rubric**，它涨了——这是 signal
- **style 微降**——操作员判断是否能接受这个 trade-off
- **样本量小**——默认要求至少 12 cases (4 × 3 runs) 才默认 adopt，否则按钮变灰

### G4（隐性）：异常分支

如果 `validating` 失败（CC 给了不能 apply 的 diff），proposal 自动进 `invalidated` 状态，但不丢弃——它本身就是数据：**说明 CC 在这个任务上不可靠**，可能要换更强的模型，或者调 brief 模板。需要操作员看几次后判断是数据偶发还是系统性问题。

## 六、CC 的"沙盒边界"——能做什么、不能做什么

这个非常关键，**绝不能让 CC 直接动 live 仓库**。两条边界：

1. **物理隔离**：CC 在 `snapshot/skill/` 的副本上工作（用 git worktree 或纯文件拷贝），不是直接编辑 `services/api/src/uteki_api/skills/research/SKILL.md`。它的输出是 *diff*，不是 *change*。apply 阶段才把 diff 应用到 live。

2. **能力隔离**：spawn CC 时显式限制可用工具——`--allowedTools Read,Grep,Glob,Edit,Write`，**禁用** `Bash`（除非有强需要）+ `WebFetch` + `Agent`（防 recursive spawn）。同时设 `--max-turns` 避免 CC 自己卡循环。

brief.md 模板大致：

```markdown
# Task: review uteki run P-2026-001

You are reviewing a single research_pipeline run that pass_rate=0.6
(below the 0.7 quality threshold). The user-facing question was:
"中国半导体设备板块研究框架（简化版本）"

## What's in this workdir
- run_artifacts/   — the run's output (plan.md, final-research.md, eval-report.json, judge-*.json, run-trace.json)
- skill/SKILL.md   — the prompt that drove the research skill
- specs/           — platform contracts you must respect
- rubrics/         — the judges that scored this run

## Output you must produce (in this workdir, exactly these names)
- critique.md — at least 3 specific failures, each citing a line number in
  run_artifacts/final-research.md, scored against an existing rubric.
- patch.diff — unified diff against skill/SKILL.md. Minimize blast radius.
- rubric.diff — unified diff against rubrics/cite_compliance.md (or other),
  empty file is OK if rubric changes aren't needed.

## Constraints
- Do not invent acceptance criteria not in specs/.
- Do not propose >30 lines of total SKILL.md change.
- Cite a specific line in run_artifacts/* for every failure you claim.
- The skill's brand voice is editorial Chinese; preserve it.
```

## 七、审计记录的 Schema

每个 proposal 都是文件系统里的一个目录，不是 DB 行——**git diff 直接能看历史，rollback 就是 git revert**，灾难恢复变 trivial。

```
data/evolution/proposals/
└── P-2026-001/                          # auto-incrementing id
    ├── meta.json                        # 状态机的真相
    ├── trigger.json                     # 谁/为什么/什么时候触发
    ├── snapshot/                        # 触发那一刻的世界状态
    │   ├── run_artifacts/              #   被审查的 run 的所有 artifacts
    │   ├── skill/
    │   │   ├── SKILL.md                #   被审查时的 prompt
    │   │   └── signature               #   compute_signature 的输出
    │   ├── specs/                       #   harness.spec.md 等
    │   └── rubrics/                     #   eval/judges/*.md
    ├── brief.md                         # 喂给 CC 的 prompt
    ├── cc_run/                          # CC 自己的产物（完整）
    │   ├── invocation.json             #   命令行 + env + model
    │   ├── transcript.jsonl            #   CC 完整的 tool_use 序列
    │   ├── critique.md
    │   ├── patch.diff
    │   ├── rubric.diff
    │   └── stdout.log
    ├── validation.json                  # 自动校验结果
    ├── decisions/                       # 每次状态转移
    │   ├── 001-pending_review.json     # 自动转入 pending
    │   ├── 002-accepted.json           # G1 决策 + reviewer + reason
    │   ├── 003-applied.json            # apply 结果 + new skill version
    │   ├── 004-a_b_eval.json           # 完整对比数据
    │   └── 005-adopted.json            # G2 决策
    └── post_apply/                      # 应用后的快照（用于 rollback）
        ├── SKILL.md
        ├── signature
        └── rubrics/
```

`meta.json` 是状态机的真相——查询入口都走这个：

```json
{
  "proposal_id": "P-2026-001",
  "status": "adopted",
  "source_skill": "research",
  "source_run_id": "ab12cd34",
  "snapshot_skill_signature": "ab12cd34ef56",
  "applied_skill_signature": "9988aabbccdd",
  "transitions": [
    {"to": "triggered",      "ts": "2026-05-26T14:32:01Z", "by": "system:drift_monitor"},
    {"to": "snapshotting",   "ts": "...", "by": "system"},
    {"to": "briefing",       "ts": "...", "by": "system"},
    {"to": "spawning",       "ts": "...", "by": "system"},
    {"to": "generating",     "ts": "...", "by": "system", "cc_pid": 23341},
    {"to": "validating",     "ts": "...", "by": "system"},
    {"to": "pending_review", "ts": "...", "by": "system"},
    {"to": "accepted",       "ts": "2026-05-26T15:14:22Z", "by": "user:alice@..."},
    {"to": "applying",       "ts": "...", "by": "system"},
    {"to": "a_b_eval",       "ts": "...", "by": "system"},
    {"to": "adopted",        "ts": "2026-05-26T15:38:01Z", "by": "user:alice@..."}
  ],
  "ab_summary": { "pass_rate_baseline": 0.50, "pass_rate_proposed": 0.75 }
}
```

## 八、关键失败模式 + 对策

| 失败 | 现象 | 对策 |
|---|---|---|
| CC 给的 diff 不能 apply | 行号漂移、上下文不匹配 | validating 阶段拦截 → `invalidated`，留 transcript 给人看 |
| CC 写的 critique 是车轱辘话 | 没有具体行号、没有 specific failure | brief.md 里把"必须 cite 行号"作为硬约束；持续低质 → 换 model |
| 两个 proposal 改同一份 SKILL.md | merge conflict | 每个 skill 同时只允许 1 个 in_flight proposal（在 `triggered..pending_review` 中）|
| A/B 显示涨了但只是过拟合那 4 个 case | 样本量小 + cases 不代表实际流量 | 默认要求 ≥12 sample；同时跑 N 个未在原 eval set 里的 holdout case |
| Drift trigger + adopt + 又 drift | 系统震荡，prompt 反复改 | 每个 skill 7 天内最多 1 次 adopted change；之后强制人工 |
| CC 自己 OOM/超时 | proposal 卡在 `generating` | 子进程 timeout=10min + uteki 端 health-check；超时 → `invalidated` |
| 历史 proposals 污染 CC 的判断 | 后续 CC 看到之前的 critique，向同方向漂 | brief.md **不暴露** 历史 proposal；CC 永远是初次观察 |
| 一个 adopted 改动隐性破坏了别的 skill | research 改完，earnings 跌了 | A/B eval **跑全套 cases**，不只是触发的那条 case |

## 九、留给团队拍板的开放问题

1. **触发自动化的激进程度**：drift-triggered 是 nice 但有"系统震荡"风险。要不要 MVP 只先做 manual，跑顺了再开 auto？
2. **谁能审 G1/G2**：现在 uteki 没有 RBAC。三个选项：
   - (a) 加 `User.role` 字段
   - (b) 用 env 配置 `UTEKI_ADMIN_EMAILS` 白名单
   - (c) 先所有 user 都能审（dev 阶段 OK）
3. **A/B 的样本量底线**：4 个 case 显然不够，但跑 12 case × 3 runs 一次 real-LLM ≈ $3-5。要不要分两档：小样本 "preview"（< 1 min, $0.5）+ 大样本 "promote"（5 min, $3）？
4. **CC 用什么 model**：Opus（最强但贵）/ Sonnet（够用且便宜 5×）/ 让操作员每次选？建议默认 Sonnet，drift 严重的 case 走 Opus。
5. **历史 proposal 的"自然遗忘"机制**：永久保留 vs 90 天后归档冷存储？审计法规视角通常要 ≥2 年。
6. **跨 skill 影响检测**：A/B 跑全套 cases 但每个 case 可能只测一个 skill。要不要专门维护一组 "jointly important" 的 holdout case？

## 十、最小可跑切片（5 天 MVP）

| Day | 交付物 |
|---|---|
| **1** | proposal 目录结构 + `meta.json` 状态机 + `triggered → pending_review` 路径（手动触发 + 真跑 CC 子进程 + 落 critique/diff）|
| **2** | G1 评审 UI（终端 CLI 先行，web UI 后做）+ apply 流程（含 cache_clear + EvolutionStore record）|
| **3** | A/B eval + G2 决策 + rollback 路径 |
| **4** | drift_monitor 自动触发 + rate limit |
| **5** | 审计查询 + 趋势可视化 |

第 1 天结束就能看到第一份"CC 写的 critique + diff"，这是 morale boost；第 3 天结束有完整闭环；第 4-5 天是把它变成 always-on 的事。

## 十一、与方向 A/B 的次序关系

强建议：
- **先方向 B**（MCP server）—— 让 CC 能用 uteki 的 skill，1-2 天
- **再方向 C 的人工版**—— `.claude/commands/uteki-review.md` 让人手动触发 CC review，不进 proposal store，0.5 天
- **第三步才是 C 的完整版**—— 上面那个 5 天 MVP

人工版是真正的"先验证 CC 写出的 critique 质量到底够不够好"的廉价试金石。critique 质量过关，再投资 5 天搭基础设施才划算。
