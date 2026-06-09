import { Calendar } from "lucide-react";
import type { EarningsEvent } from "@/lib/api";
import { cn } from "@/lib/cn";

/** Days from now until ``iso`` (rounded toward zero). Negative = past. */
function daysFromNow(iso: string): number {
  return Math.round((new Date(iso).getTime() - Date.now()) / (1000 * 60 * 60 * 24));
}

type Urgency = "soon" | "near" | "later" | "past";

function urgency(days: number): Urgency {
  if (days < 0) return "past";
  if (days <= 3) return "soon";
  if (days <= 14) return "near";
  return "later";
}

function label(days: number): string {
  if (days < 0) return `${Math.abs(days)}d 前`;
  if (days === 0) return "今天";
  return `${days}d`;
}

const TONE_CLASS: Record<Urgency, string> = {
  soon: "text-[var(--loss)] border-[color-mix(in_srgb,var(--loss)_45%,transparent)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)]",
  near: "text-[var(--warn)] border-[color-mix(in_srgb,var(--warn)_45%,transparent)] bg-[color-mix(in_srgb,var(--warn)_8%,transparent)]",
  later: "text-[var(--accent)] border-[var(--accent-line)] bg-[var(--accent-soft)]",
  past: "text-[var(--ink-faint)] border-[var(--line)]",
};

/**
 * Compact countdown pill — used in /admin/companies rows, /company-agent
 * watchlist cards, and the trg-news-002 ticker rail. Hides itself when
 * there's no upcoming event so consumers don't have to null-check.
 *
 * ``size`` is "sm" for inline-with-meta rendering (10px text, no icon),
 * "md" for header-strip rendering (11px text, calendar icon).
 */
export function EarningsCountdown({
  event,
  size = "md",
  className,
}: {
  event: EarningsEvent | null | undefined;
  size?: "sm" | "md";
  className?: string;
}) {
  if (!event) return null;
  const days = daysFromNow(event.expected_date);
  const tone = urgency(days);
  const date = new Date(event.expected_date).toLocaleDateString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  });
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm border font-mono tracking-[0.04em]",
        TONE_CLASS[tone],
        size === "sm" ? "px-1.5 py-0 text-[9px]" : "px-2 py-0.5 text-[10px]",
        className,
      )}
      title={`下次财报 ${event.fiscal_period} · ${date} · ${event.bmo_amc}`}
    >
      {size === "md" && <Calendar size={10} />}
      {label(days)}
      {size === "md" && (
        <span className="text-[var(--ink-faint)]">· {date}</span>
      )}
    </span>
  );
}
