import { cn } from "@/lib/cn";

export function PageHeader({
  eyebrow,
  title,
  subtitle,
  actions,
  className,
}: {
  eyebrow?: string;
  title: string;
  subtitle?: string;
  actions?: React.ReactNode;
  className?: string;
}) {
  return (
    <header className={cn("mb-10 flex items-end justify-between gap-6", className)}>
      <div>
        {eyebrow && <div className="eyebrow mb-3">{eyebrow}</div>}
        <h1 className="h-display text-[44px] text-[var(--ink)]">{title}</h1>
        {subtitle && (
          <p className="mt-3 max-w-2xl text-[15px] leading-relaxed text-[var(--ink-soft)]">
            {subtitle}
          </p>
        )}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </header>
  );
}

export function PageContainer({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mx-auto w-full max-w-6xl px-8 py-12", className)}>{children}</div>
  );
}
