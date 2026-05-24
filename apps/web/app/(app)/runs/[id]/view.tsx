"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { Trace } from "@/components/agent/Trace";
import { Message } from "@/components/agent/Message";
import { Artifacts } from "@/components/agent/Artifacts";
import { PageContainer } from "@/components/ui/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import type { ArtifactRef, RunDetail } from "@/lib/api";
import { ChevronLeft, ChevronDown, ChevronRight } from "lucide-react";

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

export function RunDetailView({ run }: { run: RunDetail }) {
  const [rawOpen, setRawOpen] = useState(false);

  const finalText = useMemo(
    () =>
      run.events
        .filter((ev) => ev.type === "delta")
        .map((ev) => String(ev.data.text ?? ""))
        .join(""),
    [run.events],
  );

  const eventCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const ev of run.events) counts[ev.type] = (counts[ev.type] ?? 0) + 1;
    return counts;
  }, [run.events]);

  // Extract artifact metadata from the event stream (no extra fetch).
  const artifactRefs: ArtifactRef[] = useMemo(
    () =>
      run.events
        .filter((ev) => ev.type === "artifact_written")
        .map((ev) => ({
          name: String(ev.data.name ?? ""),
          kind: (ev.data.kind as ArtifactRef["kind"]) ?? "binary",
          size_bytes: Number(ev.data.size_bytes ?? 0),
          written_by: String(ev.data.written_by ?? ""),
          description: ev.data.description ? String(ev.data.description) : "",
          url: String(ev.data.url ?? ""),
        }))
        .filter((a) => a.name),
    [run.events],
  );

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

      {/* Trace + Final answer */}
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
            {finalText ? (
              <Message role="assistant" content={finalText} />
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
