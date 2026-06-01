"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Empty } from "@/components/ui/Empty";
import {
  listAgents,
  listRuns,
  type AgentInfo,
  type RunSummary,
} from "@/lib/api";
import { ArrowUpRight, RefreshCw } from "lucide-react";

function formatTs(ts: number | undefined | null): string {
  if (!ts) return "—";
  const d = new Date(ts * 1000);
  return d.toLocaleString();
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

export default function RunsPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const skillFromUrl = searchParams.get("skill") ?? "";
  const triggeredFromUrl = searchParams.get("triggered_by") ?? "";

  const [skill, setSkill] = useState(skillFromUrl);
  const [triggeredBy, setTriggeredBy] = useState(triggeredFromUrl);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Sync local filter state when URL changes (back/forward, deep link).
  useEffect(() => {
    setSkill(skillFromUrl);
    setTriggeredBy(triggeredFromUrl);
  }, [skillFromUrl, triggeredFromUrl]);

  // Pull the canonical skill list from the registry so the dropdown shows
  // every skill, not just ones the current user happens to have runs for.
  useEffect(() => {
    listAgents()
      .then((r) => setAgents(r.items))
      .catch(() => setAgents([]));
  }, []);

  const fetchRuns = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await listRuns({
        skill: skill || undefined,
        triggered_by: triggeredBy || undefined,
        limit: 100,
      });
      setRuns(r.items);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [skill, triggeredBy]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  // Push filter changes into the URL so refresh / deep-link / share works.
  const setFilter = useCallback(
    (key: "skill" | "triggered_by", value: string) => {
      const params = new URLSearchParams(searchParams.toString());
      if (value) params.set(key, value);
      else params.delete(key);
      const qs = params.toString();
      router.replace(qs ? `/runs?${qs}` : "/runs");
    },
    [router, searchParams],
  );

  const skillOptions = useMemo(
    () => agents.map((a) => a.name).sort(),
    [agents],
  );
  const triggerOptions = useMemo(
    () => Array.from(new Set(runs.map((r) => r.triggered_by))).sort(),
    [runs],
  );

  return (
    <PageContainer>
      <PageHeader
        eyebrow="ENGINE · RUNS"
        title="Runs"
        subtitle="每一条 run 都是 harness 编排过一次 skill 的留痕：trigger 来源、命中的工具、最终输出、token 用量、版本号——全在事件流里。"
        actions={
          <Button onClick={fetchRuns} disabled={loading}>
            <RefreshCw size={14} className={loading ? "animate-spin" : ""} /> Refresh
          </Button>
        }
      />

      {/* Filter rail */}
      <div className="mb-6 flex flex-wrap items-center gap-3 rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface-1)] p-3">
        <FilterField label="SKILL">
          <FilterSelect
            value={skill}
            onChange={(v) => setFilter("skill", v)}
            options={[
              { value: "", label: "all" },
              ...skillOptions.map((s) => ({ value: s, label: s })),
            ]}
          />
        </FilterField>
        <FilterField label="TRIGGER">
          <FilterSelect
            value={triggeredBy}
            onChange={(v) => setFilter("triggered_by", v)}
            options={[
              { value: "", label: "all" },
              ...triggerOptions.map((s) => ({ value: s, label: s })),
            ]}
          />
        </FilterField>
        <span className="ml-auto font-mono text-[11px] text-[var(--ink-faint)]">
          {runs.length} runs
        </span>
      </div>

      {error && (
        <Card className="mb-4 border-[color-mix(in_srgb,var(--loss)_40%,transparent)] p-4 text-[12px] text-[var(--loss)]">
          ⚠ {error}
        </Card>
      )}

      {runs.length === 0 && !loading ? (
        <Empty
          title={
            skill
              ? `没有 ${skill} 的 run`
              : "Nothing here yet"
          }
          hint={
            skill
              ? "这个 skill 还没被触发过，或者你筛选了其他 trigger 类型。"
              : "去关注列表 / 研究台触发一次，run 会出现在这里。"
          }
          action={
            <Link
              href={skill ? `/agents/${encodeURIComponent(skill)}` : "/agents"}
              className="inline-flex items-center gap-2 font-mono text-[11px] tracking-[0.08em] uppercase text-[var(--accent)] hover:underline"
            >
              {skill ? "View skill" : "Browse skills"} <ArrowUpRight size={14} />
            </Link>
          }
        />
      ) : (
        <ul className="space-y-2">
          {runs.map((r) => {
            const dur = durationMs(r);
            return (
              <li key={r.id}>
                <Link
                  href={`/runs/${r.id}`}
                  className="group block rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface-1)] p-4 transition-colors hover:border-[var(--line-strong)] hover:bg-[var(--surface-2)]"
                >
                  <div className="flex flex-wrap items-baseline gap-3">
                    <span className="font-display italic text-[18px] tracking-tight text-[var(--ink)]">
                      {r.skill}
                    </span>
                    {r.skill_version && (
                      <span className="font-mono text-[10px] tracking-[0.08em] text-[var(--ink-faint)]">
                        {r.skill_version}
                      </span>
                    )}
                    <Badge>{r.triggered_by}</Badge>
                    <span className="ml-auto flex items-center gap-3">
                      {dur != null && (
                        <span className="numeric text-[11px] text-[var(--ink-muted)]">
                          {dur} ms
                        </span>
                      )}
                      <Badge tone={statusTone(r.status)}>{r.status}</Badge>
                    </span>
                  </div>
                  {r.trigger_reason && (
                    <div className="mt-2 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
                      reason: {r.trigger_reason}
                    </div>
                  )}
                  {(r.summary || r.user_input) && (
                    <div className="mt-2 line-clamp-2 text-[13px] leading-relaxed text-[var(--ink-soft)]">
                      {r.summary || r.user_input}
                    </div>
                  )}
                  <div className="mt-3 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
                    {formatTs(r.started_at)} → {formatTs(r.ended_at)} ·{" "}
                    <span className="text-[var(--ink-muted)]">{r.id}</span>
                  </div>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </PageContainer>
  );
}

function FilterField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="flex items-center gap-2">
      <span className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
        {label}
      </span>
      {children}
    </label>
  );
}

function FilterSelect({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-md border border-[var(--line-strong)] bg-[var(--surface)] px-2.5 py-1.5 font-mono text-[11px] text-[var(--ink-soft)] hover:bg-[var(--surface-2)] transition-colors"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value} className="bg-[var(--surface)]">
          {o.label}
        </option>
      ))}
    </select>
  );
}
