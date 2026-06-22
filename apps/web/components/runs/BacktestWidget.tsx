"use client";

import { useEffect, useState } from "react";
import { Activity, Loader2, TrendingDown, TrendingUp } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { getRunPrediction, type RunPrediction } from "@/lib/api";

/**
 * 015 PR ε MVP — Screen 4 backtest widget.
 *
 * Renders on `/runs/[id]` right pane below the rating panel. Shows:
 *   - the frozen prediction (action / conviction / entry price at t0)
 *   - the LIVE current price + delta vs entry
 *   - SPY relative comparison (when both endpoints available)
 *   - 30 / 90 / 180 day horizon countdown bars
 *
 * Behaviors:
 *   - 404 from API → render nothing (skill isn't predictive)
 *   - other errors → quiet inline error
 *   - WATCH action gets a "verdict-neutral" pill since hit/miss only
 *     applies to BUY/AVOID by D1 hit definition
 */
export function BacktestWidget({ runId }: { runId: string }) {
  const [pred, setPred] = useState<RunPrediction | null>(null);
  const [loading, setLoading] = useState(true);
  const [missing, setMissing] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setMissing(false);
    setErr(null);
    getRunPrediction(runId)
      .then((p) => {
        if (cancelled) return;
        setPred(p);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        const msg = e instanceof Error ? e.message : String(e);
        if (msg === "no-prediction") setMissing(true);
        else setErr(msg);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  if (loading) {
    return (
      <Card className="mt-3">
        <CardBody className="flex items-center justify-center py-4 text-[var(--ink-muted)]">
          <Loader2 size={14} className="mr-2 animate-spin" />
          <span className="text-[12px]">loading backtest…</span>
        </CardBody>
      </Card>
    );
  }
  if (missing) return null; // skill not predictive — silent
  if (err || !pred) {
    return (
      <Card className="mt-3">
        <CardBody className="py-3 text-[11px] text-[var(--loss)]">
          backtest unavailable: {err ?? "no data"}
        </CardBody>
      </Card>
    );
  }

  const actionTone =
    pred.action === "BUY" ? "gain" : pred.action === "AVOID" ? "loss" : "neutral";
  const stockUp = pred.stock_pct != null && pred.stock_pct >= 0;
  const elapsedDays = Math.max(0, (Date.now() / 1000 - pred.t0) / 86400);

  return (
    <Card className="mt-3">
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="font-mono text-[9px] tracking-[0.18em] uppercase text-[var(--ink-faint)]">
            market backtest
          </div>
          <div className="inline-flex items-center gap-1 rounded-full bg-[color-mix(in_srgb,var(--gain)_12%,transparent)] px-2 py-[1px] text-[10px] font-mono font-semibold text-[var(--gain)]">
            <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-[var(--gain)]" />
            live
          </div>
        </div>
      </CardHeader>

      <CardBody className="space-y-4">
        {/* Header — ticker + action */}
        <div className="flex items-baseline gap-3">
          <span className="font-display italic text-[26px] text-[var(--ink)]">
            {pred.ticker}
          </span>
          <div className="flex flex-col gap-[1px]">
            <Badge tone={actionTone}>
              {pred.action} · conv {pred.conviction.toFixed(2)}
            </Badge>
            <span className="font-mono text-[10px] text-[var(--ink-faint)]">
              predicted {formatRelative(pred.t0)}
            </span>
          </div>
        </div>

        {/* Entry → Now gauge */}
        <div className="rounded-[var(--r-lg)] border border-[var(--line)] p-3">
          <div className="mb-1 font-mono text-[10px] uppercase tracking-[0.1em] text-[var(--ink-muted)]">
            entry → now ({formatElapsed(elapsedDays)})
          </div>
          <div className="flex items-baseline gap-2">
            <span className="numeric text-[24px] font-semibold text-[var(--ink)]">
              {pred.now_price != null ? `$${pred.now_price.toFixed(2)}` : "—"}
            </span>
            {pred.stock_pct != null ? (
              <span
                className={`inline-flex items-center gap-[2px] numeric text-[13px] font-semibold ${
                  stockUp ? "text-[var(--gain)]" : "text-[var(--loss)]"
                }`}
              >
                {stockUp ? <TrendingUp size={12} /> : <TrendingDown size={12} />}
                {stockUp ? "+" : ""}
                {pred.stock_pct.toFixed(2)}%
              </span>
            ) : null}
          </div>
          <div className="mt-1 font-mono text-[10px] text-[var(--ink-muted)]">
            entry{" "}
            {pred.t0_price != null ? `$${pred.t0_price.toFixed(2)}` : "(unavailable)"} ·{" "}
            {formatDate(pred.t0)}
          </div>

          {pred.spy_now_price != null ? (
            <div className="mt-3 flex items-center gap-3 border-t border-[var(--line-soft)] pt-2 text-[11px]">
              <div className="flex flex-col gap-[1px]">
                <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-[var(--ink-faint)]">
                  vs SPY
                </span>
                <span className="text-[var(--ink-muted)]">
                  SPY now ${pred.spy_now_price.toFixed(2)}
                </span>
              </div>
              <div className="ml-auto flex flex-col items-end gap-[1px]">
                <span className="font-mono text-[9px] uppercase tracking-[0.1em] text-[var(--ink-faint)]">
                  action verdict
                </span>
                {pred.action === "WATCH" ? (
                  <span className="text-[10px] text-[var(--ink-muted)]">
                    WATCH ≠ hit/miss (D1)
                  </span>
                ) : (
                  <span className="text-[10px] text-[var(--ink-muted)]">
                    matures at horizons
                  </span>
                )}
              </div>
            </div>
          ) : null}
        </div>

        {/* Horizon countdowns */}
        <div>
          <div className="mb-2 font-mono text-[10px] uppercase tracking-[0.1em] text-[var(--ink-faint)]">
            scoring horizons
          </div>
          <div className="space-y-2">
            {pred.horizons.map((h) => {
              const totalDays = h.horizon_days;
              const elapsed = totalDays - h.days_remaining;
              const pct = Math.max(0, Math.min(100, (elapsed / totalDays) * 100));
              const matured = h.outcome != null;
              return (
                <div
                  key={h.horizon_days}
                  className="grid grid-cols-[40px_1fr_72px] items-center gap-2"
                >
                  <span className="font-mono text-[11px] text-[var(--ink-muted)]">
                    {h.horizon_days}d
                  </span>
                  <div className="h-1.5 overflow-hidden rounded-full bg-[var(--canvas-soft)]">
                    <div
                      className="h-full bg-[var(--accent)] transition-all"
                      style={{ width: `${pct}%` }}
                    />
                  </div>
                  <span className="text-right font-mono text-[10px] text-[var(--ink-muted)]">
                    {matured
                      ? `${h.outcome?.hit ? "✓" : "✗"} ${formatPct(h.outcome?.stock_pct)}`
                      : `${Math.ceil(h.days_remaining)}d left`}
                  </span>
                </div>
              );
            })}
          </div>
        </div>

        <div className="flex items-center gap-1 text-[10px] text-[var(--ink-faint)]">
          <Activity size={10} />
          <span>
            scoring cron arrives in PR ε.2 — bars fill, horizons mark hit/miss
          </span>
        </div>
      </CardBody>
    </Card>
  );
}

function formatPct(p: number | null | undefined): string {
  if (p == null) return "";
  return `${p >= 0 ? "+" : ""}${p.toFixed(1)}%`;
}
function formatDate(epoch: number): string {
  return new Date(epoch * 1000).toLocaleDateString("zh-CN");
}
function formatRelative(epoch: number): string {
  const sec = Date.now() / 1000 - epoch;
  if (sec < 60) return `${sec | 0}s ago`;
  if (sec < 3600) return `${(sec / 60) | 0}min ago`;
  if (sec < 86400) return `${(sec / 3600) | 0}h ago`;
  return `${(sec / 86400) | 0}d ago`;
}
function formatElapsed(days: number): string {
  if (days < 1) {
    const h = days * 24;
    if (h < 1) return `${(h * 60) | 0}m`;
    return `${h.toFixed(1)}h`;
  }
  return `${days.toFixed(1)}d`;
}
