"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { listAgents, type AgentInfo } from "@/lib/api";
import { ArrowUpRight, GitBranch } from "lucide-react";

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listAgents()
      .then((r) => setAgents(r.items))
      .catch((e) => setError((e as Error).message));
  }, []);

  return (
    <PageContainer>
      <PageHeader
        eyebrow="CATALOG · SKILLS"
        title="Skills & evolution"
        subtitle="每个 skill 是一个注册的 agent，带版本签名（prompt / tools / model）。点进去看它的配置、最近 run、版本演化历史。"
      />

      {error && (
        <Card className="mb-4 border-[color-mix(in_srgb,var(--loss)_40%,transparent)] p-4 text-[12px] text-[var(--loss)]">
          ⚠ {error}
        </Card>
      )}

      <ul className="grid gap-3 md:grid-cols-2">
        {agents.map((a) => (
          <li key={a.name}>
            <Link
              href={`/agents/${encodeURIComponent(a.name)}`}
              className="group block h-full rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface-1)] p-5 transition-colors hover:border-[var(--line-strong)] hover:bg-[var(--surface-2)]"
            >
              <div className="flex items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-baseline gap-2">
                    <span className="font-display italic text-[20px] tracking-tight text-[var(--ink)] truncate">
                      {a.name}
                    </span>
                    <Badge tone="accent">{a.version}</Badge>
                    {a.kind === "pipeline" && (
                      <span className="font-mono text-[9px] tracking-[0.18em] uppercase text-[var(--ink-faint)]">
                        pipeline
                      </span>
                    )}
                  </div>
                  <p className="mt-2 line-clamp-2 text-[13px] leading-relaxed text-[var(--ink-soft)]">
                    {a.description}
                  </p>
                </div>
                <ArrowUpRight
                  size={14}
                  className="shrink-0 text-[var(--ink-faint)] group-hover:text-[var(--accent)] transition-colors"
                />
              </div>

              <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-[var(--line)]/60 pt-3">
                {(a.default_tools ?? []).slice(0, 4).map((t) => (
                  <Badge key={t}>{t}</Badge>
                ))}
                {(a.default_tools?.length ?? 0) > 4 && (
                  <span className="font-mono text-[10px] text-[var(--ink-faint)]">
                    +{(a.default_tools?.length ?? 0) - 4}
                  </span>
                )}
                {a.default_model && (
                  <span className="ml-auto inline-flex items-center gap-1 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
                    <GitBranch size={10} /> {a.default_model}
                  </span>
                )}
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </PageContainer>
  );
}
