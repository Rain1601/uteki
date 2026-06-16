# 013 · Design

## 数据模型 deltas

### Run 表新增 2 字段(`runs/sql_models.py`, `runs/models.py`)

```python
class Run:
    ...existing...
    auto_score: float | None = None            # 0.0-5.0, 加权聚合
    score_breakdown: dict | None = None         # JSON: {outcome: 4.2, cost: 5.0, ...}
```

NULL = "judge 还没跑 / 不适用此 skill"。**不影响**任何现有查询。

### RunFeedback 表(新)— 平行 `news_feedback` 的形态

```python
class RunFeedback(SQLModel, table=True):
    __tablename__ = "run_feedback"
    user_id: str = Field(primary_key=True, foreign_key="user.id")
    run_id: str = Field(primary_key=True, foreign_key="run.id")
    rating: str = Field(...)                   # "up" | "down"
    notes: str = Field(default="")             # 自由文本
    flagged: bool = Field(default=False)       # 🚩 "需要重审"
    created_at: datetime
    updated_at: datetime
```

复合主键 `(user_id, run_id)` → 每个 user 对每个 run **只能有一行**,upsert 而非 append。改主意了就 update。

### 权限

`auth/roles.py` 加常量:

```python
PERM_ANNOTATE_RUNS = "runs:annotate"
```

`permissions_for_role("admin")` 加这条。`permissions_for_role("reader")` 不加。

> Phase 2:加个 `User.extra_permissions: list[str]` JSON 字段,admin 可以经 `PATCH /api/admin/users/{id}` 给非-admin 用户**单独**授 `runs:annotate`,不需要升 admin。

## 后端流

### 异步 judge dispatch

`runs/store.py:finish()`(harness 调用,run 已落库):

```python
def finish(self, run_id, ...):
    ...existing save events / status...
    # Fire-and-forget. Never block the caller; never let a judge error
    # bubble into the user-facing run status.
    if settings.run_eval_enabled and run.skill in JUDGE_TARGETS:
        asyncio.create_task(default_judge_dispatcher.score(run_id))
```

`JUDGE_TARGETS` 起步只含 `["research", "company_research_pipeline"]` —— 投研类 skill 评起来意义大;mock-mode 和 e2e 自动跳过(因为这两个 skill 在 e2e 走 mock,LLM 调用是 placebo)。

### Judge dispatcher (`eval/judges/dispatcher.py`,新)

```python
class JudgeDispatcher:
    async def score(self, run_id: str) -> None:
        run = await self._load_run(run_id)
        outcomes = await asyncio.gather(
            self._outcome_judge(run),       # LLM
            self._cost_discipline(run),     # rule-based
            return_exceptions=True,
        )
        breakdown = self._fold(outcomes)    # 1-5 normalized per axis
        aggregate = self._weighted(breakdown)
        await self._persist(run_id, aggregate, breakdown)
```

Exception 隔离:某个 judge 挂了不拖累其他维度。最终入库 `score_breakdown = {"outcome": null, "cost": 4.5}` 之类的可观察形态。

### Outcome judge

`eval/judges/outcome.md` rubric file(对齐 007 已有 frontmatter 格式):

```markdown
---
name: outcome
applies_to: ["research", "company_research_pipeline"]
pass_threshold: 3
judge_model_preference:
  - anthropic/claude-opus-4-7
  - openrouter/openai/gpt-5
  - deepseek/deepseek-chat        # fallback only
avoid_models: []                  # judge 用更强模型;agent 用 deepseek 时也能走 anthropic judge
escape_hatch: "Unknown"           # judge 拿不准时允许 5=Unknown,不算通过也不算失败
---

# Outcome rubric

给定 run 的 user_input + final summary + primary artifact,1-5 评分:

5 — ...
4 — ...
3 — ...
2 — ...
1 — ...
Unknown — 信息不足判分,标 5
```

> escape hatch 是 Anthropic 明确建议的 *"give the LLM a way out"*,避免 judge 幻觉打分。

### Cost discipline (规则,无 LLM)

```python
def cost_discipline(run, baseline_p50_cost_for_skill) -> float:
    ratio = run.usage_summary.cost_usd / baseline_p50_cost_for_skill
    if ratio <= 1.0:  return 5.0    # 比中位数便宜
    if ratio <= 1.5:  return 4.0
    if ratio <= 2.0:  return 3.0
    if ratio <= 3.0:  return 2.0
    return 1.0                       # 超 3x = 烧钱
```

baseline 在 dispatcher 内一次性算近 30 天同 skill 的 p50,缓存 1h。

### API endpoint(`api/runs.py`)

```python
@router.post("/{run_id}/feedback")
async def upsert_feedback(
    run_id: str,
    body: FeedbackBody,
    user: User = Depends(require_perm("runs:annotate")),
    db: Session = Depends(get_db),
) -> FeedbackOut:
    ...upsert RunFeedback(user_id, run_id)...
    return FeedbackOut(
        rating=...,
        notes=...,
        flagged=...,
        # 标完才返回 auto 分 —— 这是反污染钉子
        auto_score=run.auto_score,
        score_breakdown=run.score_breakdown,
    )


@router.get("/{run_id}/feedback")
async def get_feedback(
    run_id: str,
    user: User = Depends(require_perm("runs:annotate")),
    ...
):
    """Return my feedback row + auto-score ONLY IF I've already submitted one.
    Else return {rating: null, score_breakdown: null} — annotator sees raw run."""
```

`require_perm("runs:annotate")` = 新的小依赖,403 给没权限的人。

## 前端

### `/runs/[id]/view.tsx` 加 rating 面板

位置:status badge 那一行下面,trace 上面。

```
┌─── Quality (admin only, gated by runs:annotate) ──────┐
│                                                       │
│  YOUR  [👍 Good] [👎 Bad]  notes: ____________       │
│        [🚩 Mark for re-review]               [保存]   │
│                                                       │
│  ──── 标完后才显示 ────                                │
│  AUTO  outcome 4.2/5 · cost discipline 5/5            │
│        aggregate 4.6/5                                │
└───────────────────────────────────────────────────────┘
```

`canOperate(user, "runs:annotate")` 控制面板可见;**默认 collapsed,点开才显示**。

### `/runs` 列表加 score badge

每行尾部追加(只 annotator 看得到):

```
... ✓ ok · 1.2s · ⭐ 4.6      🚩
```

`⭐ x.x` = aggregate auto_score(标过的 run 才显示;没标过 = 没有 badge)。
🚩 = 我自己 flagged 的 run。

筛选:`/runs?flagged=1` 拉出我 🚩 的所有 run,Phase 2 改为 `/admin/review` 独立页。

## Calibration baseline 怎么挑(20 条)

按 Q4 的回答,**混合策略**:

- **10 个"明显失败"候选**:由我 grep
  - `harness_status="error"`
  - `harness_status="timeout"`
  - `max_steps_exceeded` 在 events 里
  - `cost_usd > p99` 的过度烧钱 run
- **10 个"看起来正常"**:你从 `/runs?harness_status=ok` 随机点开,挑印象深刻或最近的
- 你**亲手标完 20 条**(👍/👎 + 1 句 notes)→ 这就是 baseline
- baseline 不写代码持久化在 DB,只是普通的 RunFeedback 行 —— Phase 2 calibration cron 读它们

时机:**`/runs/[id]` UI 上线之后第一周**集中标完。

## Open questions(已 resolved)

| Q | Answer |
|---|---|
| Sync vs async judge | async,不阻塞 |
| 谁能看 auto 分 | annotator 标完才看;reader 永远看不到 |
| 数据模型 | per-user RunFeedback 表 + `runs:annotate` 权限 |
| Calibration 基准 20 条怎么挑 | 我帮挑 10 失败,你挑 10 成功 |
| Judge 模型 | 跨家 / +1 版本,**强于 agent 模型** |
| Trajectory eval | MVP 不做,只 outcome + cost |
