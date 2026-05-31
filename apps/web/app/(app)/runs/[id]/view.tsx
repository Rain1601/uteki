"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Trace } from "@/components/agent/Trace";
import { Message } from "@/components/agent/Message";
import { Artifacts } from "@/components/agent/Artifacts";
import { PageContainer } from "@/components/ui/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import type { ArtifactRef, RunDetail } from "@/lib/api";
import { fetchArtifactText } from "@/lib/api";
import { ChevronLeft, ChevronDown, ChevronRight, FileText, Scale, ShieldCheck } from "lucide-react";

function formatTs(ts: number | undefined | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

function durationMs(start?: number, end?: number | null): string {
  if (!start || !end) return "—";
  const ms = Math.max(0, (end - start) * 1000);
  if (ms < 1000) return `${ms.toFixed(0)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}

function statusTone(s: string): "gain" | "loss" | "warn" | "neutral" {
  if (s === "ok") return "gain";
  if (s === "error" || s === "timeout") return "loss";
  if (s === "running") return "warn";
  return "neutral";
}

function dedupeArtifactRefs(items: ArtifactRef[]): ArtifactRef[] {
  const byName = new Map<string, ArtifactRef>();
  for (const item of items) {
    if (!item.name) continue;
    // Artifact storage is last-write-wins for a run-scoped filename. Mirror
    // that behavior here because fallback event streams can include rewrites.
    if (byName.has(item.name)) byName.delete(item.name);
    byName.set(item.name, item);
  }
  return Array.from(byName.values());
}

export function RunDetailView({ run }: { run: RunDetail }) {
  const [rawOpen, setRawOpen] = useState(false);

  const fallbackFinalText = useMemo(
    () =>
      run.events
        .filter((ev) => ev.type === "delta")
        .map((ev) => String(ev.data.text ?? ""))
        .join(""),
    [run.events],
  );

  const eventCounts = useMemo(() => {
    if (run.events_summary) return run.events_summary;
    const counts: Record<string, number> = {};
    for (const ev of run.events) counts[ev.type] = (counts[ev.type] ?? 0) + 1;
    return counts;
  }, [run.events, run.events_summary]);

  const artifactRefs: ArtifactRef[] = useMemo(
    () => {
      const refs = run.artifacts?.length
        ? run.artifacts
        : run.events
            .filter((ev) => ev.type === "artifact_written")
            .map((ev) => ({
              name: String(ev.data.name ?? ""),
              kind: (ev.data.kind as ArtifactRef["kind"]) ?? "binary",
              size_bytes: Number(ev.data.size_bytes ?? 0),
              written_by: String(ev.data.written_by ?? ""),
              description: ev.data.description ? String(ev.data.description) : "",
              url: String(ev.data.url ?? ""),
              role: ev.data.role ? String(ev.data.role) : undefined,
              display_name: ev.data.display_name ? String(ev.data.display_name) : undefined,
            }))
            .filter((a) => a.name);
      return dedupeArtifactRefs(refs);
    },
    [run.artifacts, run.events],
  );
  const primary = artifactRefs.find((a) => a.role === "primary") ?? run.primary_artifact ?? null;

  return (
    <PageContainer>
      <div className="mb-6 flex items-center gap-3">
        <Link
          href="/runs"
          className="inline-flex items-center gap-1.5 font-mono text-[11px] tracking-[0.08em] uppercase text-[var(--ink-muted)] hover:text-[var(--ink)] transition-colors"
        >
          <ChevronLeft size={14} /> Runs
        </Link>
        <span className="ml-auto font-mono text-[10px] tracking-[0.08em] text-[var(--ink-faint)]">
          {run.id}
        </span>
      </div>

      {/* Header card */}
      <Card className="mb-8 overflow-hidden">
        <CardBody>
          <div className="flex flex-wrap items-baseline gap-3">
            <div className="eyebrow">RUN</div>
            <div className="font-display italic text-[32px] tracking-tight text-[var(--ink)]">
              {run.skill}
            </div>
            {run.skill_version && <Badge tone="accent">{run.skill_version}</Badge>}
            <Badge>{run.triggered_by}</Badge>
            <span className="ml-auto">
              <Badge tone={statusTone(run.status)}>{run.status}</Badge>
            </span>
          </div>
          {run.trigger_reason && (
            <div className="mt-3 font-mono text-[11px] tracking-[0.04em] text-[var(--ink-faint)]">
              reason: <span className="text-[var(--ink-soft)]">{run.trigger_reason}</span>
            </div>
          )}
          <div className="mt-5 grid grid-cols-2 gap-x-8 gap-y-3 sm:grid-cols-4">
            <Field label="STARTED">{formatTs(run.started_at)}</Field>
            <Field label="ENDED">{formatTs(run.ended_at)}</Field>
            <Field label="DURATION">{durationMs(run.started_at, run.ended_at)}</Field>
            <Field label="EVENTS">{run.events.length}</Field>
            <Field label="ARTIFACTS">{artifactRefs.length}</Field>
          </div>
          {/* Event histogram */}
          <div className="mt-5 flex flex-wrap gap-1.5">
            {Object.entries(eventCounts).map(([type, n]) => (
              <span
                key={type}
                className="inline-flex items-center gap-1.5 rounded-md border border-[var(--line)] bg-[var(--surface)] px-2 py-1"
              >
                <span className="font-mono text-[10px] tracking-[0.04em] text-[var(--ink-muted)]">
                  {type}
                </span>
                <span className="numeric text-[11px] text-[var(--ink)]">{n}</span>
              </span>
            ))}
          </div>
        </CardBody>
      </Card>

      {primary ? (
        <>
          {run.skill === "company_research_pipeline" && (
            <CompanyRunBrief runId={run.id} artifacts={artifactRefs} summary={run.summary ?? ""} />
          )}
        </>
      ) : null}

      {primary ? (
        <PrimaryArtifact runId={run.id} artifact={primary} fallbackText={fallbackFinalText || run.summary || ""} />
      ) : null}

      {/* Artifacts — file-typed outputs (M5) */}
      {artifactRefs.length > 0 && (
        <Card className="mb-6">
          <CardHeader>
            <div className="eyebrow">
              ARTIFACTS · {artifactRefs.length}
            </div>
          </CardHeader>
          <CardBody>
            <Artifacts runId={run.id} items={artifactRefs} />
          </CardBody>
        </Card>
      )}

      {/* Trace + fallback conversation */}
      <div className="grid gap-6 md:grid-cols-[1.2fr_1fr]">
        <Card>
          <CardHeader>
            <div className="eyebrow">EVENT TIMELINE</div>
          </CardHeader>
          <CardBody>
            {run.events.length === 0 ? (
              <div className="text-[12px] text-[var(--ink-muted)]">无事件</div>
            ) : (
              <Trace events={run.events} />
            )}
          </CardBody>
        </Card>

        <Card>
          <CardHeader>
            <div className="eyebrow">CONVERSATION</div>
          </CardHeader>
          <CardBody className="space-y-3">
            {run.user_input && <Message role="user" content={run.user_input} />}
            {fallbackFinalText ? (
              <Message role="assistant" content={fallbackFinalText} />
            ) : run.summary ? (
              <Message role="assistant" content={run.summary} />
            ) : (
              <div className="text-[12px] italic text-[var(--ink-muted)]">无回复</div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* Raw JSON */}
      <Card className="mt-6">
        <CardBody>
          <Button variant="ghost" onClick={() => setRawOpen((v) => !v)}>
            {rawOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />} Raw run JSON
          </Button>
          {rawOpen && (
            <pre className="mt-4 max-h-[480px] overflow-auto rounded-md bg-[var(--surface)] p-4 font-mono text-[11px] leading-relaxed text-[var(--ink-soft)]">
              {JSON.stringify(run, null, 2)}
            </pre>
          )}
        </CardBody>
      </Card>
    </PageContainer>
  );
}

interface DecisionArtifact {
  symbol?: string;
  action?: string;
  conviction?: number;
  target_rank?: number | null;
  initial_position_pct?: number | null;
  max_position_pct?: number | null;
  real_order_execution?: boolean;
}

interface CapitalPlanArtifact {
  symbol?: string;
  action?: string;
  initial_position_pct?: number;
  max_position_pct?: number;
  real_order_execution?: boolean;
  add_triggers?: string[];
  trim_triggers?: string[];
  sell_triggers?: string[];
}

interface RankingCompany {
  symbol?: string;
  rank?: number;
  role?: string;
  scores?: {
    total?: number;
    quality?: number;
    growth?: number;
    moat?: number;
    valuation?: number;
    risk?: number;
  };
}

interface RankingArtifact {
  target_symbol?: string;
  action?: string;
  target_rank?: number | null;
  ranked_companies?: RankingCompany[];
}

interface CompanyProfileArtifact {
  symbol?: string;
  peer_symbols?: string[];
}

function actionTone(action?: string): "gain" | "loss" | "warn" | "neutral" {
  if (action === "BUY") return "gain";
  if (action === "AVOID") return "loss";
  if (action === "WATCH") return "warn";
  return "neutral";
}

function pct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${Number(value).toFixed(1)}%`;
}

function hasArtifact(artifacts: ArtifactRef[], name: string): boolean {
  return artifacts.some((a) => a.name === name);
}

async function fetchJson<T>(runId: string, name: string): Promise<T | null> {
  const text = await fetchArtifactText(runId, name);
  return JSON.parse(text) as T;
}

function CompanyRunBrief({
  runId,
  artifacts,
  summary,
}: {
  runId: string;
  artifacts: ArtifactRef[];
  summary: string;
}) {
  const [decision, setDecision] = useState<DecisionArtifact | null>(null);
  const [capitalPlan, setCapitalPlan] = useState<CapitalPlanArtifact | null>(null);
  const [ranking, setRanking] = useState<RankingArtifact | null>(null);
  const [profile, setProfile] = useState<CompanyProfileArtifact | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const entries = await Promise.allSettled([
        hasArtifact(artifacts, "decision.json")
          ? fetchJson<DecisionArtifact>(runId, "decision.json")
          : Promise.resolve(null),
        hasArtifact(artifacts, "capital-plan.json")
          ? fetchJson<CapitalPlanArtifact>(runId, "capital-plan.json")
          : Promise.resolve(null),
        hasArtifact(artifacts, "ranking.json")
          ? fetchJson<RankingArtifact>(runId, "ranking.json")
          : Promise.resolve(null),
        hasArtifact(artifacts, "company-profile.json")
          ? fetchJson<CompanyProfileArtifact>(runId, "company-profile.json")
          : Promise.resolve(null),
      ]);
      if (cancelled) return;
      const [nextDecision, nextCapital, nextRanking, nextProfile] = entries.map((entry) =>
        entry.status === "fulfilled" ? entry.value : null,
      );
      setDecision(nextDecision as DecisionArtifact | null);
      setCapitalPlan(nextCapital as CapitalPlanArtifact | null);
      setRanking(nextRanking as RankingArtifact | null);
      setProfile(nextProfile as CompanyProfileArtifact | null);
    }
    load().catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [runId, artifacts]);

  const symbol =
    decision?.symbol ?? capitalPlan?.symbol ?? profile?.symbol ?? ranking?.target_symbol ?? "Company";
  const action = decision?.action ?? capitalPlan?.action ?? ranking?.action ?? "WATCH";
  const rankedCompanies = ranking?.ranked_companies ?? [];
  const gateArtifacts = artifacts.filter((a) => a.name.startsWith("gate-"));
  const peers = profile?.peer_symbols ?? rankedCompanies.filter((c) => c.symbol !== symbol).map((c) => c.symbol ?? "");
  const thesis = summary.split("\n").find((line) => line.trim().length > 30)?.trim();

  return (
    <section className="mb-6 border border-[var(--line-strong)] bg-[color-mix(in_srgb,var(--surface)_72%,transparent)] px-6 py-6">
      <div className="grid gap-8 lg:grid-cols-[minmax(0,1.1fr)_minmax(320px,0.9fr)]">
        <div>
          <div className="mb-6 inline-flex rotate-[-2deg] flex-col border border-[color-mix(in_srgb,var(--gain)_55%,transparent)] px-8 py-4 text-center shadow-[0_0_0_3px_color-mix(in_srgb,var(--gain)_12%,transparent)]">
            <span className="font-display text-[42px] italic leading-none text-[var(--gain)]">
              {action}
            </span>
            <span className="mt-2 font-mono text-[10px] tracking-[0.28em] text-[var(--gain)]">
              CONVICTION · {decision?.conviction != null ? decision.conviction.toFixed(2) : "—"}
            </span>
          </div>

          <div className="font-display text-[64px] italic leading-none text-[var(--ink)]">
            {symbol}
          </div>
          <p className="mt-5 max-w-2xl text-[17px] leading-relaxed text-[var(--ink-soft)]">
            {thesis ||
              "公司深度调研已经完成。先看结构化裁决、仓位计划和同行排序，再进入完整投资备忘录。"}
          </p>

          <div className="mt-8 grid grid-cols-2 gap-x-8 gap-y-5 md:grid-cols-4">
            <Metric label="INITIAL">{pct(decision?.initial_position_pct ?? capitalPlan?.initial_position_pct)}</Metric>
            <Metric label="MAX POSITION">{pct(decision?.max_position_pct ?? capitalPlan?.max_position_pct)}</Metric>
            <Metric label="TARGET RANK">{decision?.target_rank ?? ranking?.target_rank ?? "—"}</Metric>
            <Metric label="ORDER">{capitalPlan?.real_order_execution ? "enabled" : "disabled"}</Metric>
          </div>
        </div>

        <div className="space-y-6">
          <div>
            <div className="mb-3 flex items-center gap-2">
              <Scale size={14} className="text-[var(--accent)]" />
              <div className="eyebrow">PEER RANKING</div>
            </div>
            {rankedCompanies.length === 0 ? (
              <div className="border-t border-[var(--line)] py-4 text-[12px] text-[var(--ink-muted)]">
                等待 ranking.json
              </div>
            ) : (
              <ol className="border-t border-[var(--line)]">
                {rankedCompanies.map((company) => (
                  <li
                    key={`${company.rank ?? "x"}-${company.symbol ?? "company"}`}
                    className="grid grid-cols-[40px_minmax(0,1fr)_70px] border-b border-[var(--line)] py-3"
                  >
                    <span className="font-mono text-[10px] text-[var(--ink-faint)]">
                      #{company.rank ?? "—"}
                    </span>
                    <span className="font-display text-[16px] italic text-[var(--ink)]">
                      {company.symbol ?? "—"}
                    </span>
                    <span className="numeric text-right text-[12px] text-[var(--ink-soft)]">
                      {company.scores?.total?.toFixed(1) ?? "—"}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </div>

          <div>
            <div className="mb-3 flex items-center gap-2">
              <ShieldCheck size={14} className="text-[var(--accent)]" />
              <div className="eyebrow">CAPITAL PLAN</div>
              <Badge tone={actionTone(action)} className="ml-auto">
                {action}
              </Badge>
            </div>
            <div className="grid grid-cols-2 gap-3 border-t border-[var(--line)] pt-4">
              <MiniField label="peers">{peers.filter(Boolean).slice(0, 3).join(" · ") || "—"}</MiniField>
              <MiniField label="chapters">{gateArtifacts.length + 1} files</MiniField>
            </div>
            <TriggerList label="add" items={capitalPlan?.add_triggers} />
            <TriggerList label="trim" items={capitalPlan?.trim_triggers} />
          </div>
        </div>
      </div>
    </section>
  );
}

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
        {label}
      </div>
      <div className="mt-1 numeric text-[24px] leading-none text-[var(--ink)]">{children}</div>
    </div>
  );
}

function MiniField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
        {label}
      </div>
      <div className="mt-1 text-[12px] leading-relaxed text-[var(--ink-soft)]">{children}</div>
    </div>
  );
}

function TriggerList({ label, items }: { label: string; items?: string[] }) {
  if (!items?.length) return null;
  return (
    <div className="mt-4">
      <div className="mb-2 font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
        {label}
      </div>
      <ul className="space-y-1.5">
        {items.slice(0, 2).map((item) => (
          <li key={item} className="text-[12px] leading-relaxed text-[var(--ink-muted)]">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function PrimaryArtifact({
  runId,
  artifact,
  fallbackText,
}: {
  runId: string;
  artifact: ArtifactRef;
  fallbackText: string;
}) {
  const [content, setContent] = useState(fallbackText);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (artifact.kind === "binary") return;
    fetchArtifactText(runId, artifact.name)
      .then((text) => {
        if (artifact.kind === "json") {
          try {
            setContent(JSON.stringify(JSON.parse(text), null, 2));
            return;
          } catch {}
        }
        setContent(text);
      })
      .catch((e: Error) => setError(e.message));
  }, [runId, artifact.name, artifact.kind]);

  return (
    <Card className="mb-6">
      <CardHeader>
        <div className="flex items-center gap-2">
          <FileText size={15} className="text-[var(--accent)]" />
          <div className="eyebrow">
            PRIMARY ARTIFACT · {artifact.display_name || artifact.name}
          </div>
        </div>
      </CardHeader>
      <CardBody>
        {error ? (
          <div className="font-mono text-[11px] text-[var(--loss)]">Error: {error}</div>
        ) : (
          <pre className="max-h-[560px] overflow-auto whitespace-pre-wrap break-words rounded-md bg-[var(--surface)] p-4 font-mono text-[12px] leading-relaxed text-[var(--ink-soft)]">
            {content || "No content"}
          </pre>
        )}
      </CardBody>
    </Card>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
        {label}
      </div>
      <div className="mt-0.5 font-mono text-[11px] text-[var(--ink-soft)]">{children}</div>
    </div>
  );
}
