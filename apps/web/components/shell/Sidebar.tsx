"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  LayoutDashboard,
  CalendarClock,
  Activity,
  GitCompareArrows,
  ClipboardCheck,
  Boxes,
  Building2,
  Pin,
  PinOff,
  Users,
  Tags,
} from "lucide-react";
import { cn } from "@/lib/cn";
import { canAdmin, canOperate, type AuthUser } from "@/lib/auth";
import { ThemeToggle } from "./ThemeToggle";
import { UserMenu } from "./UserMenu";

type NavItem = {
  href: string;
  label: string;
  icon: React.ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
  badge?: string;
  requiresAdmin?: boolean;
};

type NavSection = {
  label: string;
  items: NavItem[];
  /** Strict gate. Section hidden entirely unless predicate holds.
   *  Used for the Admin section so non-admins don't even see the label. */
  gate?: "admin";
};

const SECTIONS: NavSection[] = [
  {
    label: "Workspace",
    items: [
      { href: "/", label: "Overview", icon: LayoutDashboard },
      { href: "/company-agent", label: "研究台", icon: Building2 },
      { href: "/tasks", label: "触发器", icon: CalendarClock },
    ],
  },
  {
    label: "Engine",
    items: [
      { href: "/runs", label: "Runs", icon: Activity },
      { href: "/compare", label: "Compare", icon: GitCompareArrows, requiresAdmin: true },
      { href: "/evals", label: "Evals", icon: ClipboardCheck, requiresAdmin: true },
    ],
  },
  {
    label: "Catalog",
    items: [
      { href: "/agents", label: "Skills", icon: Boxes },
    ],
  },
  {
    label: "Admin",
    gate: "admin",
    items: [
      { href: "/admin/users", label: "用户", icon: Users },
      { href: "/admin/tags", label: "标签", icon: Tags },
      { href: "/admin/companies", label: "公司", icon: Building2 },
    ],
  },
];

export function Sidebar({
  pinned,
  onTogglePin,
  user,
}: {
  pinned: boolean;
  onTogglePin: () => void;
  user: AuthUser;
}) {
  const pathname = usePathname();
  const canUseOperations = canOperate(user);
  const isAdmin = canAdmin(user);

  return (
    <aside
      className={cn(
        "group/sidebar fixed inset-y-0 left-0 z-40",
        "bg-[var(--surface)] paper-grain",
        "border-r border-[var(--line)]",
        "flex flex-col",
        "transition-[width] duration-[280ms]",
      )}
      style={{
        width: pinned ? "var(--sidebar-w-expanded)" : "var(--sidebar-w-collapsed)",
        transitionTimingFunction: "var(--ease)",
      }}
      data-pinned={pinned}
      onMouseEnter={(e) => {
        if (!pinned) {
          (e.currentTarget as HTMLElement).style.width = "var(--sidebar-w-expanded)";
        }
      }}
      onMouseLeave={(e) => {
        if (!pinned) {
          (e.currentTarget as HTMLElement).style.width = "var(--sidebar-w-collapsed)";
        }
      }}
    >
      {/* Brand */}
      <div className="flex h-[var(--topbar-h)] items-center gap-3 px-[18px] border-b border-[var(--line)]">
        <div className="relative flex h-7 w-7 shrink-0 items-center justify-center">
          <div className="absolute inset-0 rounded-md bg-[var(--accent)] opacity-90" />
          <div className="relative font-display text-[15px] italic font-medium text-[#1a1410] tracking-tight">
            u
          </div>
        </div>
        <div className="overflow-hidden">
          <div className="font-display italic text-[17px] tracking-tight text-[var(--ink)] whitespace-nowrap">
            uteki
          </div>
          <div className="-mt-1 font-mono text-[9px] tracking-[0.18em] uppercase text-[var(--ink-faint)] whitespace-nowrap">
            research agent
          </div>
        </div>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto overflow-x-hidden py-3">
        {SECTIONS.filter((section) => !section.gate || (section.gate === "admin" && isAdmin)).map((section) => (
          <div key={section.label} className="mb-1.5">
            <SectionLabel label={section.label} />
            <ul className="space-y-[1px] px-2">
              {section.items
                .filter((item) => canUseOperations || !item.requiresAdmin)
                .map((item) => {
                  const active = isActive(pathname, item.href);
                  return (
                    <li key={item.href}>
                      <NavLink item={item} active={active} />
                    </li>
                  );
                })}
            </ul>
          </div>
        ))}
      </nav>

      {/* Footer */}
      <div className="border-t border-[var(--line)] px-2 py-2 space-y-1">
        <UserMenu user={user} />
        <ThemeToggle />
        <button
          onClick={onTogglePin}
          className={cn(
            "group/btn flex h-9 w-full items-center gap-3 rounded-md px-[14px]",
            "text-[var(--ink-muted)] hover:text-[var(--ink)]",
            "hover:bg-[var(--surface-hover)] transition-colors",
          )}
          aria-label={pinned ? "Unpin sidebar" : "Pin sidebar"}
        >
          {pinned ? <PinOff size={16} strokeWidth={1.75} /> : <Pin size={16} strokeWidth={1.75} />}
          <span
            className={cn(
              "font-mono text-[10px] tracking-[0.14em] uppercase whitespace-nowrap",
              "opacity-0 group-hover/sidebar:opacity-100 transition-opacity duration-200 delay-75",
              "group-data-[pinned=true]/sidebar:opacity-100",
            )}
          >
            {pinned ? "Unpin" : "Pin"}
          </span>
          <span className="ml-auto h-2 w-2 rounded-full bg-[var(--gain)] shadow-[0_0_8px_var(--gain)]" />
        </button>
      </div>
    </aside>
  );
}

function SectionLabel({ label }: { label: string }) {
  return (
    <div
      className={cn(
        "px-[22px] pb-1.5 pt-3",
        "font-mono text-[9px] font-semibold tracking-[0.18em] uppercase",
        "text-[var(--ink-faint)] whitespace-nowrap",
        "opacity-0 group-hover/sidebar:opacity-100 transition-opacity duration-200 delay-75",
        "group-data-[pinned=true]/sidebar:opacity-100",
      )}
    >
      {label}
    </div>
  );
}

function NavLink({ item, active }: { item: NavItem; active: boolean }) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      className={cn(
        "relative flex h-10 items-center gap-3 rounded-md px-[14px]",
        "transition-colors duration-150",
        active
          ? "bg-[var(--surface-active)] text-[var(--ink)]"
          : "text-[var(--ink-muted)] hover:text-[var(--ink-soft)] hover:bg-[var(--surface-hover)]",
      )}
    >
      {/* Active bar — left edge */}
      {active && (
        <span
          aria-hidden
          className="absolute left-0 top-1/2 h-5 w-[2px] -translate-y-1/2 rounded-r-full bg-[var(--accent)]"
        />
      )}
      <Icon
        size={18}
        strokeWidth={active ? 2 : 1.75}
        className={cn(
          "shrink-0 transition-colors",
          active ? "text-[var(--accent)]" : "text-current",
        )}
      />
      <span
        className={cn(
          "font-display italic text-[14px] tracking-tight whitespace-nowrap",
          active ? "font-medium" : "font-normal",
          "opacity-0 group-hover/sidebar:opacity-100 transition-opacity duration-200 delay-75",
          "group-data-[pinned=true]/sidebar:opacity-100",
        )}
      >
        {item.label}
      </span>
      {item.badge && (
        <span
          className={cn(
            "ml-auto font-mono text-[8px] font-semibold tracking-[0.14em]",
            "rounded-sm border border-[var(--line-strong)] px-1 py-[1px]",
            "text-[var(--ink-faint)]",
            "opacity-0 group-hover/sidebar:opacity-100 transition-opacity duration-200 delay-75",
            "group-data-[pinned=true]/sidebar:opacity-100",
          )}
        >
          {item.badge}
        </span>
      )}
    </Link>
  );
}

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(href + "/");
}
