export function Empty({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center rounded-[var(--r-lg)] border border-dashed border-[var(--line)] bg-[var(--surface)]/40 px-8 py-16 text-center">
      <div className="h-display text-[24px] text-[var(--ink-soft)]">{title}</div>
      {hint && <p className="mt-2 max-w-md text-[13px] text-[var(--ink-muted)]">{hint}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  );
}
