"use client";

import type { AgentInfo } from "@/lib/api";

export function SkillSelector({
  value,
  onChange,
  agents,
}: {
  value: string;
  onChange: (v: string) => void;
  agents: AgentInfo[];
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-md border border-[var(--line-strong)] bg-[var(--surface)] px-3 py-2 font-mono text-[12px] text-[var(--ink-soft)] hover:bg-[var(--surface-2)] focus:border-[var(--accent)] transition-colors"
    >
      {agents.length === 0 && <option value="">(no skills)</option>}
      {agents.map((a) => (
        <option key={a.name} value={a.name} className="bg-[var(--surface)]">
          {a.name} · {a.version}
        </option>
      ))}
    </select>
  );
}
