"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { Trace } from "@/components/agent/Trace";
import { Message } from "@/components/agent/Message";
import { Artifacts } from "@/components/agent/Artifacts";
import { RunRatingPanel } from "@/components/runs/RunRatingPanel";
import { PageContainer } from "@/components/ui/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { GenericArtifactPreview } from "@/components/artifact-renderers/GenericArtifactPreview";
import type { ArtifactRef, RunDetail } from "@/lib/api";
import { fetchMe, type AuthUser } from "@/lib/auth";
import { ArrowUpRight, ChevronLeft, ChevronDown, ChevronRight } from "lucide-react";

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
    if (byName.has(item.name)) byName.delete(item.name);
    byName.set(item.name, item);
  }
  return Array.from(byName.values());
}

// Skills whose runs produce a dossier-style dedicated product page. Listing
// runs of these skills here as a "debug view" with a banner jump to the
// product page is the cleanest contract — /runs/[id] is intentionally
// generic; the rich render lives at /<skill>/[id].
const DOSSIER_ROUTES: Record<string, { label: string; href: (runId: string) => string }> = {
  company_research_pipeline: {
    label: "公司研究档案",
    href: (id) => `/company-agent/${id}`,
  },
};

export function RunDetailView({
  run,
  hideRatingPanel = false,
}: {
  run: RunDetail;
  /** When the rating panel is rendered by a parent layout (e.g. the
   *  3-pane /runs explorer puts it in its own column), suppress the
   *  in-page panel here to avoid a duplicate annotator surface. */
  hideRatingPanel?: boolean;
}) {
  const [rawOpen, setRawOpen] = useState(false);
  // 013 — annotator surface. We need the user to gate RunRatingPanel
  // visibility; readers don't get the panel rendered at all.
  const [user, setUser] = useState<AuthUser | null>(null);
  useEffect(() => {
    fetchMe().then(setUser).catch(() => setUser(null));
  }, []);

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

  const artifactRefs: ArtifactRef[] = useMemo(() => {
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
  }, [run.artifacts, run.events]);
  const primary = artifactRefs.find((a) => a.role === "primary") ?? run.primary_artifact ?? null;
  const dossierRoute = DOSSIER_ROUTES[run.skill];

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

      {/* Dossier jump banner — when this run has a dedicated product view */}
      {dossierRoute && (
        <Link
          href={dossierRoute.href(run.id)}
          className="mb-6 flex items-center gap-3 rounded-[var(--r-lg)] border border-[var(--accent-line)] bg-[var(--accent-soft)] px-5 py-3.5 transition-colors hover:bg-[color-mix(in_srgb,var(--accent)_12%,transparent)]"
        >
          <div className="min-w-0 flex-1">
            <div className="font-mono text-[9px] tracking-[0.18em] uppercase text-[var(--accent)]">
              DOSSIER AVAILABLE
            </div>
            <div className="mt-1 font-display text-[15px] italic text-[var(--ink)]">
              这次 run 有完整的{dossierRoute.label}视图
            </div>
            <div className="mt-0.5 text-[12px] text-[var(--ink-muted)]">
              这页是 engine 调试视图（trace · artifacts · events）；要看面向用户的研究结论请走档案页。
            </div>
          </div>
          <span className="inline-flex items-center gap-1 font-mono text-[11px] tracking-[0.08em] uppercase text-[var(--accent)]">
            打开档案 <ArrowUpRight size={13} />
          </span>
        </Link>
      )}

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

      {/* 013 — annotator rating panel. Hidden entirely for non-annotators.
          Default collapsed; opens to a 👍/👎 + notes + 🚩 surface; AUTO
          score is revealed after labelling (server-side masking).
          Suppressed when a parent layout (e.g. /runs 3-pane) renders the
          panel in its own column. */}
      {!hideRatingPanel && <RunRatingPanel runId={run.id} user={user} />}

      {primary ? (
        <GenericArtifactPreview
          runId={run.id}
          artifact={primary}
          fallbackText={fallbackFinalText || run.summary || ""}
        />
      ) : null}

      {/* Artifacts — file-typed outputs (M5) */}
      {artifactRefs.length > 0 && (
        <Card className="mb-6">
          <CardHeader>
            <div className="eyebrow">ARTIFACTS · {artifactRefs.length}</div>
          </CardHeader>
          <CardBody>
            <Artifacts runId={run.id} items={artifactRefs} />
          </CardBody>
        </Card>
      )}

      {/* Trace + fallback conversation —
          stack vertically below lg (14" laptops get the trace full-width)
          to avoid crushing the CJK conversation column into single chars. */}
      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.4fr)_minmax(360px,1fr)]">
        <Card className="min-w-0 overflow-hidden">
          <CardHeader>
            <div className="eyebrow">EVENT TIMELINE</div>
          </CardHeader>
          <CardBody className="min-w-0">
            {run.events.length === 0 ? (
              <div className="text-[12px] text-[var(--ink-muted)]">无事件</div>
            ) : (
              <Trace events={run.events} />
            )}
          </CardBody>
        </Card>

        <Card className="min-w-0 overflow-hidden">
          <CardHeader>
            <div className="eyebrow">CONVERSATION</div>
          </CardHeader>
          <CardBody className="min-w-0 space-y-3">
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
