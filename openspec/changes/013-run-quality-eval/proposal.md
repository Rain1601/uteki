# 013 · Run quality scoring + human feedback loop

## Problem

uteki 已经把"评测"这件事**两次卷起袖子**:

- 007 落 LLM-as-judge + rubric 文件 → 评的是 **`/evals/cases/*.json` 合成测试集**
- M1.11 接 drift_monitor → 跑的也是合成 case 的 pass_rate 趋势

**production 上的真实 run(`/runs` 看到的那些)是评测黑洞**:跑完啥都不发生,既没 LLM judge 给分,用户也没地方按 👍 / 👎。这导致:

- **prompt 变更回归**只能靠合成集兜底,合成集没覆盖的真实模式无人看护
- 用户**看了 100 个 run 觉得"质量在跌"** 也只是 vibes,没有可比的数字
- 即便有了 judge,**没人验过它准不准** —— Anthropic 的核心警告 *"LLM-as-judge graders should be closely calibrated with human experts"* 完全没落地

Anthropic 那篇 *Demystifying Evals for AI Agents* 列了 5 个公认坑:① 评路径不评结果 ② 一个 judge 评全维度 ③ 不读 transcripts ④ trial 间共享状态 ⑤ rubric 模糊 → uteki 现在**4/5 都没踩**(借了 007 的功),只是**没把它接到 prod runs 上**。

## Solution

把每个 prod run 的**完成**当成"一个待评测样本",建一个轻量评测 + 反馈环:

```
finish_run() ──→ asyncio.create_task(score_run)
                          │
                          ├─ outcome judge (LLM, 强模型,跨家)
                          ├─ cost_discipline (规则,无 LLM 调用)
                          ▼
                  RunScore 写回 run 表
                          │
                          ▼
/runs/[id] UI:
  ┌─ AUTO  outcome 4 · cost ↓ ── 仅 annotator 角色可见
  └─ YOUR  [👍] [👎] notes:____ 🚩 mark
                          │
                          ▼
                 RunFeedback 表(per-user 行)
                          │
                          ▼
   Phase 2 calibration cron: Cohen's κ(auto, human)
```

### 4 个关键设计决定(从 4 个来源的对比表反推)

| 决定 | 选择 | 理由 |
|---|---|---|
| **判分时机** | finish_run 后**异步**,不阻塞用户响应 | Anthropic + ops 体感:judge 多耗 5-10s,sync 体验差 |
| **多维度** | 每维度独立 judge,**不一个 prompt 评所有轴** | Anthropic 反模式 #2 直接命中 |
| **outcome > trajectory** | MVP **不做 trajectory judge**,只评 outcome + cost | Anthropic *"don't grade specific tool sequences"*;trajectory eval 容易扼杀 agent 的合法捷径 |
| **judge 模型 ≠ agent 模型** | 跨家 或 同家 +1 版本 | Anthropic *"avoid same model self-scoring"* + 007 的 `avoid_model` 思路 |

### "标完才看 auto 分" 是关键反污染设计

如果 annotator 标之前看到 auto 分,他大概率受暗示往那个方向标 → **calibration set 直接废**(变成"我和 judge 同意吗",不是"这 run 实际好不好")。

- annotation 面板默认**隐藏 auto 分**
- annotator 按完 👍/👎 → auto 分才浮现
- 数据库一律记录,UI 只是隐藏

### 权限模型

新增 permission `runs:annotate`:
- MVP:`admin` role 默认带,所以你拿到了;其他人没有
- Phase 2:可以经 admin UI 单独授给特定 reader(不升 admin),实现 "团队里挑几个高质量标注人"

## Out of scope(留给后续 change)

- **trajectory judge**(顺序 / 工具重复)— 等 outcome judge 跑稳 + 真有 trajectory 问题再上,**默认不做**
- **judge calibration cron** — Phase 2(等 baseline 标完 ≥ 20 条再启)
- **`/admin/review` 独立队列页** — 🚩 flagged 的 run 先在 `/runs?flagged=1` 查询参数下凑合用
- **A/B 跨版本 UI** — 已存在 `evolution/ab_eval.py`,不在本 change 上 UI
- **judge panel(多 judge 投票)** — MVP 单 judge 起步,有需要再加
