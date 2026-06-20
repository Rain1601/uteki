"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Empty } from "@/components/ui/Empty";
import { RunRatingPanel } from "@/components/runs/RunRatingPanel";
import { RunDetailView } from "./[id]/view";
import {
  getRun,
  listAgents,
  listRuns,
  type AgentInfo,
  type RunDetail,
  type RunSummary,
} from "@/lib/api";
import { canAnnotateRuns, fetchMe, type AuthUser } from "@/lib/auth";
import { ArrowUpRight, Flag, Loader2, RefreshCw } from "lucide-react";

/**
 * /runs — 3-pane explorer.
 *
 *   ┌────────────┬──────────────────────────┬────────────┐
 *   │ run list   │ run detail               │ eval panel │
 *   │ filters    │ summary + artifacts +    │ 👍/👎/🚩  │
 *   │ scroll     │ events                   │ notes      │
 *   └────────────┴──────────────────────────┴────────────┘
 *
 * Selected run is in the URL (?id=<runId>) so refresh / deep-link / share
 * works. Old /runs/[id] still exists for fullscreen single-run viewing.
 */

function formatTs(ts: number | undefined | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
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
  const flaggedFromUrl = searchParams.get("flagged") === "1";
  const selectedId = searchParams.get("id") ?? "";

  const [skill, setSkill] = useState(skillFromUrl);
  const [triggeredBy, setTriggeredBy] = useState(triggeredFromUrl);
  const [flagged, setFlagged] = useState(flaggedFromUrl);
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Detail fetched lazily when selectedId changes.
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState<string | null>(null);

  const showFlagged = canAnnotateRuns(user);

  useEffect(() => {
    setSkill(skillFromUrl);
    setTriggeredBy(triggeredFromUrl);
    setFlagged(flaggedFromUrl);
  }, [skillFromUrl, triggeredFromUrl, flaggedFromUrl]);

  useEffect(() => {
    fetchMe().then(setUser).catch(() => setUser(null));
  }, []);

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
        flagged: flagged || undefined,
      });
      setRuns(r.items);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }, [skill, triggeredBy, flagged]);

  useEffect(() => {
    fetchRuns();
  }, [fetchRuns]);

  // Lazy detail fetch when the user picks a run.
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      setDetailError(null);
      return;
    }
    let cancelled = false;
    setDetailLoading(true);
    setDetailError(null);
    getRun(selectedId)
      .then((d) => {
        if (cancelled) return;
        setDetail(d);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setDetailError(e instanceof Error ? e.message : "load failed");
      })
      .finally(() => {
        if (cancelled) return;
        setDetailLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  // If nothing's selected yet, auto-pick the first run as soon as the list
  // arrives so the middle + right columns don't look orphaned.
  useEffect(() => {
    if (!selectedId && runs.length > 0) {
      selectRun(runs[0].id);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runs.length]);

  const setUrl = useCallback(
    (next: Record<string, string | null>) => {
      const params = new URLSearchParams(searchParams.toString());
      for (const [k, v] of Object.entries(next)) {
        if (v == null || v === "") params.delete(k);
        else params.set(k, v);
      }
      const qs = params.toString();
      router.replace(qs ? `/runs?${qs}` : "/runs");
    },
    [router, searchParams],
  );

  const selectRun = useCallback(
    (id: string) => setUrl({ id }),
    [setUrl],
  );

  const setFilter = useCallback(
    (key: "skill" | "triggered_by", value: string) =>
      setUrl({ [key]: value || null }),
    [setUrl],
  );

  const toggleFlagged = useCallback(() => {
    setUrl({ flagged: flagged ? null : "1" });
  }, [flagged, setUrl]);

  const skillOptions = useMemo(
    () => agents.map((a) => a.name).sort(),
    [agents],
  );
  const triggerOptions = useMemo(
    () => Array.from(new Set(runs.map((r) => r.triggered_by))).sort(),
    [runs],
  );

  return (
    <div className="flex h-screen flex-col gap-3 p-4">
      {/* Header bar */}
      <header className="flex items-baseline gap-3">
        <div className="eyebrow">ENGINE · RUNS</div>
        <h1 className="font-display italic text-[22px] tracking-tight text-[var(--ink)]">
          Runs
        </h1>
        <span className="font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
          · 3-pane · 左列表 / 中详情 / 右 eval
        </span>
        <span className="ml-auto flex items-center gap-2">
          <Button onClick={fetchRuns} disabled={loading}>
            <RefreshCw
              size={12}
              className={loading ? "animate-spin" : ""}
            />{" "}
            Refresh
          </Button>
        </span>
      </header>

      {/* Filter rail */}
      <div className="flex flex-wrap items-center gap-3 rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface-1)] p-2.5">
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
        {showFlagged && (
          <button
            type="button"
            onClick={toggleFlagged}
            className={
              "inline-flex h-7 items-center gap-1.5 rounded-md border px-2 font-mono text-[10px] tracking-[0.06em] transition-colors " +
              (flagged
                ? "border-[color-mix(in_srgb,var(--warn)_60%,transparent)] bg-[color-mix(in_srgb,var(--warn)_10%,transparent)] text-[var(--warn)]"
                : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink-soft)]")
            }
            title={flagged ? "show all runs" : "show only flagged"}
          >
            <Flag size={10} />
            {flagged ? "FLAGGED ONLY" : "filter flagged"}
          </button>
        )}
        <span className="ml-auto font-mono text-[10px] text-[var(--ink-faint)]">
          {runs.length} runs
        </span>
      </div>

      {/* 3-pane body — each column scrolls independently */}
      <div className="grid min-h-0 flex-1 grid-cols-[300px_minmax(0,1fr)_400px] gap-3">
        {/* LEFT — run list */}
        <aside className="min-h-0 overflow-y-auto rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface-1)]">
          {error && (
            <div className="border-b border-[color-mix(in_srgb,var(--loss)_40%,transparent)] p-3 text-[11px] text-[var(--loss)]">
              ⚠ {error}
            </div>
          )}
          {runs.length === 0 && !loading ? (
            <Empty
              title="Nothing here yet"
              hint={
                skill ? "这个 skill 还没被触发过。" : "去研究台触发一次。"
              }
              action={
                <Link
                  href="/skills"
                  className="inline-flex items-center gap-2 font-mono text-[10px] tracking-[0.08em] uppercase text-[var(--accent)] hover:underline"
                >
                  Browse skills <ArrowUpRight size={12} />
                </Link>
              }
            />
          ) : (
            <ul>
              {runs.map((r) => (
                <RunListItem
                  key={r.id}
                  run={r}
                  active={r.id === selectedId}
                  onSelect={() => selectRun(r.id)}
                />
              ))}
            </ul>
          )}
        </aside>

        {/* MIDDLE — run detail */}
        <main className="min-h-0 overflow-y-auto rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface-1)] p-4">
          {!selectedId ? (
            <CenterEmpty title="选一条 run" hint="从左侧列表点一条进来。" />
          ) : detailLoading ? (
            <div className="flex items-center gap-2 text-[12px] text-[var(--ink-muted)]">
              <Loader2 size={14} className="animate-spin" /> loading run…
            </div>
          ) : detailError ? (
            <CenterEmpty
              title="加载失败"
              hint={detailError}
            />
          ) : detail ? (
            <RunDetailView run={detail} hideRatingPanel />
          ) : null}
        </main>

        {/* RIGHT — eval panel (real, persists to RunFeedback) */}
        <aside className="min-h-0 overflow-y-auto rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface-1)] p-4">
          {selectedId ? (
            <RunRatingPanel runId={selectedId} user={user} />
          ) : (
            <CenterEmpty
              title="Eval"
              hint="选一条 run 后,这里出现 👍/👎/🚩 + notes + 自动评分。"
            />
          )}
        </aside>
      </div>
    </div>
  );
}

// ─── left rail item ───────────────────────────────────────────────────

function RunListItem({
  run,
  active,
  onSelect,
}: {
  run: RunSummary;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onSelect}
        className={
          "block w-full cursor-pointer border-b border-[var(--line)] px-3 py-2.5 text-left transition-colors " +
          (active
            ? "bg-[color-mix(in_srgb,var(--accent)_8%,transparent)]"
            : "hover:bg-[var(--surface-2)]")
        }
      >
        <div className="flex items-baseline gap-2">
          <span className="truncate font-display italic text-[13px] tracking-tight text-[var(--ink)]">
            {run.skill}
          </span>
          <Badge tone={statusTone(run.status)}>{run.status}</Badge>
        </div>
        <div className="mt-1 line-clamp-1 text-[11px] leading-snug text-[var(--ink-soft)]">
          {run.summary || run.user_input || "(no summary)"}
        </div>
        <div className="mt-1.5 flex items-center gap-2 font-mono text-[9px] tracking-[0.04em] text-[var(--ink-faint)]">
          <span>{run.triggered_by}</span>
          <span>·</span>
          <span>{formatTs(run.started_at)}</span>
        </div>
      </button>
    </li>
  );
}

// ─── small helpers ────────────────────────────────────────────────────

function CenterEmpty({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="flex h-full min-h-[200px] flex-col items-center justify-center gap-1 text-center">
      <div className="font-display italic text-[14px] text-[var(--ink-muted)]">
        {title}
      </div>
      <div className="text-[11px] text-[var(--ink-faint)]">{hint}</div>
    </div>
  );
}

function FilterField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
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
      className="rounded-md border border-[var(--line-strong)] bg-[var(--surface)] px-2 py-1 font-mono text-[10px] text-[var(--ink-soft)] transition-colors hover:bg-[var(--surface-2)]"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value} className="bg-[var(--surface)]">
          {o.label}
        </option>
      ))}
    </select>
  );
}
