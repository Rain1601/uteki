"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  FileText,
  Loader2,
  Play,
  RefreshCw,
  Square,
} from "lucide-react";
import { streamChat, listRuns, type RunSummary } from "@/lib/api";
import { canOperate, fetchMe, type AuthUser } from "@/lib/auth";
import type { AgentEvent, ChatMessage } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { cn } from "@/lib/cn";

type WatchVerdict = "BUY" | "WATCH" | "AVOID" | "UNRATED";

interface CompanyWatchItem {
  symbol: string;
  name: string;
  peers: string[];
  verdict: WatchVerdict;
  conviction?: number;
  runs?: number;
}

const WATCHLIST: CompanyWatchItem[] = [
  {
    symbol: "GOOGL",
    name: "Alphabet Inc.",
    peers: ["META", "MSFT", "AMZN"],
    verdict: "BUY",
    conviction: 0.7,
    runs: 37,
  },
  {
    symbol: "TSM",
    name: "Taiwan Semi.",
    peers: ["NVDA", "ASML", "AMD"],
    verdict: "WATCH",
    conviction: 0.45,
    runs: 4,
  },
  {
    symbol: "NVDA",
    name: "NVIDIA Corp.",
    peers: ["AMD", "AVGO", "INTC"],
    verdict: "WATCH",
    conviction: 0.55,
    runs: 6,
  },
  {
    symbol: "AAPL",
    name: "Apple Inc.",
    peers: ["MSFT", "GOOGL", "META"],
    verdict: "WATCH",
    conviction: 0.5,
    runs: 2,
  },
  {
    symbol: "MSFT",
    name: "Microsoft",
    peers: ["GOOGL", "AMZN", "ORCL"],
    verdict: "UNRATED",
  },
  {
    symbol: "TSLA",
    name: "Tesla, Inc.",
    peers: ["GM", "F", "RIVN"],
    verdict: "AVOID",
    conviction: 0.35,
    runs: 10,
  },
];

const STAGE_LABELS = [
  "证据采集",
  "业务解析",
  "成长质量",
  "护城河",
  "管理层",
  "逆向检验",
  "估值与时机",
  "排序与仓位",
  "最终备忘录",
];

function formatTs(ts: number | undefined | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function duration(r: RunSummary): string {
  if (!r.started_at || !r.ended_at) return "running";
  const seconds = Math.max(0, Math.round(r.ended_at - r.started_at));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function verdictTone(verdict: WatchVerdict | string): "gain" | "loss" | "warn" | "neutral" {
  if (verdict === "BUY") return "gain";
  if (verdict === "AVOID") return "loss";
  if (verdict === "WATCH") return "warn";
  return "neutral";
}

function inferSymbol(run: RunSummary): string {
  const text = `${run.user_input ?? ""} ${run.summary ?? ""}`;
  const match = text.match(/\b[A-Z]{1,5}(?:\.[A-Z]{2})?\b|\b\d{6}\.(?:SH|SZ)\b/);
  return match?.[0] ?? run.skill;
}

function stageFromEvents(events: AgentEvent[]): { index: number; label: string; progress: number } {
  if (events.length === 0) return { index: 0, label: "等待起草", progress: 0 };
  let index = 0;
  for (const ev of events) {
    if (ev.type === "tool_call" || ev.type === "tool_result") index = Math.max(index, 1);
    if (ev.type === "subagent_start") {
      const gate = Number(ev.data.gate ?? 0);
      if (gate > 0) index = Math.max(index, gate + 1);
    }
    if (ev.type === "artifact_written") {
      const name = String(ev.data.name ?? "");
      if (name === "ranking.json" || name === "capital-plan.json") index = Math.max(index, 8);
      if (name === "final-report.md" || name === "decision.json") index = Math.max(index, 9);
    }
    if (ev.type === "done") index = STAGE_LABELS.length;
  }
  const clamped = Math.min(index, STAGE_LABELS.length);
  return {
    index: clamped,
    label: STAGE_LABELS[Math.max(0, clamped - 1)] ?? "运行中",
    progress: Math.round((clamped / STAGE_LABELS.length) * 100),
  };
}

function eventLine(ev: AgentEvent): string {
  if (ev.type === "tool_call") return `调用 ${String(ev.data.name ?? "tool")}`;
  if (ev.type === "tool_result") {
    const ok = ev.data.ok === false ? "失败" : "完成";
    return `${String(ev.data.name ?? "tool")} ${ok}`;
  }
  if (ev.type === "subagent_start") {
    return `进入 ${String(ev.data.display_name ?? ev.data.name ?? "gate")}`;
  }
  if (ev.type === "subagent_end") {
    return `完成 ${String(ev.data.display_name ?? ev.data.name ?? "gate")}`;
  }
  if (ev.type === "artifact_written") {
    return `写入 ${String(ev.data.display_name ?? ev.data.name ?? "artifact")}`;
  }
  if (ev.type === "plan") return "生成执行计划";
  if (ev.type === "done") return "run 完成";
  if (ev.type === "error") return `错误：${String(ev.data.reason ?? "unknown")}`;
  return ev.type;
}

function runPrompt(symbol: string, peers: string): string {
  const peerText = peers.trim() ? `，对比同类公司 ${peers.trim()}` : "";
  return [
    `对 ${symbol.trim().toUpperCase()} 做公司深度调研${peerText}，最多对比 3 家公司。`,
    "结合巴菲特、芒格、费雪框架，输出排序、购买建议和资金管理计划。",
    "要求：每一步持久化 artifact；明确证据来源；不得执行真实下单；资金管理要包含初始仓位、最大仓位、加仓/减仓/卖出触发条件。",
  ].join("\n");
}

export default function CompanyAgentPage() {
  const [symbol, setSymbol] = useState("GOOGL");
  const [peers, setPeers] = useState("META, MSFT, AMZN");
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [aborter, setAborter] = useState<AbortController | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const isAdmin = canOperate(user);

  const refreshRuns = useCallback(async () => {
    setLoadingRuns(true);
    try {
      const res = await listRuns({ skill: "company_research_pipeline", limit: 60 });
      setRuns(res.items);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoadingRuns(false);
    }
  }, []);

  useEffect(() => {
    refreshRuns();
  }, [refreshRuns]);

  useEffect(() => {
    fetchMe().then(setUser).catch(() => setUser(null));
  }, []);

  const latestRun = runs[0] ?? null;
  const currentStage = useMemo(() => stageFromEvents(events), [events]);
  const visibleEvents = useMemo(
    () =>
      events.filter((ev) =>
        ["plan", "tool_call", "tool_result", "subagent_start", "subagent_end", "artifact_written", "error", "done"].includes(
          ev.type,
        ),
      ),
    [events],
  );

  function chooseCompany(item: CompanyWatchItem, runNow = false) {
    setSymbol(item.symbol);
    setPeers(item.peers.join(", "));
    if (runNow && isAdmin) {
      void startRun(item.symbol, item.peers.join(", "));
    }
  }

  async function startRun(targetSymbol = symbol, peerText = peers) {
    const cleanSymbol = targetSymbol.trim().toUpperCase();
    if (!cleanSymbol || isRunning || !isAdmin) return;
    const controller = new AbortController();
    setAborter(controller);
    setError(null);
    setEvents([]);
    setActiveRunId(null);
    setIsRunning(true);

    const messages: ChatMessage[] = [{ role: "user", content: runPrompt(cleanSymbol, peerText) }];

    try {
      let seenRunId: string | null = null;
      for await (const ev of streamChat(
        {
          messages,
          agent: "company_research_pipeline",
          model: "deepseek/deepseek-chat",
        },
        controller.signal,
      )) {
        if (ev.run_id && ev.run_id !== seenRunId) {
          seenRunId = ev.run_id;
          setActiveRunId(ev.run_id);
        }
        setEvents((prev) => [...prev, ev]);
      }
      await refreshRuns();
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
    } finally {
      setIsRunning(false);
      setAborter(null);
    }
  }

  return (
    <div className="min-h-screen paper-grain">
      <div className="border-b border-[var(--line)] px-8 py-7">
        <div className="flex flex-wrap items-end gap-5">
          <div>
            <div className="eyebrow mb-2">RESEARCH DESK · COMPANY AGENT</div>
            <h1 className="h-display text-[42px] text-[var(--ink)]">研究台</h1>
          </div>
          <div className="mb-2 font-mono text-[10px] tracking-[0.18em] text-[var(--ink-faint)]">
            关注 {WATCHLIST.length} · 在跑 {isRunning ? 1 : 0} · 历史 {runs.length}
            {user ? ` · ${user.role.toUpperCase()}` : ""}
          </div>
          <div className="ml-auto mb-1 flex items-center gap-2">
            <Button variant="ghost" onClick={refreshRuns} disabled={loadingRuns}>
              <RefreshCw size={13} className={loadingRuns ? "animate-spin" : ""} />
              刷新
            </Button>
            <Button variant="primary" onClick={() => startRun()} disabled={!isAdmin || isRunning || !symbol.trim()}>
              {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              起草新研究
            </Button>
          </div>
        </div>
      </div>

      <div className="grid min-h-[calc(100vh-112px)] grid-cols-1 lg:grid-cols-[360px_minmax(0,1fr)_360px]">
        <aside className="border-b border-[var(--line)] lg:border-b-0 lg:border-r">
          <div className="flex items-center justify-between border-b border-[var(--line)] px-7 py-5">
            <div className="eyebrow">WATCHLIST</div>
            <span className="font-mono text-[10px] text-[var(--ink-faint)]">
              {isAdmin ? "+ 添加" : "READ ONLY"}
            </span>
          </div>
          <ul className="divide-y divide-[var(--line)]">
            {WATCHLIST.map((item) => (
              <li key={item.symbol}>
                <button
                  className={cn(
                    "group w-full border-l-2 px-7 py-5 text-left transition-colors hover:bg-[var(--surface-hover)]",
                    symbol === item.symbol ? "border-[var(--gain)] bg-[var(--surface-hover)]" : "border-transparent",
                  )}
                  onClick={() => chooseCompany(item)}
                >
                  <div className="flex items-start gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="font-display text-[21px] italic leading-none text-[var(--ink)]">
                        {item.symbol}
                      </div>
                      <div className="mt-2 font-display text-[13px] italic text-[var(--ink-muted)]">
                        {item.name}
                      </div>
                      <div className="mt-3 flex items-center gap-2">
                        <Badge tone={verdictTone(item.verdict)}>{item.verdict}</Badge>
                        {item.runs != null && (
                          <span className="font-mono text-[10px] tracking-[0.08em] text-[var(--ink-faint)]">
                            {item.runs}x
                          </span>
                        )}
                      </div>
                    </div>
                    {isAdmin && (
                      <span
                        className="mt-9 inline-flex h-7 items-center border border-[var(--line-strong)] px-2 font-mono text-[10px] text-[var(--ink-muted)] opacity-70 transition-colors group-hover:text-[var(--ink)]"
                        onClick={(e) => {
                          e.stopPropagation();
                          chooseCompany(item, true);
                        }}
                      >
                        起草 <ArrowRight size={12} />
                      </span>
                    )}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <main className="px-8 py-10 xl:px-12">
          <div className="mb-8 grid gap-3 md:grid-cols-[180px_minmax(0,1fr)_auto]">
            <label>
              <div className="mb-2 font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
                SYMBOL
              </div>
              <input
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                readOnly={!isAdmin}
                className="h-10 w-full border border-[var(--line-strong)] bg-[var(--surface)] px-3 font-display text-[20px] italic text-[var(--ink)] outline-none focus:border-[var(--accent)]"
              />
            </label>
            <label>
              <div className="mb-2 font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
                PEERS · MAX 3
              </div>
              <input
                value={peers}
                onChange={(e) => setPeers(e.target.value)}
                readOnly={!isAdmin}
                className="h-10 w-full border border-[var(--line-strong)] bg-[var(--surface)] px-3 font-mono text-[12px] text-[var(--ink-soft)] outline-none focus:border-[var(--accent)]"
                placeholder="META, MSFT, AMZN"
              />
            </label>
            <div className="flex items-end gap-2">
              {isRunning && (
                <Button variant="outline" onClick={() => aborter?.abort()}>
                  <Square size={13} /> 中止
                </Button>
              )}
              <Button variant="primary" onClick={() => startRun()} disabled={!isAdmin || isRunning || !symbol.trim()}>
                {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
                运行
              </Button>
            </div>
          </div>

          <section className="border border-[var(--line-strong)] bg-[color-mix(in_srgb,var(--surface)_70%,transparent)] px-7 py-6">
            <div className="mb-5 flex flex-wrap items-center gap-3">
              <div className="font-display text-[32px] italic leading-none text-[var(--ink)]">
                {symbol || "Company"}
              </div>
              <span className="font-mono text-[10px] tracking-[0.2em] text-[var(--ink-faint)]">
                DEEPSEEK · COMPANY RESEARCH PIPELINE
              </span>
              <div className="ml-auto font-mono text-[12px] text-[var(--ink-soft)]">
                {isRunning ? currentStage.label : latestRun ? "最近一次执行" : "等待起草"}
              </div>
            </div>

            <div className="mb-5 grid grid-cols-9 gap-1">
              {STAGE_LABELS.map((label, i) => (
                <div
                  key={label}
                  title={label}
                  className={cn(
                    "h-1.5 border border-[var(--line)]",
                    currentStage.index > i || (!isRunning && latestRun)
                      ? "bg-[var(--ink-soft)]"
                      : "bg-[var(--surface-2)]",
                  )}
                />
              ))}
            </div>

            <div className="flex flex-wrap items-center gap-x-6 gap-y-3 font-mono text-[11px] tracking-[0.08em] text-[var(--ink-faint)]">
              <span>{isRunning ? `${currentStage.progress}%` : "READY"}</span>
              <span>GATES 1/6 → 6/6</span>
              <span>ARTIFACT-FIRST</span>
              <span>NO REAL ORDER EXECUTION</span>
              {activeRunId && (
                <Link href={`/runs/${activeRunId}`} className="ml-auto text-[var(--accent)] hover:underline">
                  查看 run →
                </Link>
              )}
            </div>
          </section>

          {error && (
            <div className="mt-4 border border-[color-mix(in_srgb,var(--loss)_40%,transparent)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)] px-4 py-3 font-mono text-[11px] text-[var(--loss)]">
              {error}
            </div>
          )}
          {!isAdmin && (
            <div className="mt-4 border border-[var(--line)] bg-[var(--surface)] px-4 py-3 font-mono text-[11px] text-[var(--ink-muted)]">
              reader 模式：可以查看历史 run、运行过程和 artifact；起草、运行和中止仅限 admin。
            </div>
          )}

          <section className="mt-10">
            <div className="mb-4 flex items-baseline gap-3">
              <h2 className="font-display text-[28px] italic text-[var(--ink)]">运行观察</h2>
              <span className="font-mono text-[10px] tracking-[0.16em] text-[var(--ink-faint)]">
                live trace · artifacts · gates
              </span>
            </div>
            {visibleEvents.length === 0 ? (
              <div className="border-t border-[var(--line)] py-10 text-[13px] text-[var(--ink-muted)]">
                点击“运行”后，这里会实时显示工具调用、gate 推进和 artifact 写入。
              </div>
            ) : (
              <ol className="border-t border-[var(--line)]">
                {visibleEvents.slice(-18).map((ev, i) => (
                  <li key={`${ev.ts}-${ev.type}-${i}`} className="grid grid-cols-[120px_minmax(0,1fr)] border-b border-[var(--line)] py-3">
                    <span className="font-mono text-[10px] text-[var(--ink-faint)]">
                      {new Date(ev.ts * 1000).toLocaleTimeString("zh-CN", {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit",
                      })}
                    </span>
                    <span className="text-[13px] text-[var(--ink-soft)]">{eventLine(ev)}</span>
                  </li>
                ))}
              </ol>
            )}
          </section>
        </main>

        <aside className="border-t border-[var(--line)] px-7 py-6 lg:border-l lg:border-t-0">
          <div className="mb-5 flex items-center justify-between">
            <div className="eyebrow">LOG</div>
            <span className="font-mono text-[10px] text-[var(--ink-faint)]">{runs.length} entries</span>
          </div>
          {runs.length === 0 ? (
            <div className="py-8 text-[12px] leading-relaxed text-[var(--ink-muted)]">
              还没有公司深度调研 run。起草后会写入 `/runs`，并持久化所有 artifacts。
            </div>
          ) : (
            <ul className="divide-y divide-[var(--line)]">
              {runs.slice(0, 18).map((run) => (
                <li key={run.id}>
                  <Link href={`/runs/${run.id}`} className="block py-4 hover:bg-[var(--surface-hover)]">
                    <div className="flex items-baseline gap-3">
                      <span className="w-24 shrink-0 font-mono text-[10px] text-[var(--ink-faint)]">
                        {formatTs(run.started_at)}
                      </span>
                      <span className="font-display text-[16px] italic text-[var(--ink)]">
                        {inferSymbol(run)}
                      </span>
                      <span className="ml-auto font-mono text-[10px] uppercase text-[var(--ink-muted)]">
                        {run.status}
                      </span>
                    </div>
                    <div className="mt-1 flex items-center gap-3 pl-24 font-mono text-[10px] text-[var(--ink-faint)]">
                      <span>{run.primary_artifact?.display_name ?? "investment memo"}</span>
                      <span>{duration(run)}</span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}

          <div className="mt-8 border-t border-[var(--line)] pt-5">
            <div className="mb-3 flex items-center gap-2 text-[var(--ink-muted)]">
              <Activity size={14} />
              <span className="eyebrow">AGENT CONTRACT</span>
            </div>
            <div className="space-y-2 text-[12px] leading-relaxed text-[var(--ink-muted)]">
              <p>真实模型：deepseek/deepseek-chat</p>
              <p>核心步骤：证据采集 → 六个 gate → 排序 → 资金计划 → 最终备忘录。</p>
              <p>每次执行会写入 run、trace、artifact 和 capability review。</p>
            </div>
            {latestRun && (
              <Link
                href={`/runs/${latestRun.id}`}
                className="mt-4 inline-flex items-center gap-2 font-mono text-[11px] tracking-[0.08em] text-[var(--accent)] hover:underline"
              >
                <FileText size={13} /> 打开最近档案
              </Link>
            )}
          </div>
        </aside>
      </div>
    </div>
  );
}
