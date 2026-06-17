"use client";

import { useEffect, useState } from "react";
import {
  Check,
  ChevronDown,
  ChevronUp,
  Eye,
  EyeOff,
  Flag,
  Loader2,
  Pencil,
  ThumbsDown,
  ThumbsUp,
  X,
} from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { canAnnotateRuns, type AuthUser } from "@/lib/auth";
import {
  getRunFeedback,
  setRunFeedback,
  type RatingMode,
  type RunFeedback,
  type RunScoreBreakdown,
} from "@/lib/api";
import { cn } from "@/lib/cn";

/**
 * 013 δ.1 — annotator surface with TWO modes:
 *
 *   • REVIEW (default) — the judge's score is shown immediately and the
 *     annotator's job is to accept / reject / edit it. Faster but the
 *     resulting feedback row is NOT calibration-grade (Phase 2's
 *     Cohen's-κ cron will drop these rows).
 *
 *   • BLIND — the auto-score is hidden until the annotator submits a
 *     rating. Use this for the initial 20-row calibration baseline so
 *     the labels aren't anchored by the judge's number.
 *
 * The mode toggle sits in the panel header. Switching modes after
 * opening the panel re-fetches with the new ``mode=`` intent so the
 * AUTO chip on the right reflects the right visibility rule.
 *
 * Reader visibility:
 * - Hidden entirely without ``runs:annotate``.
 * - Default collapsed even for annotators.
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
  const [mode, setMode] = useState<RatingMode>("review");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<RunFeedback | null>(null);
  const [draftNotes, setDraftNotes] = useState("");
  const [draftFlagged, setDraftFlagged] = useState(false);

  useEffect(() => {
    if (!open || !allowed) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    getRunFeedback(runId, mode)
      .then((data) => {
        if (cancelled) return;
        setFeedback(data);
        setDraftNotes(data.notes || "");
        setDraftFlagged(Boolean(data.flagged));
        // If the row already exists, prefer its stored mode over the
        // panel's current toggle — the stored mode wins on re-edit.
        if (data.rating) setMode(data.rating_mode);
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
  }, [open, allowed, runId, mode]);

  if (!allowed) return null;

  const hasLabel = Boolean(feedback?.rating);
  const ratingNow = feedback?.rating || "";
  const scoreVisible =
    feedback?.auto_score !== null && feedback?.auto_score !== undefined;

  async function submit(nextRating: "up" | "down") {
    if (!allowed) return;
    setSaving(true);
    setError(null);
    try {
      const next = await setRunFeedback(runId, {
        rating: nextRating,
        notes: draftNotes,
        flagged: draftFlagged,
        rating_mode: mode,
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
          {/* Mode toggle row */}
          <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--ink-muted)]">
            <span className="font-mono tracking-[0.06em]">MODE</span>
            <ModeChip
              icon={<Eye size={11} />}
              label="REVIEW"
              active={mode === "review"}
              disabled={hasLabel}
              onClick={() => setMode("review")}
              title={
                hasLabel
                  ? "已提交的 row 锁定其原 mode;新开 row 才能切换"
                  : "judge 先评分,你 [采纳] / [拒绝] / [编辑]"
              }
            />
            <ModeChip
              icon={<EyeOff size={11} />}
              label="BLIND"
              active={mode === "blind"}
              disabled={hasLabel}
              onClick={() => setMode("blind")}
              title={
                hasLabel
                  ? "已提交的 row 锁定其原 mode"
                  : "你先标,标完后才显示 judge 分(calibration baseline 用)"
              }
            />
            <span className="ml-auto font-mono tracking-[0.04em] text-[var(--ink-faint)]">
              {mode === "review"
                ? "用于日常 ·  judge 评 + 人审"
                : "用于 baseline · 盲标 → calibration"}
            </span>
          </div>

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
              {mode === "review" ? (
                <ReviewModePane
                  feedback={feedback}
                  scoreVisible={scoreVisible}
                  draftNotes={draftNotes}
                  setDraftNotes={setDraftNotes}
                  draftFlagged={draftFlagged}
                  setDraftFlagged={setDraftFlagged}
                  ratingNow={ratingNow}
                  saving={saving}
                  onSubmit={submit}
                />
              ) : (
                <BlindModePane
                  feedback={feedback}
                  draftNotes={draftNotes}
                  setDraftNotes={setDraftNotes}
                  draftFlagged={draftFlagged}
                  setDraftFlagged={setDraftFlagged}
                  ratingNow={ratingNow}
                  saving={saving}
                  onSubmit={submit}
                />
              )}
            </>
          )}
        </CardBody>
      )}
    </Card>
  );
}

// ─── Review-mode pane ───────────────────────────────────────────────

function ReviewModePane({
  feedback,
  scoreVisible,
  draftNotes,
  setDraftNotes,
  draftFlagged,
  setDraftFlagged,
  ratingNow,
  saving,
  onSubmit,
}: {
  feedback: RunFeedback;
  scoreVisible: boolean;
  draftNotes: string;
  setDraftNotes: (s: string) => void;
  draftFlagged: boolean;
  setDraftFlagged: (b: boolean) => void;
  ratingNow: string;
  saving: boolean;
  onSubmit: (rating: "up" | "down") => void;
}) {
  // Judge's verdict on a 1-10 outcome scale; we render the
  // dispatcher's accept/reject suggestion based on the outcome
  // rubric's pass threshold (7).
  const outcome = feedback.score_breakdown?.outcome ?? null;
  const judgeVerdict: "good" | "bad" | "unknown" =
    outcome === null || outcome === undefined
      ? "unknown"
      : outcome >= 7
        ? "good"
        : "bad";

  return (
    <>
      <div className="rounded-md border border-[var(--line)] bg-[var(--surface)] p-3">
        <div className="mb-2 font-mono text-[10px] tracking-[0.18em] text-[var(--ink-faint)]">
          AUTO (judge first)
        </div>
        {scoreVisible ? (
          <>
            <AutoScoreReadout
              score={feedback.auto_score ?? null}
              breakdown={feedback.score_breakdown ?? null}
            />
            <div className="mt-2 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-muted)]">
              judge 倾向: {judgeVerdict === "good" ? "👍 好" : judgeVerdict === "bad" ? "👎 差" : "不确定"}
            </div>
          </>
        ) : (
          <p className="text-[11px] leading-relaxed text-[var(--ink-muted)]">
            judge 还没跑过这个 run。把 mode 切到 BLIND 也可以现在自己标。
          </p>
        )}
      </div>

      <div className="space-y-3">
        <div className="font-mono text-[10px] tracking-[0.18em] text-[var(--ink-faint)]">
          YOUR DECISION
        </div>
        {scoreVisible && judgeVerdict !== "unknown" ? (
          <div className="flex flex-wrap items-center gap-2">
            <ReviewButton
              icon={<Check size={13} />}
              label={`采纳 ${judgeVerdict === "good" ? "👍" : "👎"}`}
              tone={judgeVerdict === "good" ? "gain" : "loss"}
              active={
                (ratingNow === "up" && judgeVerdict === "good") ||
                (ratingNow === "down" && judgeVerdict === "bad")
              }
              onClick={() => onSubmit(judgeVerdict === "good" ? "up" : "down")}
              disabled={saving}
            />
            <ReviewButton
              icon={<X size={13} />}
              label={`拒绝 → ${judgeVerdict === "good" ? "👎" : "👍"}`}
              tone={judgeVerdict === "good" ? "loss" : "gain"}
              active={
                (ratingNow === "down" && judgeVerdict === "good") ||
                (ratingNow === "up" && judgeVerdict === "bad")
              }
              onClick={() => onSubmit(judgeVerdict === "good" ? "down" : "up")}
              disabled={saving}
            />
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-2">
            <ReviewButton
              icon={<ThumbsUp size={13} />}
              label="好"
              tone="gain"
              active={ratingNow === "up"}
              onClick={() => onSubmit("up")}
              disabled={saving}
            />
            <ReviewButton
              icon={<ThumbsDown size={13} />}
              label="差"
              tone="loss"
              active={ratingNow === "down"}
              onClick={() => onSubmit("down")}
              disabled={saving}
            />
          </div>
        )}

        <div className="flex flex-wrap items-center gap-2 text-[11px] text-[var(--ink-muted)]">
          <FlagToggle
            on={draftFlagged}
            onToggle={() => setDraftFlagged(!draftFlagged)}
            saving={saving}
          />
          {saving && <Loader2 size={12} className="animate-spin text-[var(--ink-muted)]" />}
        </div>

        <textarea
          value={draftNotes}
          onChange={(e) => setDraftNotes(e.target.value)}
          rows={2}
          placeholder="编辑 · 你为什么这么决定?(可选)"
          className="w-full resize-y rounded-md border border-[var(--line)] bg-[var(--surface)] px-3 py-2 text-[12px] text-[var(--ink-soft)] placeholder-[var(--ink-faint)] outline-none focus:border-[var(--accent-line)]"
          disabled={saving}
        />

        <div className="flex items-center gap-2 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
          <Button
            variant="ghost"
            onClick={() =>
              ratingNow ? onSubmit(ratingNow as "up" | "down") : undefined
            }
            disabled={saving || !ratingNow}
          >
            <Pencil size={11} /> 保存 notes + 标记
          </Button>
          <span>
            {ratingNow
              ? `已存 · ${formatLocal(feedback.updated_at)} · mode=${feedback.rating_mode}`
              : "先点 采纳 / 拒绝,系统会同时保存 notes 和 flag"}
          </span>
        </div>
      </div>
    </>
  );
}

// ─── Blind-mode pane ────────────────────────────────────────────────

function BlindModePane({
  feedback,
  draftNotes,
  setDraftNotes,
  draftFlagged,
  setDraftFlagged,
  ratingNow,
  saving,
  onSubmit,
}: {
  feedback: RunFeedback;
  draftNotes: string;
  setDraftNotes: (s: string) => void;
  draftFlagged: boolean;
  setDraftFlagged: (b: boolean) => void;
  ratingNow: string;
  saving: boolean;
  onSubmit: (rating: "up" | "down") => void;
}) {
  const hasLabel = Boolean(ratingNow);
  const scoreVisible =
    feedback.auto_score !== null && feedback.auto_score !== undefined;

  return (
    <>
      <div className="space-y-3">
        <div className="font-mono text-[10px] tracking-[0.18em] text-[var(--ink-faint)]">
          YOUR LABEL · BLIND
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <RatingButton
            icon={<ThumbsUp size={13} />}
            label="好"
            tone="gain"
            active={ratingNow === "up"}
            onClick={() => onSubmit("up")}
            disabled={saving}
          />
          <RatingButton
            icon={<ThumbsDown size={13} />}
            label="差"
            tone="loss"
            active={ratingNow === "down"}
            onClick={() => onSubmit("down")}
            disabled={saving}
          />
          <FlagToggle
            on={draftFlagged}
            onToggle={() => setDraftFlagged(!draftFlagged)}
            saving={saving}
          />
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

        <div className="flex items-center gap-2 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
          <Button
            variant="ghost"
            onClick={() =>
              ratingNow ? onSubmit(ratingNow as "up" | "down") : undefined
            }
            disabled={saving || !ratingNow}
          >
            保存 notes + 标记
          </Button>
          <span>
            {ratingNow
              ? `已存 · ${formatLocal(feedback.updated_at)} · mode=${feedback.rating_mode}`
              : "先选 👍 或 👎,系统会同时保存 notes 和 flag"}
          </span>
        </div>
      </div>

      <div className="border-t border-[var(--line)] pt-4">
        <div className="mb-2 font-mono text-[10px] tracking-[0.18em] text-[var(--ink-faint)]">
          AUTO (judge) · BLIND 模式标完后显示
        </div>
        {hasLabel && scoreVisible ? (
          <AutoScoreReadout
            score={feedback.auto_score ?? null}
            breakdown={feedback.score_breakdown ?? null}
          />
        ) : (
          <p className="text-[11px] leading-relaxed text-[var(--ink-muted)]">
            BLIND 模式 — 自动评分被服务器隐藏到你标完为止,这是 013 design 的反污染设计。
            先按 👍 或 👎,马上就显示。
          </p>
        )}
      </div>
    </>
  );
}

// ─── Reusable bits ──────────────────────────────────────────────────

function ModeChip({
  icon,
  label,
  active,
  disabled,
  onClick,
  title,
}: {
  icon: React.ReactNode;
  label: string;
  active: boolean;
  disabled: boolean;
  onClick: () => void;
  title: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={cn(
        "inline-flex h-7 items-center gap-1 rounded-md border px-2 font-mono text-[10px] tracking-[0.04em] transition-colors",
        active
          ? "border-[var(--accent-line)] bg-[color-mix(in_srgb,var(--accent)_8%,transparent)] text-[var(--accent)]"
          : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink-soft)]",
        disabled && "opacity-60 cursor-not-allowed",
      )}
    >
      {icon}
      {label}
    </button>
  );
}

function FlagToggle({
  on,
  onToggle,
  saving,
}: {
  on: boolean;
  onToggle: () => void;
  saving: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onToggle}
      disabled={saving}
      className={cn(
        "inline-flex h-9 items-center gap-1 rounded-md border px-2.5 font-mono text-[11px] tracking-[0.04em] transition-colors",
        on
          ? "border-[color-mix(in_srgb,var(--warn)_60%,transparent)] bg-[color-mix(in_srgb,var(--warn)_10%,transparent)] text-[var(--warn)]"
          : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink-soft)]",
        saving && "opacity-50",
      )}
      title="标记为需要重审"
    >
      <Flag size={11} />
      {on ? "已标记 re-review" : "标记 re-review"}
    </button>
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

function ReviewButton({
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
  // Same visual language as RatingButton; semantic role differs (accept
  // / reject of the judge rather than independent up/down vote).
  return (
    <RatingButton
      icon={icon}
      label={label}
      tone={tone}
      active={active}
      onClick={onClick}
      disabled={disabled}
    />
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
