"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import {
  CalendarClock,
  ExternalLink,
  Loader2,
  TrendingUp,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody } from "@/components/ui/Card";
import {
  fetchNewsStats,
  type NewsStatsResponse,
  type ArticleSummaryDTO,
} from "@/lib/api";
import { cn } from "@/lib/cn";

/**
 * /tasks — overview dashboard.
 *
 * Layout:
 *   ┌─ TILES ─────────────────────────────────────────────────────────────┐
 *   │  [total]  [24h]  [7d]  [impact distribution]                        │
 *   ├─ STATISTICS (2 columns) ─────────────────────────────────────────────┤
 *   │ TOP CRITICAL (≤10)            │ TRIGGER ACTIVITY (last 7d)          │
 *   │ TOP SYMBOLS (≤10)             │ UPCOMING EARNINGS (next ≤10)        │
 *   └──────────────────────────────────────────────────────────────────────┘
 *
 * The full-width header (eyebrow + h-display + stats + 刷新 + 管理 trigger)
 * and the left trigger sidebar are owned by ``tasks/layout.tsx``. When the
 * layout's 刷新 button fires, it dispatches a ``tasks-refresh`` window
 * event that this page subscribes to so the stats re-fetch in lockstep
 * with the trigger-list reload.
 */
export default function TasksOverviewPage() {
  const [stats, setStats] = useState<NewsStatsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await fetchNewsStats();
      setStats(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Re-fetch when the layout-level 刷新 button fires the broadcast event.
  useEffect(() => {
    const handler = () => void refresh();
    window.addEventListener("tasks-refresh", handler);
    return () => window.removeEventListener("tasks-refresh", handler);
  }, [refresh]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
        {error && (
          <div className="mb-4 border border-[color-mix(in_srgb,var(--loss)_40%,transparent)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)] px-4 py-3 font-mono text-[11px] text-[var(--loss)]">
            {error}
          </div>
        )}

        {loading && !stats && (
          <div className="flex h-40 items-center justify-center text-[12px] text-[var(--ink-muted)]">
            <Loader2 size={14} className="mr-2 animate-spin" />
            loading stats…
          </div>
        )}

        {stats && (
          <div className="space-y-6">
            {/* Stat tiles — 4 across on lg+ */}
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              <StatTile label="文章总数" value={stats.total_articles} sub="all-time" />
              <StatTile label="24 小时" value={stats.articles_24h} sub="rolling 24h" />
              <StatTile label="7 天" value={stats.articles_7d} sub="rolling 7d" />
              <ImpactTile by_impact={stats.by_impact} />
            </div>

            {/* Two-column statistics grid */}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <Panel title="重要新闻 · TOP 10" subtitle="近 7 天 · 负面 / 关键事件优先">
                {stats.top_critical.length === 0 ? (
                  <EmptyPanel hint="近期没有标记为 negative / critical 的新闻。等下一轮 ingest。" />
                ) : (
                  <ul className="divide-y divide-[var(--line)]">
                    {stats.top_critical.map((a) => (
                      <CriticalRow key={a.id} article={a} />
                    ))}
                  </ul>
                )}
              </Panel>

              <Panel title="Trigger 活动" subtitle="近 7 天命中次数 · 已停用排末位">
                {stats.trigger_activity.length === 0 ? (
                  <EmptyPanel hint="还没有 trigger。" />
                ) : (
                  <ul className="space-y-1.5">
                    {stats.trigger_activity.map((t) => (
                      <TriggerActivityRow
                        key={t.id}
                        trigger={t}
                        maxCount={Math.max(
                          1,
                          ...stats.trigger_activity.map((x) => x.count_7d),
                        )}
                      />
                    ))}
                  </ul>
                )}
              </Panel>

              <Panel title="热门标的 · TOP 10" subtitle="近 7 天被新闻提到最多的 ticker">
                {stats.top_symbols.length === 0 ? (
                  <EmptyPanel hint="近 7 天还没有公司新闻命中 ticker。" />
                ) : (
                  <ul className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                    {stats.top_symbols.map((s) => (
                      <SymbolChip key={s.symbol} item={s} />
                    ))}
                  </ul>
                )}
              </Panel>

              <Panel title="临近财报" subtitle="watchlist 内最近的 10 场">
                {stats.upcoming_earnings.length === 0 ? (
                  <EmptyPanel hint="watchlist 还没有挂未来的财报。" />
                ) : (
                  <ul className="divide-y divide-[var(--line)]">
                    {stats.upcoming_earnings.map((e) => (
                      <EarningsRow key={e.id} item={e} />
                    ))}
                  </ul>
                )}
              </Panel>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Sub-components ─────────────────────────────────────────────────

function StatTile({
  label,
  value,
  sub,
}: {
  label: string;
  value: number;
  sub: string;
}) {
  return (
    <Card className="overflow-hidden">
      <CardBody className="px-4 py-3.5">
        <div className="eyebrow text-[var(--ink-faint)]">{label}</div>
        <div className="numeric mt-1.5 font-display text-[28px] leading-none text-[var(--ink)]">
          {value.toLocaleString()}
        </div>
        <div className="mt-1.5 font-mono text-[9px] tracking-[0.08em] text-[var(--ink-faint)]">
          {sub}
        </div>
      </CardBody>
    </Card>
  );
}

function ImpactTile({ by_impact }: { by_impact: Record<string, number> }) {
  const pos = by_impact.positive ?? 0;
  const neg = by_impact.negative ?? 0;
  const neu = by_impact.neutral ?? 0;
  const unknown = by_impact.unknown ?? 0;
  const total = pos + neg + neu + unknown;
  const pct = (n: number) => (total === 0 ? 0 : Math.round((n / total) * 100));
  return (
    <Card className="overflow-hidden">
      <CardBody className="px-4 py-3.5">
        <div className="eyebrow text-[var(--ink-faint)]">IMPACT 分布</div>
        <div className="mt-2 flex h-2.5 overflow-hidden rounded-sm border border-[var(--line)]">
          {pos > 0 && (
            <div
              className="bg-[var(--gain)]"
              style={{ width: `${pct(pos)}%` }}
              title={`正面 ${pos}`}
            />
          )}
          {neg > 0 && (
            <div
              className="bg-[var(--loss)]"
              style={{ width: `${pct(neg)}%` }}
              title={`负面 ${neg}`}
            />
          )}
          {neu > 0 && (
            <div
              className="bg-[color-mix(in_srgb,var(--ink-muted)_70%,transparent)]"
              style={{ width: `${pct(neu)}%` }}
              title={`中性 ${neu}`}
            />
          )}
          {unknown > 0 && (
            <div
              className="bg-[var(--surface-hover)]"
              style={{ width: `${pct(unknown)}%` }}
              title={`未标 ${unknown}`}
            />
          )}
        </div>
        <div className="mt-2 flex flex-wrap gap-2 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-muted)]">
          <span className="text-[var(--gain)]">↑{pos}</span>
          <span className="text-[var(--loss)]">↓{neg}</span>
          <span>—{neu}</span>
          <span className="text-[var(--ink-faint)]">·{unknown}</span>
        </div>
      </CardBody>
    </Card>
  );
}

function Panel({
  title,
  subtitle,
  children,
}: {
  title: string;
  subtitle: string;
  children: React.ReactNode;
}) {
  return (
    <Card className="overflow-hidden">
      <div className="border-b border-[var(--line)] px-5 py-3">
        <div className="font-display text-[15px] italic text-[var(--ink)]">{title}</div>
        <div className="mt-0.5 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
          {subtitle}
        </div>
      </div>
      <CardBody className="px-5 py-3">{children}</CardBody>
    </Card>
  );
}

function EmptyPanel({ hint }: { hint: string }) {
  return (
    <div className="py-6 text-center text-[11.5px] text-[var(--ink-muted)]">
      {hint}
    </div>
  );
}

function CriticalRow({ article }: { article: ArticleSummaryDTO }) {
  return (
    <li className="py-2.5 first:pt-0 last:pb-0">
      <div className="flex items-start gap-3">
        <div className="min-w-0 flex-1">
          <div className="font-display text-[13.5px] italic leading-snug text-[var(--ink)]">
            {article.title_zh ?? article.title}
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-2 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
            <span>{article.source.toUpperCase()}</span>
            <span>·</span>
            <span>{relativeFromNow(article.published_at)}</span>
            {article.symbols.length > 0 && (
              <>
                <span>·</span>
                <span className="numeric text-[var(--ink-muted)]">
                  {article.symbols.slice(0, 3).join(" · ")}
                </span>
              </>
            )}
          </div>
        </div>
        {article.impact && (
          <Badge
            tone={
              article.impact === "negative"
                ? "loss"
                : article.impact === "positive"
                  ? "gain"
                  : "neutral"
            }
          >
            {article.impact}
          </Badge>
        )}
        {article.url && !article.url.startsWith("demo://") && (
          <a
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 text-[var(--ink-muted)] hover:text-[var(--accent)]"
            title="外链"
          >
            <ExternalLink size={11} />
          </a>
        )}
      </div>
    </li>
  );
}

function TriggerActivityRow({
  trigger,
  maxCount,
}: {
  trigger: {
    id: string;
    name: string;
    kind: string;
    enabled: boolean;
    count_7d: number;
  };
  maxCount: number;
}) {
  const pct = Math.max(2, Math.round((trigger.count_7d / maxCount) * 100));
  return (
    <li>
      <Link
        href={`/tasks/${trigger.id}`}
        className="group block rounded-sm border border-transparent px-2 py-1.5 hover:border-[var(--line)] hover:bg-[var(--surface-hover)]"
      >
        <div className="flex items-baseline justify-between gap-3">
          <div className="min-w-0 flex-1 truncate font-display text-[13px] italic text-[var(--ink)]">
            {trigger.name}
            {!trigger.enabled && (
              <span className="ml-2 font-mono text-[9px] tracking-[0.1em] text-[var(--ink-faint)]">
                PAUSED
              </span>
            )}
          </div>
          <span className="numeric font-mono text-[11px] text-[var(--ink-soft)]">
            {trigger.count_7d}
          </span>
        </div>
        <div className="mt-1 h-1 overflow-hidden rounded-sm bg-[var(--surface-hover)]">
          <div
            className={cn(
              "h-full transition-all",
              trigger.enabled
                ? "bg-[var(--accent)]"
                : "bg-[color-mix(in_srgb,var(--ink-faint)_60%,transparent)]",
            )}
            style={{ width: `${pct}%` }}
          />
        </div>
      </Link>
    </li>
  );
}

function SymbolChip({
  item,
}: {
  item: { symbol: string; count_7d: number };
}) {
  return (
    <li>
      <Link
        href={`/tasks/trg-news-002`}
        className="group flex items-center justify-between rounded-sm border border-[var(--line)] bg-[var(--surface)] px-2.5 py-1.5 transition-colors hover:border-[var(--accent-line)] hover:bg-[var(--accent-soft)]"
        title={`查看 ${item.symbol} 的全部新闻`}
      >
        <span className="numeric font-display text-[14px] italic text-[var(--ink)] group-hover:text-[var(--accent)]">
          {item.symbol}
        </span>
        <span className="flex items-center gap-1 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-muted)]">
          <TrendingUp size={9} />
          {item.count_7d}
        </span>
      </Link>
    </li>
  );
}

function EarningsRow({
  item,
}: {
  item: {
    id: string;
    symbol: string;
    fiscal_period: string;
    expected_date: string;
    days_until: number;
  };
}) {
  return (
    <li className="py-2 first:pt-0 last:pb-0">
      <div className="flex items-center gap-3">
        <CalendarClock size={12} className="shrink-0 text-[var(--ink-muted)]" />
        <span className="numeric font-display text-[14px] italic text-[var(--ink)]">
          {item.symbol}
        </span>
        <span className="font-mono text-[10px] tracking-[0.04em] text-[var(--ink-muted)]">
          {item.fiscal_period}
        </span>
        <span className="grow" />
        <span className="font-mono text-[10px] tracking-[0.04em] text-[var(--ink-muted)]">
          {item.expected_date.slice(0, 10)}
        </span>
        <span
          className={cn(
            "rounded-sm border px-1.5 font-mono text-[10px] tracking-[0.04em]",
            item.days_until <= 3
              ? "border-[var(--accent-line)] bg-[var(--accent-soft)] text-[var(--accent)]"
              : "border-[var(--line)] text-[var(--ink-muted)]",
          )}
        >
          {item.days_until}d
        </span>
      </div>
    </li>
  );
}

function relativeFromNow(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} 小时前`;
  return `${Math.round(seconds / 86400)} 天前`;
}
