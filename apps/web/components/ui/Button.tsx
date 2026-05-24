import { cn } from "@/lib/cn";
import { forwardRef } from "react";

type Variant = "primary" | "ghost" | "outline";
type Size = "sm" | "md";

export const Button = forwardRef<
  HTMLButtonElement,
  React.ButtonHTMLAttributes<HTMLButtonElement> & {
    variant?: Variant;
    size?: Size;
  }
>(function Button(
  { variant = "outline", size = "md", className, children, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-2 font-mono tracking-[0.04em]",
        "rounded-md transition-all duration-150",
        "disabled:opacity-40 disabled:pointer-events-none",
        size === "sm" && "h-7 px-3 text-[11px]",
        size === "md" && "h-9 px-4 text-[12px]",
        variant === "primary" &&
          "bg-[var(--accent)] text-[#1a1410] hover:brightness-110 font-semibold",
        variant === "outline" &&
          "border border-[var(--line-strong)] text-[var(--ink-soft)] hover:text-[var(--ink)] hover:border-[var(--ink-muted)] hover:bg-[var(--surface-hover)]",
        variant === "ghost" &&
          "text-[var(--ink-muted)] hover:text-[var(--ink)] hover:bg-[var(--surface-hover)]",
        className,
      )}
      {...rest}
    >
      {children}
    </button>
  );
});
