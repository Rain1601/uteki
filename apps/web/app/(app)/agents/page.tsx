"use client";

import { useEffect, useState } from "react";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import {
  listAgents,
  listVersions,
  type AgentInfo,
  type SkillVersion,
} from "@/lib/api";
import { ChevronDown, ChevronRight, GitBranch } from "lucide-react";

function formatTs(ts: number | undefined): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString();
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [versions, setVersions] = useState<Record<string, SkillVersion[]>>({});
  const [loadingV, setLoadingV] = useState<Record<string, boolean>>({});

  useEffect(() => {
    listAgents()
      .then((r) => setAgents(r.items))
      .catch((e) => setError((e as Error).message));
  }, []);

  async function toggle(name: string) {
    const willOpen = !expanded[name];
    setExpanded((p) => ({ ...p, [name]: willOpen }));
    if (willOpen && !versions[name]) {
      setLoadingV((p) => ({ ...p, [name]: true }));
      try {
        const r = await listVersions(name);
        setVersions((p) => ({ ...p, [name]: r.items }));
      } catch (e) {
        setError((e as Error).message);
      } finally {
        setLoadingV((p) => ({ ...p, [name]: false }));
      }
    }
  }

  return (
    <PageContainer>
      <PageHeader
        eyebrow="CATALOG · SKILLS"
        title="Skills & evolution"
        subtitle="每个 skill 注册时记录 prompt / tools / model 的签名。启动期自动 diff 与上次比对，签名变更 → 新版本。每条 run 都绑定其执行时的版本，便于回溯。"
      />

      {error && (
        <Card className="mb-4 border-[color-mix(in_srgb,var(--loss)_40%,transparent)] p-4 text-[12px] text-[var(--loss)]">
          ⚠ {error}
        </Card>
      )}

      <ul className="space-y-3">
        {agents.map((a) => {
          const open = !!expanded[a.name];
          const vs = (versions[a.name] ?? []).slice().sort((x, y) => y.created_at - x.created_at);
          return (
            <Card key={a.name} as="article" className="overflow-hidden">
              <button
                type="button"
                onClick={() => toggle(a.name)}
                className="block w-full px-5 py-4 text-left hover:bg-[var(--surface-hover)] transition-colors"
              >
                <div className="flex items-center gap-3">
                  {open ? (
                    <ChevronDown size={14} className="text-[var(--ink-muted)]" />
                  ) : (
                    <ChevronRight size={14} className="text-[var(--ink-muted)]" />
                  )}
                  <span className="font-display italic text-[22px] tracking-tight text-[var(--ink)]">
                    {a.name}
                  </span>
                  <Badge tone="accent">{a.version}</Badge>
                  <span className="ml-auto font-mono text-[10px] tracking-[0.08em] text-[var(--ink-faint)]">
                    skill
                  </span>
                </div>
                <p className="mt-2 pl-7 text-[13px] leading-relaxed text-[var(--ink-soft)]">
                  {a.description}
                </p>
              </button>

              {open && (
                <div className="border-t border-[var(--line)] bg-[var(--surface)]/40 p-5">
                  <div className="mb-3 flex items-center gap-2">
                    <GitBranch size={13} className="text-[var(--accent)]" />
                    <span className="font-mono text-[9px] tracking-[0.18em] uppercase text-[var(--ink-faint)]">
                      VERSION HISTORY
                    </span>
                  </div>

                  {loadingV[a.name] ? (
                    <div className="text-[12px] text-[var(--ink-muted)]">加载中…</div>
                  ) : vs.length === 0 ? (
                    <div className="text-[12px] text-[var(--ink-muted)]">没有版本记录</div>
                  ) : (
                    <ol className="relative space-y-3 pl-5">
                      <span
                        aria-hidden
                        className="absolute left-[6px] top-2 bottom-2 w-px bg-[var(--line)]"
                      />
                      {vs.map((v, i) => (
                        <li key={v.version} className="relative">
                          <span
                            aria-hidden
                            className="absolute -left-[14px] top-2 h-2 w-2 rounded-full ring-2 ring-[var(--surface)]"
                            style={{
                              background: i === 0 ? "var(--accent)" : "var(--ink-muted)",
                            }}
                          />
                          <div className="rounded-[var(--r)] border border-[var(--line)] bg-[var(--surface-1)] p-3">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="font-mono text-[12px] font-semibold text-[var(--ink)]">
                                {v.version}
                              </span>
                              {v.parent_version && (
                                <span className="font-mono text-[10px] text-[var(--ink-faint)]">
                                  ← {v.parent_version}
                                </span>
                              )}
                              <Badge>{v.model}</Badge>
                              <span className="ml-auto font-mono text-[10px] text-[var(--ink-faint)]">
                                {formatTs(v.created_at)}
                              </span>
                            </div>
                            {v.changelog && (
                              <div className="mt-2 text-[12px] text-[var(--ink-soft)]">
                                {v.changelog}
                              </div>
                            )}
                            {v.tool_names && v.tool_names.length > 0 && (
                              <div className="mt-2 flex flex-wrap gap-1">
                                {v.tool_names.map((t) => (
                                  <Badge key={t}>{t}</Badge>
                                ))}
                              </div>
                            )}
                            {v.prompt && (
                              <details className="mt-2">
                                <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-[0.08em] text-[var(--ink-muted)] hover:text-[var(--ink)]">
                                  view prompt
                                </summary>
                                <pre className="mt-2 max-h-40 overflow-auto rounded-sm bg-[var(--surface)] p-2 font-mono text-[10px] leading-relaxed text-[var(--ink-muted)] whitespace-pre-wrap">
                                  {v.prompt}
                                </pre>
                              </details>
                            )}
                          </div>
                        </li>
                      ))}
                    </ol>
                  )}
                </div>
              )}
            </Card>
          );
        })}
      </ul>
    </PageContainer>
  );
}
