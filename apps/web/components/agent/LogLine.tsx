"use client";

export function LogLine({
  level,
  message,
  extra,
}: {
  level: "info" | "warn" | "error";
  message: string;
  extra?: Record<string, unknown>;
}) {
  const color =
    level === "error"
      ? "var(--loss)"
      : level === "warn"
      ? "var(--warn)"
      : "var(--ink-faint)";
  return (
    <div className="font-mono text-[11px] leading-relaxed">
      <span
        className="mr-2 inline-block min-w-[3em] uppercase tracking-[0.12em]"
        style={{ color }}
      >
        [{level}]
      </span>
      <span className="text-[var(--ink-soft)]">{message}</span>
      {extra && Object.keys(extra).length > 0 && (
        <pre className="mt-1 overflow-x-auto text-[10px] text-[var(--ink-muted)]">
          {JSON.stringify(extra, null, 2)}
        </pre>
      )}
    </div>
  );
}
