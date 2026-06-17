"use client";

import { useEffect, useState } from "react";
import {
  ChevronDown,
  ChevronUp,
  Flag,
  Loader2,
  ThumbsDown,
  ThumbsUp,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { canAnnotateRuns, type AuthUser } from "@/lib/auth";
import {
  getRunFeedback,
  setRunFeedback,
  type RunFeedback,
  type RunScoreBreakdown,
} from "@/lib/api";
import { cn } from "@/lib/cn";

/**
 * RunRatingPanel — annotator's run-quality UI for 013.
 *
 * Two halves on one card:
 *
 *   1. YOUR — 👍/👎 toggle + notes + 🚩 flag. POSTs to
 *      ``/api/runs/{id}/feedback`` which upserts a per-(user, run) row.
 *   2. AUTO — the LLM judge + cost-discipline aggregate, ONLY rendered
 *      after the user has submitted feedback. The server enforces this
 *      by masking the score fields to null on GET until a feedback row
 *      exists, so we just respect what we receive.
 *
 * Visibility:
 *
 *   - Hidden entirely for callers without ``runs:annotate`` (reader role).
 *   - Default collapsed for annotators — the panel sits in the page
 *     without screaming for attention; click the header to open.
 *
 * Why reveal-after-label matters (per 013 design):
 *
 *   If the annotator sees the judge's score before they label, the
 *   calibration set degrades into "do I agree with the model" rather
 *   than "is this run actually good". So the AUTO half stays empty on
 *   first paint and only fills in on submit.
 */
export function RunRatingPanel({
  runId,
  user,
}: {
  runId: string;
  user: AuthUser | null;
}) {
  const allowed = canAnnotateRuns(user);

  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<RunFeedback | null>(null);
  const [draftNotes, setDraftNotes] = useState("");
  const [draftFlagged, setDraftFlagged] = useState(false);

  // Lazy-fetch the current row only after the user opens the panel —
  // there's no value in spending bandwidth on it during initial page
  // paint when annotators rarely open every run they look at.
  useEffect(() => {
    if (!open || !allowed) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getRunFeedback(runId)
      .then((data) => {
        if (cancelled) return;
        setFeedback(data);
        setDraftNotes(data.notes || "");
        setDraftFlagged(Boolean(data.flagged));
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "load failed");
      })
      .finally(() => {
        if (cancelled) return;
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [open, allowed, runId]);

  if (!allowed) return null;

  const hasLabel = Boolean(feedback?.rating);
  const ratingNow = feedback?.rating || "";

  async function submit(nextRating: "up" | "down") {
    if (!allowed) return;
    setSaving(true);
    setError(null);
    try {
      const next = await setRunFeedback(runId, {
        rating: nextRating,
        notes: draftNotes,
        flagged: draftFlagged,
      });
      setFeedback(next);
    } catch (e) {
      setError(e instanceof Error ? e.message : "save failed");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Card className="mb-6 overflow-hidden">
      <CardHeader>
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="-mx-2 -my-1.5 flex w-full items-center gap-3 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-[var(--surface-hover)]"
        >
          <div className="eyebrow">QUALITY · 013 EVAL</div>
          {hasLabel && (
            <Badge tone={ratingNow === "up" ? "gain" : "loss"}>
              you said {ratingNow === "up" ? "👍" : "👎"}
            </Badge>
          )}
          {feedback?.flagged && (
            <Badge tone="warn">
              <Flag size={10} /> flagged
            </Badge>
          )}
          <span className="ml-auto text-[var(--ink-muted)]">
            {open ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </span>
        </button>
      </CardHeader>

      {open && (
        <CardBody className="space-y-5">
          {loading && (
            <div className="flex items-center gap-2 text-[12px] text-[var(--ink-muted)]">
              <Loader2 size={14} className="animate-spin" />
              loading…
            </div>
          )}

          {error && (
            <div className="border border-[color-mix(in_srgb,var(--loss)_40%,transparent)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)] px-3 py-2 font-mono text-[11px] text-[var(--loss)]">
              {error}
            </div>
          )}

          {!loading && feedback && (
            <>
              {/* YOUR — labelling controls */}
              <div className="space-y-3">
                <div className="font-mono text-[10px] tracking-[0.18em] text-[var(--ink-faint)]">
                  YOUR LABEL
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <RatingButton
                    icon={<ThumbsUp size={13} />}
                    label="好"
                    tone="gain"
                    active={ratingNow === "up"}
                    onClick={() => void submit("up")}
                    disabled={saving}
                  />
                  <RatingButton
                    icon={<ThumbsDown size={13} />}
                    label="差"
                    tone="loss"
                    active={ratingNow === "down"}
                    onClick={() => void submit("down")}
                    disabled={saving}
                  />
                  <button
                    type="button"
                    onClick={() => setDraftFlagged((v) => !v)}
                    disabled={saving}
                    className={cn(
                      "inline-flex h-9 items-center gap-1 rounded-md border px-2.5 font-mono text-[11px] tracking-[0.04em] transition-colors",
                      draftFlagged
                        ? "border-[color-mix(in_srgb,var(--warn)_60%,transparent)] bg-[color-mix(in_srgb,var(--warn)_10%,transparent)] text-[var(--warn)]"
                        : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink-soft)]",
                      saving && "opacity-50",
                    )}
                    title="标记为需要重审"
                  >
                    <Flag size={11} />
                    {draftFlagged ? "已标记 re-review" : "标记 re-review"}
                  </button>
                  {saving && <Loader2 size={12} className="animate-spin text-[var(--ink-muted)]" />}
                </div>

                <textarea
                  value={draftNotes}
                  onChange={(e) => setDraftNotes(e.target.value)}
                  rows={2}
                  placeholder="为什么这么标?(可选)— 帮 calibration 时回忆当时的想法"
                  className="w-full resize-y rounded-md border border-[var(--line)] bg-[var(--surface)] px-3 py-2 text-[12px] text-[var(--ink-soft)] placeholder-[var(--ink-faint)] outline-none focus:border-[var(--accent-line)]"
                  disabled={saving}
                />

                {/* Save notes only — the rating buttons above already
                    submit on click, but notes need an explicit confirm. */}
                <div className="flex items-center gap-2 text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
                  <Button
                    variant="ghost"
                    onClick={() =>
                      ratingNow ? void submit(ratingNow as "up" | "down") : undefined
                    }
                    disabled={saving || !ratingNow}
                  >
                    保存 notes + 标记
                  </Button>
                  <span className="font-mono">
                    {ratingNow
                      ? `last saved ${formatLocal(feedback.updated_at)}`
                      : "先选 👍 或 👎,系统会同时保存 notes 和 flag"}
                  </span>
                </div>
              </div>

              {/* AUTO — only after you've labelled */}
              <div className="border-t border-[var(--line)] pt-4">
                <div className="mb-2 font-mono text-[10px] tracking-[0.18em] text-[var(--ink-faint)]">
                  AUTO (judge) · 标完后显示
                </div>
                {hasLabel ? (
                  <AutoScoreReadout
                    score={feedback.auto_score ?? null}
                    breakdown={feedback.score_breakdown ?? null}
                  />
                ) : (
                  <p className="text-[11px] leading-relaxed text-[var(--ink-muted)]">
                    自动评分被服务器隐藏到你标完为止 — 这是 013 design 的反污染设计:
                    先看模型分数会带偏 calibration。先按 👍 或 👎,马上就显示。
                  </p>
                )}
              </div>
            </>
          )}
        </CardBody>
      )}
    </Card>
  );
}

function RatingButton({
  icon,
  label,
  tone,
  active,
  onClick,
  disabled,
}: {
  icon: React.ReactNode;
  label: string;
  tone: "gain" | "loss";
  active: boolean;
  onClick: () => void;
  disabled: boolean;
}) {
  const activeCls =
    tone === "gain"
      ? "border-[color-mix(in_srgb,var(--gain)_50%,transparent)] bg-[color-mix(in_srgb,var(--gain)_10%,transparent)] text-[var(--gain)]"
      : "border-[color-mix(in_srgb,var(--loss)_50%,transparent)] bg-[color-mix(in_srgb,var(--loss)_10%,transparent)] text-[var(--loss)]";
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={cn(
        "inline-flex h-9 items-center gap-1.5 rounded-md border px-3 font-display text-[13px] italic transition-colors",
        active
          ? activeCls
          : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink-soft)]",
        disabled && "opacity-50",
      )}
    >
      {icon}
      {label}
    </button>
  );
}

function AutoScoreReadout({
  score,
  breakdown,
}: {
  score: number | null;
  breakdown: RunScoreBreakdown | null;
}) {
  if (score === null && !breakdown) {
    return (
      <p className="text-[11px] leading-relaxed text-[var(--ink-muted)]">
        judge 还没跑过这个 run — 可能是 ``UTEKI_RUN_EVAL_ENABLED=false``,或者
        skill 不在 judge target 名单里,或者 run 是 mock-LLM 测试。
      </p>
    );
  }
  return (
    <div className="space-y-2">
      <div className="flex items-baseline gap-3">
        <span className="numeric font-display text-[28px] italic leading-none text-[var(--ink)]">
          {score !== null && score !== undefined ? score.toFixed(1) : "—"}
        </span>
        <span className="font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
          / 5  · 1-5 aggregate
        </span>
      </div>
      <div className="flex flex-wrap gap-2 text-[11px] text-[var(--ink-soft)]">
        {breakdown?.outcome != null && (
          <AxisChip label="outcome" value={breakdown.outcome} max={10} />
        )}
        {breakdown?.cost != null && (
          <AxisChip label="cost" value={breakdown.cost} max={5} />
        )}
        {breakdown &&
          Object.entries(breakdown)
            .filter(([k, v]) => v != null && k !== "outcome" && k !== "cost")
            .map(([k, v]) => (
              <AxisChip key={k} label={k} value={v as number} max={5} />
            ))}
      </div>
    </div>
  );
}

function AxisChip({
  label,
  value,
  max,
}: {
  label: string;
  value: number;
  max: number;
}) {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-md border border-[var(--line)] bg-[var(--surface)] px-2 py-1 font-mono text-[10px] tracking-[0.04em]">
      <span className="text-[var(--ink-muted)]">{label}</span>
      <span className="numeric text-[var(--ink)]">{value.toFixed(1)}</span>
      <span className="text-[var(--ink-faint)]">/ {max}</span>
    </span>
  );
}

function formatLocal(iso: string): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}
