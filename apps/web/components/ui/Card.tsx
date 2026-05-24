import { cn } from "@/lib/cn";

export function Card({
  children,
  className,
  as: As = "div",
}: {
  children: React.ReactNode;
  className?: string;
  as?: "div" | "article" | "section";
}) {
  return (
    <As
      className={cn(
        "rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface-1)]",
        "transition-colors",
        className,
      )}
    >
      {children}
    </As>
  );
}

export function CardHeader({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("border-b border-[var(--line)] px-5 py-4", className)}>{children}</div>
  );
}

export function CardBody({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <div className={cn("px-5 py-4", className)}>{children}</div>;
}
