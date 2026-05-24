"use client";

import { Sparkles } from "lucide-react";

export function PlanCard({ steps }: { steps: string[] }) {
  return (
    <div className="rounded-[var(--r-lg)] border border-[var(--accent-line)] bg-[var(--accent-soft)] p-4">
      <div className="mb-3 flex items-center gap-2">
        <Sparkles size={14} className="text-[var(--accent)]" />
        <span className="font-mono text-[9px] tracking-[0.18em] uppercase text-[var(--accent)]">
          Plan
        </span>
      </div>
      <ol className="space-y-1.5">
        {steps.map((s, i) => (
          <li key={i} className="flex gap-3">
            <span className="numeric w-6 shrink-0 text-[12px] text-[var(--ink-faint)]">
              {String(i + 1).padStart(2, "0")}
            </span>
            <span className="font-display italic text-[14px] text-[var(--ink)]">{s}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
