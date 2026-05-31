"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Card, CardBody } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import {
  compareDiff,
  compareRun,
  getRun,
  listAgents,
  type AgentInfo,
  type CompareDiffEntry,
} from "@/lib/api";
import { canOperate, fetchMe, type AuthUser } from "@/lib/auth";
import type { ChatMessage } from "@/lib/types";
import { GitCompareArrows, Loader2, ArrowUpRight } from "lucide-react";
import { cn } from "@/lib/cn";

export default function ComparePage() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [model, setModel] = useState("");
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState("");
  const [results, setResults] = useState<CompareDiffEntry[] | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const isAdmin = canOperate(user);

  useEffect(() => {
    listAgents()
      .then((r) => setAgents(r.items))
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchMe().then(setUser).catch(() => setUser(null));
  }, []);

  function toggle(name: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else if (next.size < 4) next.add(name);
      return next;
    });
  }

  async function handleSubmit() {
    setError(null);
    setResults(null);
    if (!isAdmin) {
      setError("reader 模式不能创建对比 run");
      return;
    }
    if (!question.trim() || selected.size < 2) {
      setError("至少选择 2 个 skill 并输入问题");
      return;
    }
    setBusy(true);
    setStatus("creating runs…");
    const messages: ChatMessage[] = [{ role: "user", content: question.trim() }];

    try {
      const start = await compareRun({
        messages,
        agents: Array.from(selected),
        model: model || undefined,
      });
      const ids = start.run_ids;
      setStatus(`${ids.length} runs created · waiting…`);

      const deadline = Date.now() + 2 * 60_000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 1000));
        const details = await Promise.all(ids.map((id) => getRun(id)));
        const stillRunning = details.filter((d) => d.status === "running");
        setStatus(`completed ${ids.length - stillRunning.length}/${ids.length}`);
        if (stillRunning.length === 0) break;
      }

      setStatus("loading diff…");
      const diff = await compareDiff({ run_ids: ids });
      setResults(diff.runs);
      setStatus("");
    } catch (e) {
      setError((e as Error).message);
      setStatus("");
    } finally {
      setBusy(false);
    }
  }

  return (
    <PageContainer>
      <PageHeader
        eyebrow="ENGINE · COMPARE"
        title="A/B between skills"
        subtitle="同一段 prompt 同时发给多个 skill，并排比对延迟、调用的工具、最终回答。每个 skill 都跑一条独立 run，留痕在 /runs。"
      />

      <Card className="mb-6">
        <CardBody>
          <div className="eyebrow mb-3">SELECT 2–4 SKILLS</div>
          {agents.length === 0 ? (
            <div className="text-[12px] text-[var(--ink-muted)]">加载 skill 中…</div>
          ) : (
            <div className="flex flex-wrap gap-2">
              {agents.map((a) => {
                const on = selected.has(a.name);
                return (
                  <button
                    key={a.name}
                    type="button"
                    onClick={() => toggle(a.name)}
                    disabled={!isAdmin}
                    className={cn(
                      "inline-flex items-center gap-2 rounded-md border px-3 py-1.5 transition-all",
                      on
                        ? "border-[var(--accent)] bg-[var(--accent-soft)] text-[var(--ink)]"
                        : "border-[var(--line-strong)] text-[var(--ink-soft)] hover:border-[var(--ink-muted)] hover:bg-[var(--surface-hover)]",
                    )}
                  >
                    <span className="font-display italic text-[14px] tracking-tight">
                      {a.name}
                    </span>
                    <span className="font-mono text-[10px] text-[var(--ink-faint)]">
                      {a.version}
                    </span>
                  </button>
                );
              })}
            </div>
          )}

          <div className="mt-5 flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-2">
              <span className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
                MODEL
              </span>
              <input
                type="text"
                value={model}
                onChange={(e) => setModel(e.target.value)}
                readOnly={!isAdmin}
                placeholder="default"
                className="w-48 rounded-md border border-[var(--line-strong)] bg-[var(--surface)] px-2.5 py-1.5 font-mono text-[11px] text-[var(--ink-soft)] placeholder:text-[var(--ink-faint)] focus:border-[var(--accent)] transition-colors"
              />
            </label>
          </div>

          <textarea
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            readOnly={!isAdmin}
            rows={3}
            placeholder="同一个问题问多个 skill…"
            className="mt-4 w-full resize-none rounded-md border border-[var(--line-strong)] bg-[var(--surface)] p-3 font-body text-[14px] leading-relaxed text-[var(--ink)] placeholder:text-[var(--ink-faint)] focus:outline-none focus:border-[var(--accent)]"
          />

          <div className="mt-4 flex items-center gap-3">
            <Button variant="primary" onClick={handleSubmit} disabled={!isAdmin || busy}>
              {busy ? <Loader2 size={12} className="animate-spin" /> : <GitCompareArrows size={12} />}
              {busy ? "Running…" : "Compare"}
            </Button>
            {status && (
              <span className="font-mono text-[11px] tracking-[0.04em] text-[var(--ink-faint)]">
                {status}
              </span>
            )}
          </div>

          {error && (
            <div className="mt-3 rounded-[var(--r)] border border-[color-mix(in_srgb,var(--loss)_40%,transparent)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)] p-2.5 text-[12px] text-[var(--loss)]">
              ⚠ {error}
            </div>
          )}
          {!isAdmin && (
            <div className="mt-3 rounded-[var(--r)] border border-[var(--line)] bg-[var(--surface)] p-2.5 font-mono text-[11px] text-[var(--ink-muted)]">
              reader 模式：可以查看已有 run；创建对比 run 仅限 admin。
            </div>
          )}
        </CardBody>
      </Card>

      {results && (
        <>
          <div className="eyebrow mb-4">RESULTS</div>
          <div
            className="grid gap-4"
            style={{ gridTemplateColumns: `repeat(${results.length}, minmax(0, 1fr))` }}
          >
            {results.map((r) => (
              <Card key={r.id} className="overflow-hidden">
                <CardBody>
                  <div className="flex items-baseline justify-between">
                    <span className="font-display italic text-[20px] tracking-tight text-[var(--ink)]">
                      {r.skill}
                    </span>
                    {r.latency_ms != null && (
                      <span className="numeric text-[11px] text-[var(--ink-muted)]">
                        {r.latency_ms.toFixed(0)} ms
                      </span>
                    )}
                  </div>
                  {r.tools_called && r.tools_called.length > 0 && (
                    <div className="mt-3 flex flex-wrap gap-1">
                      {r.tools_called.map((t) => (
                        <Badge key={t}>{t}</Badge>
                      ))}
                    </div>
                  )}
                  {r.final_text ? (
                    <pre className="mt-4 max-h-80 overflow-auto whitespace-pre-wrap rounded-md bg-[var(--surface)] p-3 font-body text-[13px] leading-relaxed text-[var(--ink-soft)]">
                      {r.final_text}
                    </pre>
                  ) : (
                    <div className="mt-4 text-[12px] italic text-[var(--ink-muted)]">
                      (no output)
                    </div>
                  )}
                  <Link
                    href={`/runs/${r.id}`}
                    className="mt-3 inline-flex items-center gap-1 font-mono text-[10px] tracking-[0.08em] uppercase text-[var(--ink-muted)] hover:text-[var(--accent)] transition-colors"
                  >
                    {r.id} <ArrowUpRight size={12} />
                  </Link>
                </CardBody>
              </Card>
            ))}
          </div>
        </>
      )}
    </PageContainer>
  );
}
