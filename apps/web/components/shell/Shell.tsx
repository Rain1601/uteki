"use client";

import { useState } from "react";
import { Sidebar } from "./Sidebar";
import type { AuthUser } from "@/lib/auth";

/**
 * App shell — fixed sidebar (hover-expands) + flexible main area.
 * The sidebar manages its own hover-expand state via CSS group hover; this
 * component only provides the layout grid and exposes a pinned-expanded state
 * for keyboard / persistent users (future).
 */
export function Shell({
  children,
  user,
}: {
  children: React.ReactNode;
  user: AuthUser;
}) {
  const [pinned, setPinned] = useState(false);

  return (
    <div className="relative min-h-screen">
      <Sidebar
        pinned={pinned}
        onTogglePin={() => setPinned((v) => !v)}
        user={user}
      />
      <main
        className="min-h-screen transition-[padding] duration-300"
        style={{
          paddingLeft: pinned
            ? "var(--sidebar-w-expanded)"
            : "var(--sidebar-w-collapsed)",
        }}
      >
        {children}
      </main>
    </div>
  );
}
