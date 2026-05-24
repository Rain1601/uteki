import { cn } from "@/lib/cn";

type Tone = "neutral" | "accent" | "gain" | "loss" | "warn";

export function Badge({
  children,
  tone = "neutral",
  className,
}: {
  children: React.ReactNode;
  tone?: Tone;
  className?: string;
}) {
  const toneStyles: Record<Tone, string> = {
    neutral: "border-[var(--line-strong)] text-[var(--ink-muted)]",
    accent: "border-[var(--accent-line)] text-[var(--accent)] bg-[var(--accent-soft)]",
    gain: "border-[color-mix(in_srgb,var(--gain)_40%,transparent)] text-[var(--gain)] bg-[color-mix(in_srgb,var(--gain)_10%,transparent)]",
    loss: "border-[color-mix(in_srgb,var(--loss)_40%,transparent)] text-[var(--loss)] bg-[color-mix(in_srgb,var(--loss)_10%,transparent)]",
    warn: "border-[color-mix(in_srgb,var(--warn)_40%,transparent)] text-[var(--warn)] bg-[color-mix(in_srgb,var(--warn)_10%,transparent)]",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm border px-1.5 py-[2px]",
        "font-mono text-[9px] font-semibold tracking-[0.14em] uppercase",
        toneStyles[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
