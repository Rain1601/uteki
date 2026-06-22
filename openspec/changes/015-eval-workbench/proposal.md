# 015 · Eval Workbench

## Problem

013 给我们装上了**单 run 评测的零件**(`Run.auto_score` + `RunFeedback` + `JudgeDispatcher`),但这些零件**没装成机器**:

- 改一次 prompt 后**不知道**整体效果是变好还是变差 —— 只能手动跑一条 GOOGL 看看
- 改完一次 prompt **不知道**会不会撞回归 —— 我们今天就出过一次 fisher_qa 格式漂移让 P0 lock 脱挂
- prod run 在跑,但**没人能回答**"过去 30 天 hedge 短语率有没有涨" 这种基础问题
- 我们给出的 BUY / WATCH / AVOID 建议**没有 ground truth 回路** —— 不知道实际有没有挣到钱

013 把零件做好了,015 是把零件**装成可工作的眼睛 + 闭环**。

Anthropic *Demystifying Evals for AI Agents* 那篇文章里特别强调:**"observability is half the work; the other half is acting on it without overfitting"**。我们现在有一半都没有。

## Solution

建一个 **Eval Workbench**,把"测什么 / 怎么测 / 测了谁负责改"这条链路接上。三个共生模块:

```
┌────────────────────────────────────────────────────────────────┐
│                     EVAL WORKBENCH                             │
│                                                                │
│  ① Benchmark Suite     ② A/B Compare        ③ Backtest        │
│     固定 query 集 +      Mode A (quality)     预测 vs SPY        │
│     版本回放             Mode B (smoke)       30/90/180d        │
│         │                    │                    │            │
│         └────────────────────┴────────────────────┘            │
│                              │                                 │
│                              ▼                                 │
│         共享地基:复用 013 的 Run.auto_score                    │
│                   复用 013 的 RunFeedback                      │
│                   复用 013 的 JudgeDispatcher                  │
│                   不新建 store,只新建 view                     │
└────────────────────────────────────────────────────────────────┘
```

### 模式 A · Quality bench(质量验证)

回答 *"v4 比 v3 真的更好吗?"*

- T = prod 默认值,N = 3,聚合 median / mode / majority
- 跑 10 个固定 ticker × 2 个版本 × 3 次 = 60 run · ~50 min · $15
- 输出:**A/B 矩阵**(结构 / 行为 / 引用 / judge / cost 五维)+ per-query 钻取
- 决策权重:**唯一**有资格回答"该不该 ship"的信号
- 触发:**人工**点 "Run quality bench" 按钮

### 模式 B · Format smoke(结构冒烟)

回答 *"我刚改的 prompt 还能不能跑通?"*

- T = 0,N = 1
- 跑同样 10 ticker · 单次 · ~5 min · $2.5
- 输出:**pass/fail 列表**(15 Q 全在不在 / heading 完整 / parser 跑通 / 必引来源类型出现)
- 决策权重:**挡住低级错误**(prompt 改完 broke 了 parser 这种)
- 触发:**人工**或 **EvolutionStore hash 变化 → 自动提示但不强跑**

### Backtest(回测)— 最慢但最真实的反馈

回答 *"我们的 BUY / AVOID 信号在市场上有没有用?"*

- 每条 company run 落 prediction:(run_id, ticker, action, conviction, t0, t0_price)
- Daily cron 扫到期预测(t0+30d / t0+90d / t0+180d),拉历史价
- **Hit 定义:vs SPY 相对收益**(BUY 需要超过 SPY,AVOID 需要落后 SPY,WATCH 不计入)
- 按 skill version 聚合 hit rate,出"v3 BUY 命中率 62% / v4 数据未到期"

### 反模式守则(由你拍板)

> "我们不能以一次指标的问题就修改 prompt,**我们的修改需要人工确认后才开始的**"

落地为两条硬规则:
1. Eval workbench **只暴露数据,不自动改 prompt** —— 没有 "auto-tune" 按钮
2. ship 一个新 prompt 版本到 prod 必须经过:**Mode B pass → Mode A 指标人工 review → "Approve & ship" 按钮**(每个按钮一次确认)

## 为什么现在做

- ✅ 013 零件齐了(auto_score / RunFeedback / JudgeDispatcher),建在上面零额外存储
- ✅ 我们刚把 6 个 Anthropic 模式装进 company gates,**正需要**回头量化"装上去到底拉了多少分"
- ✅ vertex_grounding 让 web_search 真有用,下一步 P1(给 fisher_qa 接 transcripts)的 ROI **不靠手感判断,靠 eval bench 数字**
- ✅ TSLA 并发 bug 教训:**没有 eval bench 我们靠用户 + 人肉发现 bug**;有了之后,Mode B 的 "parser 跑通率突然降到 80%" 会立刻告警
- ✅ prod 上线了真用户路径(虽然现在只有你),回测层每天都在累积数据 —— **越晚做越浪费已发生的预测样本**

## 谁受益

- **你(开发者 + 唯一 alpha 用户)**:每次 prompt 改动有个"该 ship 吗"的客观答案,不再靠手跑 GOOGL 押宝
- **未来 alpha 用户**:他们的 prod run 自动喂回测层 → 我们的 prompt 演化基于真实信号
- **审计 / 解释**:用户问"为什么 v4 比 v3 推 BUY 多?" → 直接打开 A/B compare 页给他看矩阵
- **drift 监控**:不用等用户报 bug,**结构合规跌破阈值**当晚就告警

## 不做的事(明确范围)

- ❌ Auto-tune prompt:eval bench 只读,不写 prompt 文件
- ❌ 推到 production 用户:第一版只对 admin 开放(`/eval-bench` 路由走 `require_admin`)
- ❌ 大盘 / 板块基准外延:Mode A 暂只支持 company_research_pipeline,不一次性铺 6 个 skill
- ❌ 拉真实 PM 当 labeler:第一版 inter-rater(κ)还是 0,等 alpha 用户上来再做 Phase 2

## 成本估算

- **Mode A 单次成本**:$15(60 run × $0.25)· 推荐**每次 prompt 改动跑 1 次**
- **Mode B 单次成本**:$2.5(10 run × $0.25)· 推荐**改完立即跑**
- **Backtest 成本**:近 0(yfinance 免费,cron 跑批,每天扫表)
- **存储成本**:median run artifact 保留 ~5MB × 30/月 ≈ 150MB,其它 N-1 次只存 metric 几 KB
