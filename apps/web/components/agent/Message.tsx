"use client";

import { cn } from "@/lib/cn";

export function Message({
  role,
  content,
}: {
  role: "user" | "assistant";
  content: string;
}) {
  const isUser = role === "user";
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] whitespace-pre-wrap px-4 py-3 text-[14px] leading-relaxed",
          isUser
            ? "rounded-[var(--r-lg)] rounded-br-sm bg-[var(--accent-soft)] border border-[var(--accent-line)] text-[var(--ink)]"
            : "rounded-[var(--r-lg)] rounded-bl-sm border border-[var(--line)] bg-[var(--surface)] text-[var(--ink-soft)]",
        )}
      >
        {content || (
          <span className="text-[var(--ink-faint)]">
            <Cursor />
          </span>
        )}
      </div>
    </div>
  );
}

function Cursor() {
  return (
    <span
      aria-hidden
      className="inline-block h-3 w-[2px] translate-y-[2px] bg-[var(--accent)] animate-pulse"
    />
  );
}
