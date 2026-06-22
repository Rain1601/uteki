# UI Mocks · 信息架构 + 屏间关系

## 路由地图

```
/eval-bench                              (Screen 1 · landing)
    ├── /eval-bench/suites/[id]          (Screen 2 · suite detail)
    │       └── /eval-bench/runs/[id]    (Screen 3 · bench run detail = A/B compare)
    ├── /eval-bench/compare              (Screen 3 · A/B compare 入口,不带 bench_run_id)
    ├── /eval-bench/trends               (Screen 5 · longitudinal trends)
    └── /eval-bench/backtest             (Screen 6 · backtest aggregate)

/runs/[id]?view=metrics                  (Screen 4 · single-run breakdown,复用既有路由)

/skills/[name]                           (existing — 顶部加 widget,见 07)
```

## 6 屏 + widget 的角色矩阵

| Screen | 主要用途 | 触发频率 | 决策含金量 |
|---|---|---|---|
| **1 · Overview** | 入口屏 / 工作流总览 | 每次进 eval-bench | 中(导航,不决策) |
| **2 · Suite detail** | 管理 query 集 | 偶尔(增减 query 时) | 低(配置) |
| **3 · A/B Compare** ★ | 决定 prompt 改动 ship 不 ship | 每次 prompt 改动后 | **高(核心决策点)** |
| **4 · Run detail (with backtest)** | 看单 run 的预测 vs 实际市场表现 | 每次打开 run | **高(实际反馈)** |
| **5 · Trends** | 长期监控 / 发现漂移 | 每周浏览 1 次 | 中(预警) |
| **6 · Backtest** | 看真实市场反馈 | 每月 1 次 | **高(ground truth)** |
| **Widget** | prompt 改动后的提示入口 | 触发 Screen 3 的 hook | 高(导引) |

## 信息流(用户故事)

### 故事 1 · "我刚改了 fisher_qa 的 prompt"

```
本地改 prompt → push prod →
    /skills/company_research_pipeline 顶部 widget 显示 ⚠ unverified
        ↓ 点 [Run smoke] (Mode B)
    /eval-bench/runs/<smoke_id> 显示 10 条 run 全部 parser 通过
        ↓ 点 [Run quality bench] (Mode A)
    /eval-bench/runs/<bench_id> 显示 60 条 run 跑了 50 min
        ↓ 看 5 维矩阵
    v4 vs v3:hedge ↓88%,WATCH% ↓25%,citation density ↑88%
    judge actionability +1.1
        ↓ 点击 NVDA 那一行钻取
    看 v3 vs v4 的 fisher_qa.md side-by-side
        ↓ 觉得 v4 真的更好
    点 [Approve & ship]
    BenchmarkRun.metrics_summary["approved_by"] = user_id
```

### 故事 2 · "我想知道我们的 BUY 信号准不准"

```
/eval-bench/backtest
    看 v3 的 BUY 命中率(vs SPY):62% (n=12 over 90d)
    看 v3 的 AVOID 命中率:71% (n=7)
        ↓ 想知道 v4 表现
    v4 数据 pending(预测都还没到 30d)
        ↓ 看 v3 失败的 5 个 BUY
    共同特征:都是 NEUTRAL→BUY 的临界点 + PE > 30x
        ↓ 这是 prompt 改进方向,但
    [Open as draft prompt-tuning task] 按钮(只记录,不动 prompt)
```

### 故事 3 · "我想看过去一个月 hedge 率有没有涨"

```
/eval-bench/trends
    选 metric: hedge_phrase_count
    时间范围:30d
    skill: company_research_pipeline
    版本切片:v3 / v4
    
    图上看到:
    - v3 时段 (6/01-6/20) 平均 2.4
    - v4 时段 (6/21-6/26) 平均 0.3
    - 差距明显,v4 的 6 个 Anthropic 模式确实起作用了
```

## 屏间共享的组件

| 组件 | 用在 | 实现 |
|---|---|---|
| `MetricBadge` | Screen 3,4,5,6 | 数字 + 单位 + Δ 箭头 |
| `RunDiffViewer` | Screen 3 钻取 + Screen 4 上下文 | 复用 /runs 详情的 artifact 渲染器 |
| `BenchSelector` | Screen 3, header | suite + version_a + version_b 三件套 |
| `PromptChangeWidget` | Screen 1, /skills/[name] | 状态条 + 一键跑按钮 |
| `MatrixTable` | Screen 3 主体 + Screen 6 aggregate | 多维度矩阵渲染(可排序/可钻取) |

## 设计原则

1. **不藏数字** — Screen 3 的矩阵第一屏就完整显示,不展开/不分页
2. **每个决策按钮带数字注脚** — "Approve & ship" 旁边写 "based on +X structural / +Y judge" 一句话
3. **跨屏 URL deeplinkable** — 比如 `/eval-bench/compare?suite=mega-cap&va=v3&vb=v4` 直接可分享给 reviewer
4. **空状态认真做** — 没 bench 跑过、没 backtest 数据、没 prompt 变更队列的状态,**显式说出来 + 给"该做啥"按钮**

## 颜色编码

复用 `Badge` 现有 tone 系统(`/components/ui/Badge.tsx`):

- `gain` 绿色 = 改进(hedge 下降 / WATCH% 下降 / citation 上升 → 绿)
- `loss` 红色 = 退化(structural pass rate 下降 / hit rate 下降 → 红)
- `warn` 黄色 = 未验证 / pending / unstable(N=3 跑出 3 个不同 verdict)
- `neutral` 灰色 = 无变化 / 不适用
- `accent` 紫色 = 重要指引(比如"Approve & ship" 按钮 / "Run bench" 按钮)
