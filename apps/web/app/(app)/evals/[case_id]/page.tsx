"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { use } from "react";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import {
  listEvalCaseHistory,
  type EvalRecord,
} from "@/lib/api";
import { ChevronLeft } from "lucide-react";
import { LineChart, type ChartSeries } from "./Chart";

export default function EvalCaseDetailPage({
  params,
}: {
  params: Promise<{ case_id: string }>;
}) {
  const { case_id } = use(params);
  const [records, setRecords] = useState<EvalRecord[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listEvalCaseHistory(case_id, 50)
      .then((r) => setRecords(r.items ?? []))
      .catch(() => setRecords([]))
      .finally(() => setLoading(false));
  }, [case_id]);

  // newest-first → reverse for chronological chart
  const chronological = useMemo(() => [...records].reverse(), [records]);

  const series: ChartSeries[] = useMemo(() => {
    if (chronological.length === 0) return [];

    // Collect rubric names that appear in at least one record.
    const rubricNames = new Set<string>();
    for (const r of chronological) {
      for (const k of Object.keys(r.judge_scores ?? {})) rubricNames.add(k);
    }

    // pass_rate × 10 → share the 0..10 axis.
    const passSeries: ChartSeries = {
      name: "pass_rate ×10",
      color: "var(--accent)",
      points: chronological.map((r, i) => ({ x: i, y: r.pass_rate * 10 })),
    };

    const palette = ["#6f8db0", "#6faf8d", "#c9a97e", "#b0524a", "#9b87c4"];
    const rubricSeries: ChartSeries[] = Array.from(rubricNames).map((name, idx) => ({
      name,
      color: palette[idx % palette.length],
      points: chronological.map((r, i) => {
        const v = r.judge_scores?.[name];
        return { x: i, y: typeof v === "number" ? v : NaN };
      }),
    }));

    return [passSeries, ...rubricSeries];
  }, [chronological]);

  const latest = records[0];

  return (
    <PageContainer>
      <div className="mb-6">
        <Link
          href="/evals"
          className="inline-flex items-center gap-1.5 font-mono text-[11px] tracking-[0.08em] uppercase text-[var(--ink-muted)] hover:text-[var(--ink)] transition-colors"
        >
          <ChevronLeft size={14} /> evals
        </Link>
      </div>

      <PageHeader
        eyebrow="EVAL CASE"
        title={case_id}
        subtitle={
          latest
            ? `共 ${records.length} 次执行，最新 ${new Date(latest.started_at * 1000).toLocaleString()}`
            : "尚未有历史记录。跑一次 `/api/eval/run` 后回来。"
        }
        actions={
          latest?.decision ? <Badge tone={toneFor(latest.decision)}>{latest.decision}</Badge> : null
        }
      />

      {loading && (
        <Card className="mb-6">
          <CardBody>
            <div className="text-[12px] text-[var(--ink-muted)]">加载历史…</div>
          </CardBody>
        </Card>
      )}

      {!loading && records.length === 0 && (
        <Card className="mb-6">
          <CardBody>
            <div className="text-[13px] text-[var(--ink-muted)]">
              没有历史记录。运行评测后将自动出现。
            </div>
          </CardBody>
        </Card>
      )}

      {!loading && records.length > 0 && (
        <>
          <Card className="mb-6 overflow-hidden">
            <CardHeader>
              <div className="eyebrow">PASS RATE + JUDGE SCORES (NEWEST → RIGHT)</div>
            </CardHeader>
            <CardBody>
              <LineChart
                series={series}
                xAxisLabels={chronological.map((r) =>
                  new Date(r.started_at * 1000).toLocaleDateString(undefined, {
                    month: "numeric",
                    day: "numeric",
                  }),
                )}
              />
            </CardBody>
          </Card>

          <Card className="overflow-hidden">
            <CardHeader>
              <div className="eyebrow">HISTORY · NEWEST FIRST</div>
            </CardHeader>
            <CardBody>
              <ul className="divide-y divide-[var(--line)]">
                {records.map((r) => (
                  <li key={`${r.started_at}-${r.run_id ?? "x"}`} className="py-2.5 flex items-center gap-3">
                    <div className="font-mono text-[10px] tracking-[0.08em] text-[var(--ink-faint)] w-44">
                      {new Date(r.started_at * 1000).toLocaleString()}
                    </div>
                    <Badge tone={r.pass_rate >= 1 ? "gain" : r.pass_rate > 0 ? "warn" : "loss"}>
                      pass {Math.round(r.pass_rate * 100)}%
                    </Badge>
                    {r.decision && (
                      <Badge tone={toneFor(r.decision)}>{r.decision}</Badge>
                    )}
                    <div className="flex flex-wrap gap-1.5 flex-1">
                      {Object.entries(r.judge_scores).map(([k, v]) => (
                        <span
                          key={k}
                          className="inline-flex items-center gap-1 rounded-md border border-[var(--line)] bg-[var(--surface)] px-2 py-0.5 font-mono text-[10px] text-[var(--ink-soft)]"
                        >
                          {k}: <span className="text-[var(--ink)]">{v}/10</span>
                        </span>
                      ))}
                    </div>
                    {r.run_id && (
                      <Link
                        href={`/runs/${r.run_id}`}
                        className="font-mono text-[10px] tracking-[0.08em] uppercase text-[var(--ink-muted)] hover:text-[var(--accent)]"
                      >
                        {r.run_id.slice(0, 8)}↗
                      </Link>
                    )}
                  </li>
                ))}
              </ul>
            </CardBody>
          </Card>
        </>
      )}
    </PageContainer>
  );
}

function toneFor(decision: string): "gain" | "warn" | "loss" | "neutral" {
  if (decision === "approve") return "gain";
  if (decision === "revise") return "warn";
  if (decision === "reject") return "loss";
  return "neutral";
}
