"use client";

import { useState } from "react";
import type { AgentEvent } from "@/lib/types";
import { Wrench, ChevronDown, ChevronRight, Loader2 } from "lucide-react";

export function ToolCallCard({
  call,
  result,
}: {
  call: AgentEvent;
  result?: AgentEvent;
}) {
  const [open, setOpen] = useState(false);
  const name = String(call.data.name ?? "");
  const args = call.data.args ?? {};
  const ok = result ? (result.data.ok as boolean) : undefined;
  const summary = result ? String(result.data.summary ?? result.data.error ?? "") : "";
  const preview = result?.data.preview;

  const tone = result == null ? "pending" : ok ? "ok" : "fail";
  const tones: Record<string, string> = {
    pending: "border-[color-mix(in_srgb,var(--warn)_40%,transparent)] bg-[color-mix(in_srgb,var(--warn)_5%,transparent)]",
    ok:      "border-[color-mix(in_srgb,var(--gain)_40%,transparent)] bg-[color-mix(in_srgb,var(--gain)_5%,transparent)]",
    fail:    "border-[color-mix(in_srgb,var(--loss)_40%,transparent)] bg-[color-mix(in_srgb,var(--loss)_5%,transparent)]",
  };
  const accent: Record<string, string> = {
    pending: "text-[var(--warn)]",
    ok:      "text-[var(--gain)]",
    fail:    "text-[var(--loss)]",
  };

  return (
    <div className={`rounded-[var(--r)] border p-3 ${tones[tone]}`}>
      <div className="flex items-center gap-2">
        <Wrench size={13} className={accent[tone]} />
        <span className="font-mono text-[12px] font-medium text-[var(--ink)]">{name}</span>
        <span className="ml-auto flex items-center gap-1.5">
          {tone === "pending" && (
            <>
              <Loader2 size={12} className="animate-spin text-[var(--warn)]" />
              <span className="font-mono text-[10px] text-[var(--warn)]">pending</span>
            </>
          )}
          {tone === "ok" && (
            <span className="font-mono text-[10px] text-[var(--gain)]">✓ ok</span>
          )}
          {tone === "fail" && (
            <span className="font-mono text-[10px] text-[var(--loss)]">✗ fail</span>
          )}
        </span>
      </div>
      <div className="mt-1.5 truncate font-mono text-[10px] text-[var(--ink-muted)]">
        args = {JSON.stringify(args)}
      </div>
      {summary && (
        <div className="mt-1.5 text-[12px] text-[var(--ink-soft)]">{summary}</div>
      )}
      {preview != null && (
        <div className="mt-2">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.08em] text-[var(--ink-muted)] hover:text-[var(--ink)]"
          >
            {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />} preview
          </button>
          {open && (
            <pre className="mt-1.5 max-h-40 overflow-auto rounded-sm bg-[var(--surface)] p-2 font-mono text-[10px] leading-relaxed text-[var(--ink-muted)]">
              {JSON.stringify(preview, null, 2)}
            </pre>
          )}
        </div>
      )}
    </div>
  );
}
