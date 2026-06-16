"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { Layers, Loader2 } from "lucide-react";
import {
  KIND_ICON,
  KIND_LABEL,
  loadTriggers,
  type AgentTrigger,
  type TriggerKind,
} from "@/lib/triggers";
import { cn } from "@/lib/cn";

/**
 * /tasks shell: three-column layout owned by the route group.
 *
 *   ┌──────────────┬─────────────────────────────────────────────────┐
 *   │ trigger list │ <children> = filter rail + article feed         │
 *   │  (this file) │   (apps/web/components/tasks/TaskFeedView.tsx)  │
 *   └──────────────┴─────────────────────────────────────────────────┘
 *
 * - ``/tasks`` (this page.tsx) renders the merged "全部" view.
 * - ``/tasks/[id]`` renders that specific trigger.
 *
 * The left sidebar lists every persisted trigger and highlights the active
 * one based on URL segment. We fetch the trigger list once here and
 * children consume the URL's :id; no shared context needed.
 */
export default function TasksLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [triggers, setTriggers] = useState<AgentTrigger[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const params = useParams<{ id?: string }>();
  const pathname = usePathname();
  const activeId = params.id ?? null; // null on /tasks, set on /tasks/[id]
  const isAllView = pathname === "/tasks";

  useEffect(() => {
    loadTriggers()
      .then(setTriggers)
      .catch((e: unknown) =>
        setError(e instanceof Error ? e.message : "load failed"),
      );
  }, []);

  return (
    <div className="flex h-screen overflow-hidden paper-grain">
      <aside className="hidden w-[260px] shrink-0 flex-col border-r border-[var(--line)] lg:flex">
        <div className="shrink-0 border-b border-[var(--line)] px-5 py-4">
          <div className="eyebrow">TRIGGERS</div>
          <div className="mt-1 font-mono text-[10px] tracking-[0.1em] text-[var(--ink-faint)]">
            {triggers ? `${triggers.length} 个监听器` : "loading…"}
          </div>
        </div>

        <nav className="min-h-0 flex-1 overflow-y-auto">
          {/* "全部" — merged feed of every trigger's hits */}
          <TriggerRow
            href="/tasks"
            active={isAllView}
            icon={<Layers size={14} />}
            name="全部"
            sub="全部 trigger 合并"
          />

          {error && (
            <div className="px-5 py-3 font-mono text-[10px] text-[var(--loss)]">
              {error}
            </div>
          )}
          {!triggers && !error && (
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
                active={activeId === t.id}
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
