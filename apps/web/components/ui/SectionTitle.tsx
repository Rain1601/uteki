import { cn } from "@/lib/cn";

export function SectionTitle({
  eyebrow,
  title,
  className,
  trailing,
}: {
  eyebrow?: string;
  title: string;
  className?: string;
  trailing?: React.ReactNode;
}) {
  return (
    <div className={cn("mb-4 flex items-end justify-between", className)}>
      <div>
        {eyebrow && <div className="eyebrow mb-1.5">{eyebrow}</div>}
        <h2 className="font-display italic text-[22px] tracking-tight text-[var(--ink)]">
          {title}
        </h2>
      </div>
      {trailing}
    </div>
  );
}
