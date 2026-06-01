"use client";

import type { AgentEvent } from "@/lib/types";
import { cn } from "@/lib/cn";
import {
  Play,
  CheckCircle2,
  Wrench,
  AlignLeft,
  Quote,
  AlertCircle,
  AlertOctagon,
  Activity,
  Sparkles,
  Gauge,
  CheckCheck,
  FileText,
  ChevronDown,
  ChevronUp,
  Brain,
} from "lucide-react";

export function Trace({ events }: { events: AgentEvent[] }) {
  if (events.length === 0) return null;

  // Walk events maintaining a depth counter so sub-agent (M6) blocks indent
  // visually. A `subagent_start` increases depth for subsequent events; the
  // matching `subagent_end` decreases it.
  let depth = 0;

  return (
    <ol className="relative space-y-3 pl-6">
      {/* vertical timeline rule */}
      <span
        aria-hidden
        className="absolute left-2 top-2 bottom-2 w-px bg-gradient-to-b from-transparent via-[var(--line)] to-transparent"
      />
      {events.map((ev, i) => {
        // Depth applies to the event itself for end markers (they sit at the
        // parent level), so handle end first. Start markers render at the
        // parent level and bump depth for *following* children.
        if (ev.type === "subagent_end" && depth > 0) {
          depth -= 1;
        }
        const renderDepth = depth;
        if (ev.type === "subagent_start") {
          depth += 1;
        }
        return (
          <li
            key={i}
            className="relative"
            style={{ marginLeft: renderDepth * 16 }}
          >
            <TimelineDot type={ev.type} />
            <TraceEvent ev={ev} />
          </li>
        );
      })}
    </ol>
  );
}

const dotConfig: Record<string, { color: string; size?: "sm" | "md" }> = {
  run_start:   { color: "var(--ink-muted)", size: "sm" },
  plan:        { color: "var(--accent)" },
  step_start:  { color: "var(--info)" },
  step_end:    { color: "var(--ink-muted)", size: "sm" },
  thinking:    { color: "var(--accent)" },
  tool_call:   { color: "var(--warn)" },
  tool_result: { color: "var(--gain)" },
  delta:       { color: "var(--ink-faint)", size: "sm" },
  citation:    { color: "var(--ink-muted)", size: "sm" },
  usage:       { color: "var(--ink-faint)", size: "sm" },
  log:         { color: "var(--ink-faint)", size: "sm" },
  artifact_written: { color: "var(--accent)" },
  await_review:     { color: "var(--warn)" },
  subagent_start:   { color: "var(--accent)" },
  subagent_end:     { color: "var(--ink-muted)", size: "sm" },
  error:       { color: "var(--loss)" },
  done:        { color: "var(--gain)" },
};

function TimelineDot({ type }: { type: string }) {
  const cfg = dotConfig[type] ?? dotConfig.run_start;
  const sz = cfg.size === "sm" ? 4 : 7;
  return (
    <span
      aria-hidden
      className="absolute -left-[18px] top-2 rounded-full ring-2 ring-[var(--surface-1)]"
      style={{
        width: sz,
        height: sz,
        background: cfg.color,
      }}
    />
  );
}

function TraceEvent({ ev }: { ev: AgentEvent }) {
  switch (ev.type) {
    case "run_start":
      return (
        <Row icon={Play} muted>
          <span className="font-mono text-[10px] tracking-[0.12em] uppercase text-[var(--ink-faint)]">
            run start
          </span>
          <span className="font-mono text-[11px] text-[var(--ink-muted)]">
            · agent={String(ev.data.agent ?? "?")}
          </span>
        </Row>
      );

    case "plan": {
      const steps = (ev.data.steps as string[]) ?? [];
      return (
        <div className="rounded-[var(--r)] border border-[var(--accent-line)] bg-[var(--accent-soft)] p-3">
          <div className="mb-2 flex items-center gap-2">
            <Sparkles size={13} className="text-[var(--accent)]" />
            <span className="font-mono text-[9px] tracking-[0.18em] uppercase text-[var(--accent)]">
              plan
            </span>
          </div>
          <ol className="space-y-1">
            {steps.map((s, i) => (
              <li key={i} className="flex gap-2 text-[13px] text-[var(--ink)]">
                <span className="numeric w-5 shrink-0 text-[var(--ink-faint)]">
                  {String(i + 1).padStart(2, "0")}
                </span>
                <span className="font-display italic">{s}</span>
              </li>
            ))}
          </ol>
        </div>
      );
    }

    case "step_start":
      return (
        <Row icon={Activity}>
          <span className="font-display italic text-[14px] text-[var(--ink)]">
            {String(ev.data.title ?? "step")}
          </span>
        </Row>
      );

    case "step_end":
      return (
        <Row icon={CheckCircle2} muted>
          <span className="font-mono text-[10px] tracking-[0.08em] uppercase text-[var(--ink-faint)]">
            step ok
          </span>
        </Row>
      );

    case "thinking":
      // Agent's internal voice — the *reasoning* behind whatever happens
      // next (tool call selection, section claim, key judgment). Per the
      // M1.x guardrails §6, skills should yield one of these before every
      // tool_call. Renders as a load-bearing quote, not as log noise.
      return (
        <div
          className={cn(
            "rounded-[var(--r)] border-l-[3px] border-[var(--accent)]",
            "bg-[color-mix(in_srgb,var(--accent)_4%,transparent)]",
            "py-2 pl-3 pr-3",
          )}
        >
          <div className="mb-1 flex items-center gap-2">
            <Brain
              size={12}
              className="shrink-0 text-[var(--accent)]"
              strokeWidth={1.75}
            />
            <span className="font-mono text-[9px] tracking-[0.18em] uppercase text-[var(--accent)]">
              thinking
            </span>
          </div>
          <div className="font-display italic text-[13px] leading-relaxed text-[var(--ink)]">
            {String(ev.data.text ?? "")}
          </div>
        </div>
      );

    case "tool_call":
      return (
        <div className="rounded-[var(--r)] border border-dashed border-[color-mix(in_srgb,var(--warn)_50%,transparent)] bg-[color-mix(in_srgb,var(--warn)_6%,transparent)] p-2.5">
          <div className="flex items-center gap-2">
            <Wrench size={13} className="text-[var(--warn)]" />
            <span className="font-mono text-[12px] font-medium text-[var(--warn)]">
              {String(ev.data.name ?? "")}
            </span>
            <span className="font-mono text-[10px] text-[var(--ink-faint)]">→ pending</span>
          </div>
          <div className="mt-1 truncate font-mono text-[10px] text-[var(--ink-muted)]">
            {JSON.stringify(ev.data.args ?? {})}
          </div>
        </div>
      );

    case "tool_result": {
      const ok = ev.data.ok as boolean;
      return (
        <div
          className={cn(
            "rounded-[var(--r)] border p-2.5",
            ok
              ? "border-[color-mix(in_srgb,var(--gain)_40%,transparent)] bg-[color-mix(in_srgb,var(--gain)_6%,transparent)]"
              : "border-[color-mix(in_srgb,var(--loss)_40%,transparent)] bg-[color-mix(in_srgb,var(--loss)_6%,transparent)]",
          )}
        >
          <div className="flex items-baseline gap-2">
            <CheckCircle2
              size={13}
              className={ok ? "text-[var(--gain)] mt-0.5" : "text-[var(--loss)] mt-0.5"}
            />
            <span className="font-mono text-[11px] text-[var(--ink)]">
              {String(ev.data.name ?? "")}
            </span>
            <span className="font-mono text-[10px] text-[var(--ink-faint)]">
              → {ok ? "ok" : "fail"}
            </span>
          </div>
          {Boolean(ev.data.summary || ev.data.error) && (
            <div className="mt-1 text-[12px] text-[var(--ink-soft)]">
              {String(ev.data.summary ?? ev.data.error ?? "")}
            </div>
          )}
          {ev.data.preview != null && (
            <pre className="mt-2 max-h-32 overflow-auto rounded-sm bg-[var(--surface)] p-2 font-mono text-[10px] leading-relaxed text-[var(--ink-muted)]">
              {JSON.stringify(ev.data.preview, null, 2)}
            </pre>
          )}
        </div>
      );
    }

    case "citation":
      return (
        <Row icon={Quote} muted>
          <span className="text-[12px] text-[var(--ink-muted)]">
            {String(ev.data.title ?? "")}
          </span>
          <span className="font-mono text-[10px] italic text-[var(--ink-faint)]">
            · {String(ev.data.source ?? "")}
          </span>
        </Row>
      );

    case "usage":
      return (
        <Row icon={Gauge} muted>
          <span className="font-mono text-[10px] tracking-[0.08em] uppercase text-[var(--ink-faint)]">
            tokens
          </span>
          <span className="numeric text-[11px] text-[var(--ink-muted)]">
            in {String(ev.data.input_tokens ?? "?")} · out{" "}
            {String(ev.data.output_tokens ?? "?")}
          </span>
        </Row>
      );

    case "log": {
      const level = String(ev.data.level ?? "info");
      const color =
        level === "error" ? "var(--loss)" : level === "warn" ? "var(--warn)" : "var(--ink-faint)";
      return (
        <Row icon={AlignLeft} muted>
          <span
            className="font-mono text-[10px] tracking-[0.08em] uppercase"
            style={{ color }}
          >
            {level}
          </span>
          <span className="font-mono text-[11px] text-[var(--ink-muted)]">
            {String(ev.data.message ?? "")}
          </span>
        </Row>
      );
    }

    case "artifact_written":
      return (
        <Row icon={FileText}>
          <span className="font-mono text-[11px] text-[var(--accent)]">
            📄 {String(ev.data.name ?? "")}
          </span>
          <span className="font-mono text-[10px] text-[var(--ink-faint)]">
            · {String(ev.data.written_by ?? "")} ·{" "}
            {String(ev.data.size_bytes ?? "?")} B
          </span>
        </Row>
      );

    case "await_review":
      return (
        <div className="rounded-[var(--r)] border border-[color-mix(in_srgb,var(--warn)_50%,transparent)] bg-[color-mix(in_srgb,var(--warn)_10%,transparent)] p-2.5">
          <div className="flex items-center gap-2">
            <AlertOctagon size={14} className="text-[var(--warn)]" />
            <span className="font-mono text-[11px] text-[var(--warn)]">
              await_review · {String(ev.data.checkpoint ?? "checkpoint")}
            </span>
          </div>
          {ev.data.reason ? (
            <div className="mt-1 text-[11px] text-[var(--ink-soft)]">
              {String(ev.data.reason)}
            </div>
          ) : null}
        </div>
      );

    case "error":
      return (
        <div className="rounded-[var(--r)] border border-[color-mix(in_srgb,var(--loss)_50%,transparent)] bg-[color-mix(in_srgb,var(--loss)_10%,transparent)] p-2.5">
          <div className="flex items-center gap-2">
            <AlertCircle size={14} className="text-[var(--loss)]" />
            <span className="text-[12px] text-[var(--loss)]">
              {String(ev.data.reason ?? "error")}
            </span>
          </div>
        </div>
      );

    case "done":
      return (
        <Row icon={CheckCheck}>
          <span className="font-mono text-[10px] tracking-[0.12em] uppercase text-[var(--gain)]">
            run done
          </span>
          <span className="font-mono text-[10px] text-[var(--ink-faint)]">
            steps={String(ev.data.steps ?? "?")} tools={String(ev.data.tools ?? "?")}
          </span>
        </Row>
      );

    case "subagent_start": {
      const name = String(ev.data.name ?? "?");
      const iter = ev.data.iteration;
      return (
        <Row icon={ChevronDown}>
          <span className="font-mono text-[10px] tracking-[0.12em] uppercase text-[var(--accent)]">
            subagent
          </span>
          <span className="font-display italic text-[13px] text-[var(--ink)]">
            {name}
          </span>
          {iter !== undefined && iter !== null ? (
            <span className="font-mono text-[10px] text-[var(--ink-faint)]">
              · iteration={String(iter)}
            </span>
          ) : null}
        </Row>
      );
    }

    case "subagent_end":
      return (
        <Row icon={ChevronUp} muted>
          <span className="font-mono text-[10px] tracking-[0.08em] uppercase text-[var(--ink-faint)]">
            subagent end · {String(ev.data.name ?? "?")}
          </span>
        </Row>
      );

    case "delta":
      return null;
  }
}

function Row({
  icon: Icon,
  children,
  muted,
}: {
  icon: React.ComponentType<{ size?: number; className?: string }>;
  children: React.ReactNode;
  muted?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 px-1",
        muted ? "text-[var(--ink-muted)]" : "text-[var(--ink)]",
      )}
    >
      <Icon size={12} className="shrink-0" />
      {children}
    </div>
  );
}
