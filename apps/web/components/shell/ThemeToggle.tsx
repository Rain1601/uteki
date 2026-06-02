"use client";

import { Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";

const STORAGE_KEY = "uteki-theme";

/**
 * Day/Night toggle for the 雨檐 theme.
 *
 * Dark is the default — written into the `:root { ... }` block of globals.css.
 * Setting `data-theme="light"` on <html> flips into the light override block.
 * Choice persists in localStorage so subsequent visits / refreshes stay put.
 *
 * The initial paint is handled by an inline script in `app/layout.tsx` that
 * runs before React hydrates — this component just keeps the in-memory state
 * in sync with what the script set, and handles user clicks afterwards.
 */
export function ThemeToggle() {
  const [theme, setTheme] = useState<"dark" | "light">("dark");

  useEffect(() => {
    const current = document.documentElement.getAttribute("data-theme");
    setTheme(current === "light" ? "light" : "dark");
  }, []);

  function toggle() {
    const next = theme === "dark" ? "light" : "dark";
    setTheme(next);
    if (next === "light") {
      document.documentElement.setAttribute("data-theme", "light");
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // localStorage may be unavailable (Safari private, embedded contexts);
      // toggle still works for the current page, just won't persist.
    }
  }

  // Icon shows what you'll switch TO, not what you're in — matches the label.
  const Icon = theme === "dark" ? Sun : Moon;
  const label = theme === "dark" ? "Day" : "Night";

  return (
    <button
      onClick={toggle}
      className={cn(
        "group/btn flex h-9 w-full items-center gap-3 rounded-md px-[14px]",
        "text-[var(--ink-muted)] hover:text-[var(--ink)]",
        "hover:bg-[var(--surface-hover)] transition-colors",
      )}
      aria-label={`Switch to ${label} mode`}
    >
      <Icon size={16} strokeWidth={1.75} />
      <span
        className={cn(
          "font-mono text-[10px] tracking-[0.14em] uppercase whitespace-nowrap",
          "opacity-0 group-hover/sidebar:opacity-100 transition-opacity duration-200 delay-75",
          "group-data-[pinned=true]/sidebar:opacity-100",
        )}
      >
        {label}
      </span>
    </button>
  );
}
