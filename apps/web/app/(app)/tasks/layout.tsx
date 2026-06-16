"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useSelectedLayoutSegment } from "next/navigation";
import { BarChart3, Loader2, RefreshCw, Settings2 } from "lucide-react";
import { Button } from "@/components/ui/Button";
import { canAdmin, fetchMe, type AuthUser } from "@/lib/auth";
import {
  KIND_ICON,
  KIND_LABEL,
  loadTriggers,
  type AgentTrigger,
  type TriggerKind,
} from "@/lib/triggers";
import { cn } from "@/lib/cn";

/**
 * /tasks shell. Two-row, two-column grid:
 *
 *   ┌─ HEADER (full width) ─────────────────────────────────────────────┐
 *   │ eyebrow + h-display + counters + 刷新 + 管理 trigger              │
 *   ├──────────────┬─────────────────────────────────────────────────────┤
 *   │ TRIGGERS     │ <children>                                          │
 *   │ Overview ●   │  • /tasks       → stats dashboard                  │
 *   │ ...triggers  │  • /tasks/[id]  → filter rail + article feed       │
 *   └──────────────┴─────────────────────────────────────────────────────┘
 *
 * The header mirrors ``/company-agent``'s pattern (eyebrow + italic
 * h-display + inline counters + right-aligned actions, all spanning the
 * full window width above both the sidebar and the content).
 *
 * Header content adapts to the active route via ``useSelectedLayoutSegment``:
 * the segment is ``null`` on ``/tasks`` (Overview) and the trigger id
 * string on ``/tasks/[id]`` — we surface the matching trigger's name /
 * kind / cadence in that case.
 *
 * The 刷新 button broadcasts a window-level ``tasks-refresh`` CustomEvent.
 * Pages listen for it and re-fetch their own data — keeps the layout
 * free of page-specific data and avoids passing setters through context.
 */
export default function TasksLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [triggers, setTriggers] = useState<AgentTrigger[] | null>(null);
  const [triggerError, setTriggerError] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const pathname = usePathname();
  const segment = useSelectedLayoutSegment();  // null on /tasks, id on /tasks/[id]
  const isOverview = pathname === "/tasks";
  const activeTrigger =
    !isOverview && triggers && segment
      ? triggers.find((t) => t.id === segment) ?? null
      : null;

  const loadList = useCallback(async () => {
    try {
      const rows = await loadTriggers(true);
      setTriggers(rows);
    } catch (e) {
      setTriggerError(e instanceof Error ? e.message : "load failed");
    }
  }, []);

  useEffect(() => {
    void loadList();
  }, [loadList]);

  useEffect(() => {
    fetchMe().then(setUser).catch(() => setUser(null));
  }, []);

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      await loadList();
      // Tell pages to re-fetch their own data. Pages opt in by listening
      // for this event in a useEffect; if no listener is attached we just
      // refresh the trigger list.
      window.dispatchEvent(new CustomEvent("tasks-refresh"));
    } finally {
      setRefreshing(false);
    }
  }, [loadList]);

  // Header copy — depends on segment.
  const headerEyebrow = isOverview
    ? "TASKS · OVERVIEW"
    : activeTrigger
      ? `TASKS · ${(KIND_LABEL[activeTrigger.kind as TriggerKind] ?? activeTrigger.kind).toUpperCase()}`
      : "TASKS · TRIGGER";
  const headerTitle = isOverview
    ? "监听台"
    : activeTrigger?.name ?? (segment ? segment : "—");
  const headerStats = triggers
    ? isOverview
      ? `${triggers.length} 个 trigger · ${triggers.filter((t) => t.enabled).length} 监听中`
      : activeTrigger
        ? `${activeTrigger.cadence_text || `每 ${activeTrigger.cadence_minutes} 分钟`}${
            activeTrigger.enabled ? " · LISTENING" : " · PAUSED"
          }`
        : "未找到该 trigger"
    : "loading…";

  return (
    <div className="flex h-screen flex-col overflow-hidden paper-grain">
      {/* ─── Full-width header strip ────────────────────────────────── */}
      <div className="shrink-0 border-b border-[var(--line)] px-8 py-5">
        <div className="flex flex-wrap items-end gap-5">
          <div className="min-w-0">
            <div className="eyebrow mb-1.5">{headerEyebrow}</div>
            <h1 className="h-display text-[32px] text-[var(--ink)]">
              {headerTitle}
            </h1>
          </div>
          <div className="mb-1 font-mono text-[10px] tracking-[0.18em] text-[var(--ink-faint)]">
            {headerStats}
            {user ? ` · ${user.role.toUpperCase()}` : ""}
          </div>
          <div className="ml-auto mb-1 flex items-center gap-2">
            <Button variant="ghost" onClick={refresh} disabled={refreshing}>
              <RefreshCw size={13} className={refreshing ? "animate-spin" : ""} />
              刷新
            </Button>
            {canAdmin(user) && (
              <Link href="/admin/triggers">
                <Button variant="primary">
                  <Settings2 size={13} /> 管理 trigger
                </Button>
              </Link>
            )}
          </div>
        </div>
      </div>

      {/* ─── Sidebar + content row ──────────────────────────────────── */}
      <div className="flex min-h-0 flex-1">
        <aside className="hidden w-[260px] shrink-0 flex-col border-r border-[var(--line)] lg:flex">
          <div className="shrink-0 border-b border-[var(--line)] px-5 py-4">
            <div className="eyebrow">TRIGGERS</div>
            <div className="mt-1 font-mono text-[10px] tracking-[0.1em] text-[var(--ink-faint)]">
              {triggers ? `${triggers.length} 个监听器` : "loading…"}
            </div>
          </div>

          <nav className="min-h-0 flex-1 overflow-y-auto">
            <TriggerRow
              href="/tasks"
              active={isOverview}
              icon={<BarChart3 size={14} />}
              name="Overview"
              sub="活动概览 · 统计"
            />

            {triggerError && (
              <div className="px-5 py-3 font-mono text-[10px] text-[var(--loss)]">
                {triggerError}
              </div>
            )}
            {!triggers && !triggerError && (
              <div className="flex items-center gap-2 px-5 py-4 font-mono text-[10px] text-[var(--ink-muted)]">
                <Loader2 size={11} className="animate-spin" />
                loading…
              </div>
            )}
            {triggers?.map((t) => {
              const kind = t.kind as TriggerKind;
              const Icon = KIND_ICON[kind] ?? KIND_ICON.news;
              return (
                <TriggerRow
                  key={t.id}
                  href={`/tasks/${t.id}`}
                  active={segment === t.id}
                  icon={<Icon size={14} />}
                  name={t.name}
                  source={KIND_LABEL[kind] ?? t.kind}
                  condition={t.condition}
                  cadence={t.cadence_text || `每 ${t.cadence_minutes} 分钟`}
                  paused={!t.enabled}
                />
              );
            })}
          </nav>
        </aside>

        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </div>
  );
}

function TriggerRow({
  href,
  active,
  icon,
  name,
  sub,
  source,
  condition,
  cadence,
  paused,
}: {
  href: string;
  active: boolean;
  icon: React.ReactNode;
  name: string;
  sub?: string;
  source?: string;
  condition?: string;
  cadence?: string;
  paused?: boolean;
}) {
  return (
    <Link
      href={href}
      className={cn(
        "block border-l-2 px-5 py-3 transition-colors",
        active
          ? "border-[var(--accent)] bg-[var(--accent-soft)]"
          : "border-transparent hover:bg-[var(--surface-hover)]",
      )}
    >
      <div className="flex items-start gap-2">
        <span
          className={cn(
            "mt-px shrink-0",
            active ? "text-[var(--accent)]" : "text-[var(--ink-muted)]",
          )}
        >
          {icon}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <div
              className={cn(
                "min-w-0 truncate font-display text-[14px] italic leading-tight",
                active ? "text-[var(--accent)]" : "text-[var(--ink)]",
              )}
            >
              {name}
            </div>
            {paused && (
              <span className="shrink-0 rounded-sm border border-[var(--line)] px-1.5 font-mono text-[8px] tracking-[0.12em] text-[var(--ink-faint)]">
                PAUSED
              </span>
            )}
          </div>
          {sub && (
            <div className="mt-1 truncate font-mono text-[9px] tracking-[0.06em] text-[var(--ink-muted)]">
              {sub}
            </div>
          )}
          {source && (
            <div className="mt-1 truncate font-mono text-[9px] tracking-[0.08em] text-[var(--ink-faint)]">
              {source.toUpperCase()}
            </div>
          )}
          {condition && (
            <div className="mt-1 line-clamp-2 text-[10.5px] leading-snug text-[var(--ink-muted)]">
              {condition}
            </div>
          )}
          {cadence && (
            <div className="mt-1 truncate font-mono text-[9px] tracking-[0.05em] text-[var(--ink-faint)]">
              ⌬ {cadence}
            </div>
          )}
        </div>
      </div>
    </Link>
  );
}
