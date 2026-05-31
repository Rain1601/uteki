"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import { cn } from "@/lib/cn";
import { logout, type AuthUser } from "@/lib/auth";

/**
 * Footer pill: avatar + email (label hidden when sidebar is collapsed).
 * Clicking opens a tiny menu with sign-out. We position the menu absolutely
 * within the sidebar so it doesn't get clipped by the aside overflow.
 */
export function UserMenu({ user }: { user: AuthUser }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function onDoc(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", onDoc);
    return () => document.removeEventListener("mousedown", onDoc);
  }, [open]);

  async function onLogout() {
    setBusy(true);
    try {
      await logout();
    } finally {
      setBusy(false);
      setOpen(false);
      router.replace("/login");
    }
  }

  const initial = (user.display_name || user.email).slice(0, 1).toUpperCase();

  return (
    <div className="relative" ref={ref}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex h-10 w-full items-center gap-3 rounded-md px-[10px]",
          "text-[var(--ink-muted)] hover:text-[var(--ink)]",
          "hover:bg-[var(--surface-hover)] transition-colors",
        )}
        aria-label="account menu"
      >
        <div className="relative flex h-7 w-7 shrink-0 items-center justify-center overflow-hidden rounded-md bg-[var(--surface-active)]">
          {user.avatar_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={user.avatar_url}
              alt=""
              className="absolute inset-0 h-full w-full object-cover"
            />
          ) : (
            <span className="font-display italic text-[13px] text-[var(--ink)]">
              {initial}
            </span>
          )}
        </div>
        <div
          className={cn(
            "min-w-0 flex-1 text-left",
            "opacity-0 group-hover/sidebar:opacity-100 transition-opacity duration-200 delay-75",
            "group-data-[pinned=true]/sidebar:opacity-100",
          )}
        >
          <div className="truncate font-display italic text-[13px] leading-tight text-[var(--ink)]">
            {user.display_name || user.email.split("@")[0]}
          </div>
          <div className="truncate font-mono text-[9px] tracking-[0.05em] text-[var(--ink-faint)]">
            {user.role} · {user.email}
          </div>
        </div>
      </button>

      {open && (
        <div
          className={cn(
            "absolute bottom-[calc(100%+6px)] left-1 right-1 z-50",
            "rounded-md border border-[var(--line)] bg-[var(--surface)] shadow-lg",
            "py-1",
          )}
        >
          <button
            onClick={onLogout}
            disabled={busy}
            className={cn(
              "flex w-full items-center gap-2 px-3 py-2",
              "font-mono text-[11px] tracking-[0.05em] text-[var(--ink-muted)]",
              "hover:text-[var(--loss)] hover:bg-[var(--surface-hover)]",
              "disabled:opacity-50",
            )}
          >
            <LogOut size={13} strokeWidth={1.75} />
            <span>{busy ? "退出中…" : "Sign out"}</span>
          </button>
        </div>
      )}
    </div>
  );
}
