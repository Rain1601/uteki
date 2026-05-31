"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { SectionTitle } from "@/components/ui/SectionTitle";
import { API_BASE } from "@/lib/api";
import { authedFetch, canOperate, fetchMe, type AuthUser } from "@/lib/auth";
import { Play, CheckCircle2, XCircle, Target, ArrowUpRight } from "lucide-react";

interface EvalCase {
  id: string;
  description: string;
  messages: Array<{ role: string; content: string }>;
  expected_substrings: string[];
  expected_tools: string[];
}

interface CaseResult {
  case_id: string;
  passed: boolean;
  latency_ms: number;
  final_text: string;
  tools_called: string[];
  scores: { substring: number; tool: number };
  notes?: string;
}

interface EvalReport {
  started_at: number;
  duration_ms: number;
  results: CaseResult[];
  pass_rate: number;
}

export default function EvalsPage() {
  const [cases, setCases] = useState<EvalCase[]>([]);
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState<EvalReport | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const isAdmin = canOperate(user);

  useEffect(() => {
    fetch(`${API_BASE}/api/eval/cases`)
      .then((r) => r.json())
      .then((d) => setCases(d.items ?? []))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchMe().then(setUser).catch(() => setUser(null));
  }, []);

  async function runAll() {
    if (!isAdmin) return;
    setRunning(true);
    setReport(null);
    try {
      const r = await authedFetch(`${API_BASE}/api/eval/run`, { method: "POST" });
      setReport(await r.json());
    } finally {
      setRunning(false);
    }
  }

  return (
    <PageContainer>
      <PageHeader
        eyebrow="ENGINE · EVAL"
        title="Evaluation"
        subtitle="基于 case 给 skill 的输出打分。两个轴：(a) 最终回答是否覆盖关键词，(b) 是否调对了工具。pass_rate 可作合并门禁，趋势线监控质量回归。"
        actions={
          <Button variant="primary" onClick={runAll} disabled={!isAdmin || running}>
            <Play size={14} /> {running ? "Running…" : "Run all cases"}
          </Button>
        }
      />
      {!isAdmin && (
        <div className="mb-6 rounded-[var(--r)] border border-[var(--line)] bg-[var(--surface)] p-3 font-mono text-[11px] text-[var(--ink-muted)]">
          reader 模式：可以查看 case 和历史结果；运行 eval 仅限 admin。
        </div>
      )}

      {/* Methodology */}
      <Card className="mb-8 overflow-hidden">
        <CardHeader>
          <SectionTitle eyebrow="METHODOLOGY" title="How scoring works" className="mb-0" />
        </CardHeader>
        <CardBody>
          <div className="grid gap-6 md:grid-cols-3">
            <Method
              icon={Target}
              title="Substring score"
              body="检查 final assistant text 是否包含 expected_substrings 中的每一项。命中比例 / 期望数 = score。"
            />
            <Method
              icon={Target}
              title="Tool score"
              body="检查实际调用过的 tool 列表是否覆盖 expected_tools。命中比例 / 期望数 = score。"
            />
            <Method
              icon={Target}
              title="Pass criterion"
              body="substring_score ≥ 0.5 AND tool_score ≥ 0.5 → passed=true。两轴可独立加权（TODO）。"
            />
          </div>
          <div className="mt-6 rounded-md border border-[var(--line)] bg-[var(--surface)] p-4 font-mono text-[11px] leading-relaxed text-[var(--ink-soft)]">
            <span className="text-[var(--ink-faint)"># 未来计划</span><br />
            <span className="text-[var(--ink-faint)]">·</span> LLM-as-judge：用另一个模型给 final text 1-10 打分<br />
            <span className="text-[var(--ink-faint)]">·</span> baseline 漂移告警（pass_rate 比上次 -X% 即告警）<br />
            <span className="text-[var(--ink-faint)]">·</span> A/B 不同 skill version 在同一 case 集上的表现
          </div>
        </CardBody>
      </Card>

      {/* Cases */}
      <SectionTitle
        eyebrow="CASES"
        title="Test cases"
        trailing={<Badge>{cases.length} cases</Badge>}
      />
      <div className="mb-8 space-y-2">
        {cases.length === 0 && (
          <div className="rounded-[var(--r-lg)] border border-dashed border-[var(--line)] p-6 text-center text-[12px] text-[var(--ink-muted)]">
            后端未启动 或无 case。在 <span className="font-mono">services/api/src/uteki_api/eval/cases/*.json</span> 添加。
          </div>
        )}
        {cases.map((c) => (
          <Link
            key={c.id}
            href={`/evals/${encodeURIComponent(c.id)}`}
            className="block group"
          >
            <Card className="p-4 transition-colors group-hover:border-[var(--accent-line)]">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] tracking-[0.14em] text-[var(--ink-faint)]">
                      {c.id}
                    </span>
                    <ArrowUpRight
                      size={12}
                      className="text-[var(--ink-faint)] group-hover:text-[var(--accent)]"
                    />
                  </div>
                  <div className="mt-1.5 font-display italic text-[16px] text-[var(--ink)]">
                    {c.description}
                  </div>
                  <div className="mt-3 grid grid-cols-2 gap-4">
                    <Spec
                      label="EXPECTED SUBSTRINGS"
                      items={c.expected_substrings}
                      tone="accent"
                    />
                    <Spec
                      label="EXPECTED TOOLS"
                      items={c.expected_tools}
                      tone="warn"
                    />
                  </div>
                </div>
              </div>
            </Card>
          </Link>
        ))}
      </div>

      {/* Report */}
      {report && (
        <>
          <SectionTitle
            eyebrow="REPORT"
            title="Latest run"
            trailing={
              <div className="flex items-center gap-3">
                <span className="font-mono text-[11px] text-[var(--ink-faint)]">
                  {report.duration_ms} ms
                </span>
                <Badge tone={report.pass_rate >= 0.8 ? "gain" : report.pass_rate >= 0.5 ? "warn" : "loss"}>
                  pass_rate {(report.pass_rate * 100).toFixed(0)}%
                </Badge>
              </div>
            }
          />
          <div className="space-y-2">
            {report.results.map((r) => (
              <Card key={r.case_id} className="p-4">
                <div className="flex items-start gap-3">
                  {r.passed ? (
                    <CheckCircle2 size={16} className="mt-0.5 text-[var(--gain)] shrink-0" />
                  ) : (
                    <XCircle size={16} className="mt-0.5 text-[var(--loss)] shrink-0" />
                  )}
                  <div className="flex-1">
                    <div className="flex items-center gap-3">
                      <span className="font-mono text-[11px] text-[var(--ink)]">{r.case_id}</span>
                      <span className="font-mono text-[10px] text-[var(--ink-faint)]">
                        {r.latency_ms} ms
                      </span>
                      <span className="ml-auto flex gap-1.5">
                        <ScoreBar label="sub" value={r.scores.substring} />
                        <ScoreBar label="tool" value={r.scores.tool} />
                      </span>
                    </div>
                    <div className="mt-2 line-clamp-2 text-[12px] text-[var(--ink-soft)]">
                      {r.final_text}
                    </div>
                    <div className="mt-2 flex flex-wrap gap-1.5">
                      {r.tools_called.map((t) => (
                        <Badge key={t} tone="neutral">{t}</Badge>
                      ))}
                    </div>
                  </div>
                </div>
              </Card>
            ))}
          </div>
        </>
      )}
    </PageContainer>
  );
}

function Method({
  icon: Icon,
  title,
  body,
}: {
  icon: React.ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
  title: string;
  body: string;
}) {
  return (
    <div>
      <Icon size={16} strokeWidth={1.75} className="mb-2 text-[var(--accent)]" />
      <div className="font-display italic text-[15px] text-[var(--ink)]">{title}</div>
      <p className="mt-1 text-[11px] leading-relaxed text-[var(--ink-muted)]">{body}</p>
    </div>
  );
}

function Spec({
  label,
  items,
  tone,
}: {
  label: string;
  items: string[];
  tone: "accent" | "warn";
}) {
  return (
    <div>
      <div className="mb-1.5 font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
        {label}
      </div>
      <div className="flex flex-wrap gap-1">
        {items.length === 0 ? (
          <span className="text-[11px] text-[var(--ink-faint)]">—</span>
        ) : (
          items.map((s) => (
            <Badge key={s} tone={tone}>
              {s}
            </Badge>
          ))
        )}
      </div>
    </div>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100);
  const color =
    value >= 0.8 ? "var(--gain)" : value >= 0.5 ? "var(--warn)" : "var(--loss)";
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="font-mono text-[9px] uppercase tracking-[0.14em] text-[var(--ink-faint)]">
        {label}
      </span>
      <span className="relative inline-block h-1 w-12 overflow-hidden rounded-full bg-[var(--surface-2)]">
        <span
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${pct}%`, background: color }}
        />
      </span>
      <span className="font-mono text-[10px] text-[var(--ink-soft)]" style={{ color }}>
        {pct}
      </span>
    </span>
  );
}
