"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Empty } from "@/components/ui/Empty";
import {
  getAgent,
  listRuns,
  listVersions,
  type AgentDetail,
  type RunSummary,
  type SkillVersion,
} from "@/lib/api";
import { ArrowUpRight, ChevronLeft, GitBranch } from "lucide-react";

function formatTs(ts: number | undefined | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

function durationMs(r: RunSummary): number | undefined {
  if (!r.ended_at || !r.started_at) return undefined;
  return Math.round((r.ended_at - r.started_at) * 1000);
}

function statusTone(s: string): "gain" | "loss" | "warn" | "neutral" {
  if (s === "ok" || s === "success") return "gain";
  if (s === "error" || s === "failed" || s === "timeout") return "loss";
  if (s === "running") return "warn";
  return "neutral";
}

export default function AgentDetailPage() {
  const params = useParams<{ name: string }>();
  const name = decodeURIComponent(params.name);

  const [agent, setAgent] = useState<AgentDetail | null>(null);
  const [recentRuns, setRecentRuns] = useState<RunSummary[]>([]);
  const [versions, setVersions] = useState<SkillVersion[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const [a, runs, vs] = await Promise.all([
          getAgent(name),
          listRuns({ skill: name, limit: 5 }),
          listVersions(name),
        ]);
        if (cancelled) return;
        setAgent(a);
        setRecentRuns(runs.items);
        setVersions(
          (vs.items ?? []).slice().sort((x, y) => y.created_at - x.created_at),
        );
      } catch (e) {
        if (!cancelled) setError((e as Error).message);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [name]);

  const cur = agent?.current_version;
  const tools = cur?.tool_names ?? agent?.default_tools ?? [];
  const model = cur?.model ?? agent?.default_model ?? "";

  return (
    <PageContainer>
      <div className="mb-4">
        <Link
          href="/agents"
          className="inline-flex items-center gap-1.5 font-mono text-[11px] tracking-[0.08em] uppercase text-[var(--ink-faint)] hover:text-[var(--ink)] transition-colors"
        >
          <ChevronLeft size={12} /> All skills
        </Link>
      </div>

      <PageHeader
        eyebrow={`CATALOG · ${agent?.kind === "pipeline" ? "PIPELINE" : "SKILL"}`}
        title={name}
        subtitle={agent?.description ?? "—"}
        actions={
          <Link
            href={`/runs?skill=${encodeURIComponent(name)}`}
            className="inline-flex items-center gap-2 rounded-md border border-[var(--accent-line)] bg-[var(--accent-soft)] px-3 py-1.5 font-mono text-[11px] tracking-[0.08em] uppercase text-[var(--accent)] hover:brightness-110 transition"
          >
            View all runs <ArrowUpRight size={12} />
          </Link>
        }
      />

      {error && (
        <Card className="mb-4 border-[color-mix(in_srgb,var(--loss)_40%,transparent)] p-4 text-[12px] text-[var(--loss)]">
          ⚠ {error}
        </Card>
      )}

      {/* Configuration row */}
      <div className="mb-8 grid gap-3 md:grid-cols-3">
        <Card>
          <CardBody>
            <div className="eyebrow mb-2">VERSION</div>
            <div className="font-mono text-[18px] text-[var(--ink)]">
              {agent?.version ?? "—"}
            </div>
            {cur?.changelog && (
              <div className="mt-2 text-[11px] leading-relaxed text-[var(--ink-soft)]">
                {cur.changelog}
              </div>
            )}
          </CardBody>
        </Card>
        <Card>
          <CardBody>
            <div className="eyebrow mb-2">MODEL</div>
            <div className="font-mono text-[12px] text-[var(--ink-soft)]">
              {model || "—"}
            </div>
          </CardBody>
        </Card>
        <Card>
          <CardBody>
            <div className="eyebrow mb-2">TOOLS</div>
            {tools.length === 0 ? (
              <div className="font-mono text-[11px] text-[var(--ink-faint)]">none</div>
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {tools.map((t) => (
                  <Badge key={t}>{t}</Badge>
                ))}
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* Recent runs */}
      <Card className="mb-8">
        <CardHeader>
          <div className="flex items-center justify-between">
            <div className="eyebrow">RECENT RUNS</div>
            <Link
              href={`/runs?skill=${encodeURIComponent(name)}`}
              className="font-mono text-[10px] uppercase tracking-[0.08em] text-[var(--accent)] hover:underline"
            >
              See all →
            </Link>
          </div>
        </CardHeader>
        <CardBody>
          {recentRuns.length === 0 ? (
            <Empty title="No runs yet" hint="这个 skill 还没有被触发过。" />
          ) : (
            <ul className="space-y-2">
              {recentRuns.map((r) => {
                const dur = durationMs(r);
                return (
                  <li key={r.id}>
                    <Link
                      href={`/runs/${r.id}`}
                      className="group block rounded-[var(--r)] border border-[var(--line)] bg-[var(--surface-1)] p-3 transition-colors hover:border-[var(--line-strong)] hover:bg-[var(--surface-2)]"
                    >
                      <div className="flex flex-wrap items-baseline gap-3">
                        <Badge>{r.triggered_by}</Badge>
                        {r.skill_version && (
                          <span className="font-mono text-[10px] tracking-[0.08em] text-[var(--ink-faint)]">
                            {r.skill_version}
                          </span>
                        )}
                        <span className="ml-auto flex items-center gap-3">
                          {dur != null && (
                            <span className="numeric text-[11px] text-[var(--ink-muted)]">
                              {dur} ms
                            </span>
                          )}
                          <Badge tone={statusTone(r.status)}>{r.status}</Badge>
                        </span>
                      </div>
                      {(r.summary || r.user_input) && (
                        <div className="mt-2 line-clamp-1 text-[12px] leading-relaxed text-[var(--ink-soft)]">
                          {r.summary || r.user_input}
                        </div>
                      )}
                      <div className="mt-2 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
                        {formatTs(r.started_at)} ·{" "}
                        <span className="text-[var(--ink-muted)]">{r.id}</span>
                      </div>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )}
        </CardBody>
      </Card>

      {/* Version history */}
      <Card>
        <CardHeader>
          <div className="flex items-center gap-2">
            <GitBranch size={13} className="text-[var(--accent)]" />
            <span className="eyebrow">VERSION HISTORY</span>
          </div>
        </CardHeader>
        <CardBody>
          {versions.length === 0 ? (
            <div className="font-mono text-[11px] text-[var(--ink-faint)]">
              没有版本记录
            </div>
          ) : (
            <ol className="relative space-y-3 pl-5">
              <span
                aria-hidden
                className="absolute left-[6px] top-2 bottom-2 w-px bg-[var(--line)]"
              />
              {versions.map((v, i) => (
                <li key={v.version} className="relative">
                  <span
                    aria-hidden
                    className="absolute -left-[14px] top-2 h-2 w-2 rounded-full ring-2 ring-[var(--surface)]"
                    style={{
                      background: i === 0 ? "var(--accent)" : "var(--ink-muted)",
                    }}
                  />
                  <div className="rounded-[var(--r)] border border-[var(--line)] bg-[var(--surface-1)] p-3">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="font-mono text-[12px] font-semibold text-[var(--ink)]">
                        {v.version}
                      </span>
                      {v.parent_version && (
                        <span className="font-mono text-[10px] text-[var(--ink-faint)]">
                          ← {v.parent_version}
                        </span>
                      )}
                      <Badge>{v.model}</Badge>
                      <span className="ml-auto font-mono text-[10px] text-[var(--ink-faint)]">
                        {formatTs(v.created_at)}
                      </span>
                    </div>
                    {v.changelog && (
                      <div className="mt-2 text-[12px] text-[var(--ink-soft)]">
                        {v.changelog}
                      </div>
                    )}
                    {v.tool_names && v.tool_names.length > 0 && (
                      <div className="mt-2 flex flex-wrap gap-1">
                        {v.tool_names.map((t) => (
                          <Badge key={t}>{t}</Badge>
                        ))}
                      </div>
                    )}
                    {v.prompt && (
                      <details className="mt-2">
                        <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-[0.08em] text-[var(--ink-muted)] hover:text-[var(--ink)]">
                          view prompt
                        </summary>
                        <pre className="mt-2 max-h-60 overflow-auto rounded-sm bg-[var(--surface)] p-2 font-mono text-[10px] leading-relaxed text-[var(--ink-muted)] whitespace-pre-wrap">
                          {v.prompt}
                        </pre>
                      </details>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          )}
        </CardBody>
      </Card>
    </PageContainer>
  );
}
