"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Loader2 } from "lucide-react";
import { canAdmin, fetchMe, type AuthUser } from "@/lib/auth";
import { cn } from "@/lib/cn";

const TABS: { href: string; label: string }[] = [
  { href: "/admin/users", label: "用户" },
  { href: "/admin/tags", label: "标签" },
  { href: "/admin/companies", label: "公司" },
  { href: "/admin/earnings", label: "财报" },
  { href: "/admin/triggers", label: "触发器" },
];

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [me, setMe] = useState<AuthUser | null>(null);
  const [checked, setChecked] = useState(false);

  // Single auth gate at the layout level — children no longer need to
  // re-check; the layout redirects unauthorized users away before they
  // get to render.
  useEffect(() => {
    fetchMe().then((u) => {
      setMe(u);
      setChecked(true);
      if (!canAdmin(u)) router.replace("/");
    });
  }, [router]);

  if (!checked) {
    return (
      <div className="flex h-64 items-center justify-center text-[12px] text-[var(--ink-muted)]">
        <Loader2 size={14} className="mr-2 animate-spin" />
        loading…
      </div>
    );
  }
  if (!canAdmin(me)) return null;

  return (
    <div>
      <div className="sticky top-0 z-10 border-b border-[var(--line)] bg-[var(--canvas)]/95 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center gap-1 px-8 py-3">
          <span className="font-mono text-[9px] tracking-[0.18em] uppercase text-[var(--ink-faint)] mr-3">
            ADMIN
          </span>
          {TABS.map((tab) => {
            const active =
              pathname === tab.href || pathname.startsWith(tab.href + "/");
            return (
              <Link
                key={tab.href}
                href={tab.href}
                className={cn(
                  "relative rounded-sm px-3 py-1.5 font-display text-[14px] italic transition-colors",
                  active
                    ? "text-[var(--ink)]"
                    : "text-[var(--ink-muted)] hover:text-[var(--ink-soft)]",
                )}
              >
                {tab.label}
                {active && (
                  <span className="absolute inset-x-3 -bottom-px h-[2px] bg-[var(--accent)]" />
                )}
              </Link>
            );
          })}
        </div>
      </div>
      {children}
    </div>
  );
}
