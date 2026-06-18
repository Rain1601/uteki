"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { getRun, type RunDetail } from "@/lib/api";
import type { AgentEvent } from "@/lib/types";
import {
  AlertTriangle,
  CheckCircle2,
  Eye,
  EyeOff,
  Flag,
  Info,
  Loader2,
  MessageSquare,
  Sparkles,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";

// ─── DEMO — per-step eval on /runs/[id] with Notion-style comment layout

interface Step {
  key: string;
  kind: "phase" | "gate" | "synthesis" | "outcome";
  title: string;
  subtitle?: string;
  startTs?: number;
  endTs?: number;
  toolCalls: { name: string }[];
  artifacts: { name: string }[];
  /** Demo preview shown in the content column. Real impl would lazy-load
   *  the gate artifact text via fetchArtifactText. */
  previewMd: string;
  outcomeChecks: { label: string; pass: boolean | "warn"; detail?: string }[];
  rubric: { dimension: string; score: number | null; rationale: string };
}

const GATE_RUBRICS: Record<
  string,
  { dimension: string; rationale: string; preview: string }
> = {
  business_analysis: {
    dimension: "业务理解清晰度",
    rationale: "产品矩阵 + 收入构成都列了；分部毛利缺一档。",
    preview:
      "**核心业务** 分为 iPhone / 服务 / 可穿戴 / Mac / iPad 五大块。FY25 iPhone 占比 51%，服务上升至 25%（毛利 71%），硬件毛利 36%。地理上美洲 + 大中华 + 欧洲 ≈ 80%。\n\n**评估** Apple 是消费电子 + 数字订阅服务混合体；价值分布 IRR 高度依赖服务延续增长 + iPhone 复购周期。",
  },
  fisher_qa: {
    dimension: "Fisher 15 问覆盖率",
    rationale: "覆盖 14/15；管理层 Q11 没正面答。",
    preview:
      "**1. 业务足以支撑营收数年快速增长?** 服务业务是；硬件已成熟。\n**2. 是否有持续推出新产品/服务?** Vision Pro 评估中，目前未贡献营收。\n**3. R&D 效率?** $30B/yr R&D，~7% 营收占比；产出主要在芯片自研。\n**11. 长期管理层诚信?** 数据不足以下结论。\n*（其余 12 问见下方明细）*",
  },
  moat_assessment: {
    dimension: "护城河识别 + 量化",
    rationale: "品牌 + 生态都点到，但缺 switching cost 的量化锚点。",
    preview:
      "**品牌** Interbrand 排名第 1，估值 $516B。\n**生态系统锁定** 17 亿活跃设备，App Store + iCloud + iMessage 切换成本高。\n**芯片自研** M 系列 + A 系列性能领先竞品 1-1.5 代。\n\n_缺口：未给出切换成本的量化估计（如 $/user / yr）。_",
  },
  management_assessment: {
    dimension: "管理层 capital allocation",
    rationale: "ROIC 数据齐；buyback 历史只覆盖 3 年。",
    preview:
      "**Tim Cook 任期** 2011→ ROIC 维持 30%+。\n**Buyback** 2024 财年 $95B，过去 3 年总计 $260B。\n**Dividend** Payout ratio ~16%，保守可持续。\n\n_缺口：5 年以上 buyback yield 趋势未量化。_",
  },
  reverse_test: {
    dimension: "反向论证强度",
    rationale: "列了 3 个反方观点，每个都给了反驳路径。",
    preview:
      "**反方 1：iPhone 增长见顶** ✓ 已反映在硬件估值，服务给二次曲线。\n**反方 2：监管拆分 App Store** ✓ 估值已部分扣减，最坏 -15% 服务营收。\n**反方 3：中国市场流失** ✓ 大中华 18% 营收，悲观 -50% → -9% 总营收冲击。",
  },
  valuation: {
    dimension: "估值方法多样性 + 安全边际",
    rationale: "PE / EV-EBITDA / DCF 三套；DCF 假设 conservative，明确给出安全边际。",
    preview:
      "**PE TTM** 35.3x，vs 5 年中枢 28x — 溢价 26%。\n**EV/EBITDA** 26x，vs MSFT 22x / GOOGL 19x — 同行溢价。\n**DCF** 假设 r=10%, g=3%, FCF growth 5%/yr → IV ≈ $165/股 vs 当前 $231。\n\n**Margin of Safety: NEGATIVE 40%** — 当前价高于内在价值。",
  },
};

/** Dedupe artifact list by name — same artifact often gets rewritten
 *  multiple times within a single subagent (capability-review meta files
 *  especially), and duplicate React keys break the Badge map below. */
function dedupeArtifacts(items: { name: string }[]): { name: string }[] {
  const seen = new Set<string>();
  const out: { name: string }[] = [];
  for (const a of items) {
    if (seen.has(a.name)) continue;
    seen.add(a.name);
    out.push(a);
  }
  return out;
}

function mockScore(seed: string): number {
  let h = 2166136261;
  for (let i = 0; i < seed.length; i++) {
    h = (h ^ seed.charCodeAt(i)) >>> 0;
    h = (h * 16777619) >>> 0;
  }
  return 2.5 + (h % 25) / 10;
}

// ─── event → steps adapter ────────────────────────────────────────────

function extractSteps(events: AgentEvent[]): Step[] {
  const steps: Step[] = [];

  let firstSubagentIdx = events.findIndex((e) => e.type === "subagent_start");
  if (firstSubagentIdx === -1) firstSubagentIdx = events.length;

  const preEvents = events.slice(0, firstSubagentIdx);
  const preTools = preEvents.filter((e) => e.type === "tool_call");
  const preArts = preEvents.filter((e) => e.type === "artifact_written");
  if (preTools.length > 0 || preArts.length > 0) {
    const toolHist: Record<string, number> = {};
    for (const t of preTools) {
      const n = String(t.data?.name ?? "?");
      toolHist[n] = (toolHist[n] ?? 0) + 1;
    }
    const histLines = Object.entries(toolHist)
      .sort((a, b) => b[1] - a[1])
      .map(([n, c]) => `- \`${n}\` × ${c}`)
      .join("\n");
    steps.push({
      key: "phase:data-gather",
      kind: "phase",
      title: "Data gathering",
      subtitle: "subagent 启动前的工具调用密集段",
      startTs: events[0]?.ts,
      endTs: events[firstSubagentIdx - 1]?.ts,
      toolCalls: preTools.map((e) => ({ name: String(e.data?.name ?? "?") })),
      artifacts: dedupeArtifacts(
        preArts.map((e) => ({ name: String(e.data?.name ?? "?") })),
      ),
      previewMd: `**调用统计**\n${histLines}\n\n**Artifact**\n${
        preArts.map((a) => `- ${String(a.data?.name ?? "?")}`).join("\n") ||
        "(none)"
      }`,
      outcomeChecks: [
        {
          label: "≥3 种工具被调用",
          pass: Object.keys(toolHist).length >= 3,
          detail: `${Object.keys(toolHist).length} 种 / ${preTools.length} 次`,
        },
        {
          label: "数据采集 artifact 已落",
          pass: preArts.length > 0,
          detail: `${preArts.length} 个`,
        },
      ],
      rubric: {
        dimension: "Coverage · 数据源多样性",
        score: mockScore("phase:data-gather"),
        rationale: "覆盖行情/财务/新闻/SEC 四个面;news 只抓了一家口径。",
      },
    });
  }

  for (let i = 0; i < events.length; i++) {
    const e = events[i];
    if (e.type !== "subagent_start") continue;
    const name = String(e.data?.name ?? `step-${steps.length}`);
    let endIdx = -1;
    for (let j = i + 1; j < events.length; j++) {
      if (events[j].type === "subagent_end") {
        endIdx = j;
        break;
      }
    }
    if (endIdx === -1) endIdx = events.length - 1;
    const inner = events.slice(i + 1, endIdx);
    const tools = inner.filter((x) => x.type === "tool_call");
    const arts = inner.filter((x) => x.type === "artifact_written");

    const rubric = GATE_RUBRICS[name];
    const gateArtifact = arts.find((a) =>
      String(a.data?.name ?? "").includes("gate-"),
    );

    steps.push({
      key: `gate:${name}`,
      kind: "gate",
      title: name.replaceAll("_", " "),
      subtitle: `Gate ${steps.filter((s) => s.kind === "gate").length + 1}`,
      startTs: e.ts,
      endTs: events[endIdx]?.ts,
      toolCalls: tools.map((x) => ({ name: String(x.data?.name ?? "?") })),
      artifacts: dedupeArtifacts(
        arts.map((x) => ({ name: String(x.data?.name ?? "?") })),
      ),
      previewMd: rubric?.preview ?? `(${name} 的 gate artifact 预览)`,
      outcomeChecks: [
        {
          label: "gate artifact 已落",
          pass: Boolean(gateArtifact),
          detail: String(gateArtifact?.data?.name ?? "未找到 gate-*.md"),
        },
        {
          label: "未触发 max_steps / error",
          pass: !inner.some(
            (x) =>
              x.type === "error" ||
              String(x.data?.code ?? "").includes("max_"),
          ),
        },
      ],
      rubric: {
        dimension: rubric?.dimension ?? `${name} · 质量`,
        score: mockScore(`gate:${name}`),
        rationale: rubric?.rationale ?? "demo placeholder rationale.",
      },
    });
    i = endIdx;
  }

  let lastEnd = -1;
  for (let i = events.length - 1; i >= 0; i--) {
    if (events[i].type === "subagent_end") {
      lastEnd = i;
      break;
    }
  }
  if (lastEnd >= 0 && lastEnd < events.length - 1) {
    const tail = events.slice(lastEnd + 1);
    const tailArts = tail.filter((e) => e.type === "artifact_written");
    const synthNames = new Set(tailArts.map((e) => String(e.data?.name ?? "")));
    const hasFinal =
      synthNames.has("final-report.md") || synthNames.has("decision.json");
    steps.push({
      key: "phase:synthesis",
      kind: "synthesis",
      title: "Final synthesis",
      subtitle: "subagents 之后的综合 + decision 落库",
      startTs: events[lastEnd]?.ts,
      endTs: events[events.length - 1]?.ts,
      toolCalls: [],
      artifacts: dedupeArtifacts(
        tailArts.map((e) => ({ name: String(e.data?.name ?? "?") })),
      ),
      previewMd: `**核心产出**\n${tailArts
        .filter((a) => {
          const n = String(a.data?.name ?? "");
          return (
            n === "final-report.md" ||
            n === "decision.json" ||
            n === "ranking.json" ||
            n === "capital-plan.json" ||
            n === "peer-comparison.json"
          );
        })
        .map((a) => `- \`${String(a.data?.name ?? "?")}\``)
        .join("\n")}\n\n**Diagnostic artifacts**\n${tailArts
        .filter((a) => String(a.data?.name ?? "").includes("diagnosis"))
        .map((a) => `- \`${String(a.data?.name ?? "?")}\``)
        .join("\n")}`,
      outcomeChecks: [
        {
          label: "final-report / decision 已落",
          pass: hasFinal,
        },
        {
          label: "diagnostic artifacts 已落 (calibration 用)",
          pass:
            synthNames.has("company-run-diagnosis.json") ||
            synthNames.has("trace-diagnosis.json"),
        },
      ],
      rubric: {
        dimension: "Verdict 自洽度 · 论据闭环",
        score: mockScore("phase:synthesis"),
        rationale:
          "verdict 与 valuation gate 一致;conviction 数字与 reverse_test 给的反驳强度对得上。",
      },
    });
  }

  return steps;
}

function transcriptMetrics(run: RunDetail) {
  const counts: Record<string, number> = {};
  for (const e of run.events) counts[e.type] = (counts[e.type] ?? 0) + 1;
  const startTs = run.events[0]?.ts ?? run.started_at;
  const endTs = run.events[run.events.length - 1]?.ts ?? run.ended_at ?? startTs;
  return {
    toolCalls: counts["tool_call"] ?? 0,
    artifacts: counts["artifact_written"] ?? 0,
    subagents: counts["subagent_start"] ?? 0,
    durationMs: Math.max(0, (Number(endTs ?? 0) - Number(startTs ?? 0)) * 1000),
  };
}

// ─── client component ─────────────────────────────────────────────────

interface RowState {
  rating: "" | "up" | "down";
  notes: string;
  flagged: boolean;
}
const EMPTY_ROW: RowState = { rating: "", notes: "", flagged: false };

export function RunEvalDemoClient({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [defaultMode, setDefaultMode] = useState<"review" | "blind">("review");
  const [rows, setRows] = useState<Record<string, RowState>>({});

  useEffect(() => {
    setError(null);
    getRun(runId)
      .then(setRun)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "load failed"),
      );
  }, [runId]);

  const steps = useMemo(() => {
    if (!run) return [];
    const base = extractSteps(run.events);
    // Append the synthetic "final outcome" step — whole-run verdict.
    base.push({
      key: "outcome:final",
      kind: "outcome",
      title: "整体 outcome",
      subtitle: "整条 run 的 verdict 自洽性",
      previewMd: (run.summary || "(没有 summary)").slice(0, 1200),
      toolCalls: [],
      artifacts: [],
      outcomeChecks: [
        {
          label: "summary 非空",
          pass: Boolean(run.summary),
        },
        {
          label: "harness status = ok",
          pass: run.status === "ok",
        },
      ],
      rubric: {
        dimension: "Verdict 自洽 + 论据闭环",
        score: mockScore(`outcome:${run.id}`),
        rationale:
          "verdict = AVOID;valuation gate 给的安全边际 < 0,management gate 给的 capital allocation 中性,综合判断 supported。conviction 3/10 与 reverse_test 给出的反方论据强度一致。",
      },
    });
    return base;
  }, [run]);

  const metrics = useMemo(() => (run ? transcriptMetrics(run) : null), [run]);

  const aggregate = useMemo(() => {
    const scored = steps.filter((s) => s.rubric.score != null);
    if (scored.length === 0) return null;
    const avg =
      scored.reduce((acc, s) => acc + (s.rubric.score ?? 0), 0) / scored.length;
    return Math.round(avg * 10) / 10;
  }, [steps]);

  function update(key: string, patch: Partial<RowState>) {
    setRows((m) => ({ ...m, [key]: { ...(m[key] ?? EMPTY_ROW), ...patch } }));
  }

  if (error) {
    return (
      <PageContainer>
        <Card className="border-[color-mix(in_srgb,var(--loss)_40%,transparent)] p-4 text-[12px] text-[var(--loss)]">
          ⚠ {error}
          <div className="mt-2 text-[var(--ink-muted)]">
            可能是因为这条 run 不属于当前登录用户(跨用户隔离)。把 sessionStorage
            的 <code className="font-mono">uteki.access_token</code> 清掉后刷新即可
            (会变成 demo@local)。
          </div>
        </Card>
      </PageContainer>
    );
  }
  if (!run || !metrics) {
    return (
      <PageContainer>
        <div className="flex items-center gap-2 text-[12px] text-[var(--ink-muted)]">
          <Loader2 size={14} className="animate-spin" /> loading run…
        </div>
      </PageContainer>
    );
  }

  const flaggedCount = Object.values(rows).filter((r) => r.flagged).length;
  const labelledCount = Object.values(rows).filter((r) => r.rating).length;

  return (
    <PageContainer>
      <PageHeader
        eyebrow="DEMO · /runs/[id] · NOTION-STYLE EVAL"
        title={run.skill}
        subtitle="中间是被评测的内容,右侧是 eval 评论 — hover 内容,对应卡片会高亮 / 展开。"
        actions={
          <Link
            href={`/runs/${runId}`}
            className="font-mono text-[11px] tracking-[0.08em] text-[var(--accent)] hover:underline"
          >
            real /runs/{runId.slice(0, 8)} →
          </Link>
        }
      />

      <Card className="mb-4 border-[color-mix(in_srgb,var(--accent)_40%,transparent)] bg-[color-mix(in_srgb,var(--accent)_5%,transparent)] p-3">
        <div className="font-mono text-[10px] tracking-[0.1em] text-[var(--accent)]">
          DEMO · 评分只活在浏览器内存里 · 不会持久化
        </div>
        <div className="mt-1 text-[12px] leading-relaxed text-[var(--ink-soft)]">
          每个 step 的 eval 卡始终展开,顶部对齐内容头。outcome(程序化) /
          rubric(LLM 单维) / annotate(你说)三块一直在右侧 — 没有 hover 抖动
          也没有 sticky 飘移。
        </div>
      </Card>

      {/* Top rail */}
      <div className="mb-6 flex flex-wrap items-center gap-3 rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface-1)] p-3">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
            AGGREGATE
          </span>
          {aggregate != null ? <ScoreBadge score={aggregate} /> : "—"}
        </div>
        <span className="font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
          mean over {steps.length} steps
        </span>
        <span className="ml-auto flex items-center gap-3">
          <span className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
            DEFAULT MODE
          </span>
          <ModeChip
            icon={<Eye size={11} />}
            label="REVIEW"
            active={defaultMode === "review"}
            onClick={() => setDefaultMode("review")}
            title="judge 先给分,你审"
          />
          <ModeChip
            icon={<EyeOff size={11} />}
            label="BLIND"
            active={defaultMode === "blind"}
            onClick={() => setDefaultMode("blind")}
            title="先盲标,标完才看分"
          />
        </span>
        <span className="flex items-center gap-3 font-mono text-[11px] text-[var(--ink-faint)]">
          <span>
            <span className="text-[var(--ink-muted)]">labelled</span>{" "}
            <span className="text-[var(--ink-soft)]">
              {labelledCount} / {steps.length}
            </span>
          </span>
          <span>
            <span className="text-[var(--ink-muted)]">flagged</span>{" "}
            <span className="text-[var(--warn)]">{flaggedCount}</span>
          </span>
        </span>
      </div>

      {/* Two-column: content | eval comments. Both static, top-aligned, all
          eval cards always expanded — no hover dance, no collapse. */}
      <div className="space-y-4">
        {steps.map((s) => (
          <StepRow
            key={s.key}
            step={s}
            mode={defaultMode}
            row={rows[s.key] ?? EMPTY_ROW}
            onChange={(p) => update(s.key, p)}
          />
        ))}
      </div>

      <Card className="mt-6">
        <CardHeader>
          <div className="eyebrow">TRANSCRIPT METRICS · 程序化,不是 LLM</div>
        </CardHeader>
        <CardBody>
          <div className="grid grid-cols-2 gap-x-6 gap-y-3 font-mono text-[11px] md:grid-cols-4">
            <Metric
              label="duration"
              value={`${(metrics.durationMs / 1000).toFixed(1)} s`}
            />
            <Metric label="tool calls" value={String(metrics.toolCalls)} />
            <Metric label="artifacts" value={String(metrics.artifacts)} />
            <Metric label="subagents" value={String(metrics.subagents)} />
          </div>
        </CardBody>
      </Card>
    </PageContainer>
  );
}

// ─── step row (two-column) ────────────────────────────────────────────

function StepRow({
  step,
  mode,
  row,
  onChange,
}: {
  step: Step;
  mode: "review" | "blind";
  row: RowState;
  onChange: (p: Partial<RowState>) => void;
}) {
  return (
    <div className="grid grid-cols-[minmax(0,1fr)_360px] items-start gap-4">
      <ContentBlock step={step} />
      <EvalCard step={step} mode={mode} row={row} onChange={onChange} />
    </div>
  );
}

// ─── content block (left/center) ──────────────────────────────────────

function ContentBlock({ step }: { step: Step }) {
  const tone =
    step.kind === "gate"
      ? "border-[color-mix(in_srgb,var(--accent)_30%,var(--line))]"
      : step.kind === "outcome"
        ? "border-[color-mix(in_srgb,var(--gain)_40%,var(--line))]"
        : "border-[var(--line)]";

  return (
    <article
      className={
        "rounded-[var(--r-lg)] border bg-[var(--surface-1)] p-5 " + tone
      }
    >

      <header className="flex items-baseline gap-3">
        <Badge>{step.kind}</Badge>
        <h3 className="font-display italic text-[18px] tracking-tight text-[var(--ink)]">
          {step.title}
        </h3>
        {step.subtitle && (
          <span className="font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
            · {step.subtitle}
          </span>
        )}
        <span className="ml-auto flex items-center gap-2 font-mono text-[10px] text-[var(--ink-faint)]">
          {step.startTs && step.endTs && (
            <span>{Math.round((step.endTs - step.startTs) * 1000)} ms</span>
          )}
          {step.toolCalls.length > 0 && <span>{step.toolCalls.length} tools</span>}
          {step.artifacts.length > 0 && (
            <span>{step.artifacts.length} arts</span>
          )}
        </span>
      </header>

      {/* Preview content — simulates the artifact body that's being evaluated */}
      <div className="mt-4 whitespace-pre-line text-[13px] leading-relaxed text-[var(--ink)]">
        <MarkdownLite text={step.previewMd} />
      </div>

      {step.artifacts.length > 0 && (
        <div className="mt-4 flex flex-wrap gap-1.5">
          {step.artifacts.slice(0, 6).map((a) => (
            <Badge key={a.name} tone="neutral">
              {a.name}
            </Badge>
          ))}
          {step.artifacts.length > 6 && (
            <span className="font-mono text-[10px] text-[var(--ink-faint)]">
              +{step.artifacts.length - 6} more
            </span>
          )}
        </div>
      )}
    </article>
  );
}

// ─── eval card (right) ────────────────────────────────────────────────

function EvalCard({
  step,
  mode,
  row,
  onChange,
}: {
  step: Step;
  mode: "review" | "blind";
  row: RowState;
  onChange: (p: Partial<RowState>) => void;
}) {
  const reveal = mode === "review" || Boolean(row.rating);

  return (
    <aside className="rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface)]">
      <header className="flex items-center gap-2 border-b border-[var(--line)] px-3 py-2">
        <MessageSquare size={12} className="text-[var(--ink-faint)]" />
        <span className="font-mono text-[10px] tracking-[0.06em] text-[var(--ink-muted)]">
          EVAL
        </span>
        <span className="truncate text-[11px] text-[var(--ink-soft)]">
          {step.title}
        </span>
        <span className="ml-auto flex items-center gap-1.5">
          {reveal ? (
            <ScoreBadge score={step.rubric.score ?? 0} small />
          ) : (
            <Badge tone="neutral">⭐ ?</Badge>
          )}
          <OutcomeDots checks={step.outcomeChecks} />
          {row.rating === "up" && (
            <ThumbsUp size={11} className="text-[var(--gain)]" />
          )}
          {row.rating === "down" && (
            <ThumbsDown size={11} className="text-[var(--loss)]" />
          )}
          {row.flagged && <Flag size={11} className="text-[var(--warn)]" />}
        </span>
      </header>

      <div>
        <div className="space-y-4 p-3">
          {/* Outcome checks */}
          <section>
            <div className="mb-1.5 font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
              OUTCOME · 程序化
            </div>
            <ul className="space-y-1">
              {step.outcomeChecks.map((c, i) => (
                <li
                  key={i}
                  className="flex items-baseline gap-1.5 text-[11px] leading-relaxed"
                >
                  {c.pass === true ? (
                    <CheckCircle2
                      size={11}
                      className="shrink-0 text-[var(--gain)]"
                    />
                  ) : c.pass === false ? (
                    <AlertTriangle
                      size={11}
                      className="shrink-0 text-[var(--loss)]"
                    />
                  ) : (
                    <Info size={11} className="shrink-0 text-[var(--warn)]" />
                  )}
                  <span className="text-[var(--ink)]">{c.label}</span>
                  {c.detail && (
                    <span className="font-mono text-[10px] text-[var(--ink-faint)]">
                      {c.detail}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </section>

          {/* Rubric */}
          <section>
            <div className="mb-1.5 font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
              RUBRIC · LLM 单维
            </div>
            {reveal ? (
              <div>
                <div className="flex items-baseline gap-1.5">
                  <Sparkles size={11} className="text-[var(--accent)]" />
                  <span className="text-[12px] font-medium text-[var(--ink)]">
                    {step.rubric.dimension}
                  </span>
                </div>
                <div className="mt-1 text-[11px] leading-relaxed text-[var(--ink-soft)]">
                  {step.rubric.rationale}
                </div>
              </div>
            ) : (
              <div className="text-[11px] italic text-[var(--ink-muted)]">
                BLIND mode: 先标再看 rubric。
              </div>
            )}
          </section>

          {/* Annotate */}
          <section>
            <div className="mb-1.5 font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
              ANNOTATE · 你说
            </div>
            <div className="flex gap-1">
              <MiniBtn
                active={row.rating === "up"}
                tone="gain"
                onClick={() =>
                  onChange({ rating: row.rating === "up" ? "" : "up" })
                }
              >
                <ThumbsUp size={12} />
              </MiniBtn>
              <MiniBtn
                active={row.rating === "down"}
                tone="loss"
                onClick={() =>
                  onChange({ rating: row.rating === "down" ? "" : "down" })
                }
              >
                <ThumbsDown size={12} />
              </MiniBtn>
              <MiniBtn
                active={row.flagged}
                tone="warn"
                onClick={() => onChange({ flagged: !row.flagged })}
              >
                <Flag size={12} />
              </MiniBtn>
            </div>
            <textarea
              value={row.notes}
              onChange={(e) => onChange({ notes: e.target.value })}
              rows={2}
              placeholder="为什么 👍/👎?(留 trail 给 calibration)"
              className="mt-1.5 w-full resize-y rounded-md border border-[var(--line)] bg-[var(--surface-1)] px-2 py-1 text-[11px] leading-relaxed text-[var(--ink)] placeholder:text-[var(--ink-faint)] focus:border-[var(--accent)] focus:outline-none"
            />
          </section>
        </div>
      </div>
    </aside>
  );
}

// ─── presentational ───────────────────────────────────────────────────

/** Tiny dot strip showing pass/warn/fail at a glance — visible even when
 *  the eval card is collapsed. */
function OutcomeDots({
  checks,
}: {
  checks: { pass: boolean | "warn" }[];
}) {
  return (
    <span className="inline-flex items-center gap-0.5">
      {checks.map((c, i) => (
        <span
          key={i}
          className={
            "inline-block h-1.5 w-1.5 rounded-full " +
            (c.pass === true
              ? "bg-[var(--gain)]"
              : c.pass === false
                ? "bg-[var(--loss)]"
                : "bg-[var(--warn)]")
          }
        />
      ))}
    </span>
  );
}

function ScoreBadge({ score, small }: { score: number; small?: boolean }) {
  const tone: "gain" | "loss" | "warn" | "neutral" =
    score >= 4 ? "gain" : score >= 3 ? "neutral" : score >= 2 ? "warn" : "loss";
  return (
    <Badge tone={tone}>
      {small ? "" : "⭐ "}
      {score.toFixed(1)}
    </Badge>
  );
}

function ModeChip({
  icon,
  label,
  active,
  onClick,
  title,
}: {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  onClick: () => void;
  title: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className={
        "inline-flex h-7 items-center gap-1.5 rounded-md border px-2 font-mono text-[10px] tracking-[0.06em] transition-colors " +
        (active
          ? "border-[var(--accent)] bg-[color-mix(in_srgb,var(--accent)_10%,transparent)] text-[var(--accent)]"
          : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink-soft)]")
      }
    >
      {icon}
      {label}
    </button>
  );
}

function MiniBtn({
  children,
  active,
  tone,
  onClick,
}: {
  children: React.ReactNode;
  active: boolean;
  tone: "gain" | "loss" | "warn";
  onClick: () => void;
}) {
  const toneVar = tone === "gain" ? "--gain" : tone === "loss" ? "--loss" : "--warn";
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        "inline-flex h-6 items-center gap-0.5 rounded border px-1.5 text-[10px] transition-colors " +
        (active
          ? `border-[color-mix(in_srgb,var(${toneVar})_60%,transparent)] bg-[color-mix(in_srgb,var(${toneVar})_15%,transparent)] text-[var(${toneVar})]`
          : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink-soft)]")
      }
    >
      {children}
    </button>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
        {label.toUpperCase()}
      </div>
      <div className="mt-0.5 numeric tabular-nums text-[14px] text-[var(--ink)]">
        {value}
      </div>
    </div>
  );
}

/** Minimal markdown — just `**bold**`, `*italic*`, `` `code` ``, `- list`
 *  and `\n\n` paragraphs. We don't want to pull in a full MD lib for a
 *  demo preview. */
function MarkdownLite({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <>
      {lines.map((line, i) => {
        if (line.startsWith("- ")) {
          return (
            <div key={i} className="ml-3">
              · {renderInline(line.slice(2))}
            </div>
          );
        }
        if (line.trim() === "") return <div key={i} className="h-2" />;
        return <div key={i}>{renderInline(line)}</div>;
      })}
    </>
  );
}

function renderInline(text: string): React.ReactNode {
  // Split on bold / italic / code in a single pass.
  const parts: React.ReactNode[] = [];
  let i = 0;
  let key = 0;
  while (i < text.length) {
    if (text.startsWith("**", i)) {
      const end = text.indexOf("**", i + 2);
      if (end > 0) {
        parts.push(
          <strong key={key++} className="text-[var(--ink)]">
            {text.slice(i + 2, end)}
          </strong>,
        );
        i = end + 2;
        continue;
      }
    }
    if (text[i] === "`") {
      const end = text.indexOf("`", i + 1);
      if (end > 0) {
        parts.push(
          <code
            key={key++}
            className="rounded bg-[var(--surface-2)] px-1 font-mono text-[12px]"
          >
            {text.slice(i + 1, end)}
          </code>,
        );
        i = end + 1;
        continue;
      }
    }
    if (text[i] === "*") {
      const end = text.indexOf("*", i + 1);
      if (end > 0) {
        parts.push(
          <em key={key++} className="text-[var(--ink-soft)]">
            {text.slice(i + 1, end)}
          </em>,
        );
        i = end + 1;
        continue;
      }
    }
    // grab plain run up to next marker
    let next = text.length;
    for (const m of ["**", "`", "*"]) {
      const idx = text.indexOf(m, i);
      if (idx >= 0 && idx < next) next = idx;
    }
    parts.push(<span key={key++}>{text.slice(i, next)}</span>);
    i = next;
  }
  return parts;
}
