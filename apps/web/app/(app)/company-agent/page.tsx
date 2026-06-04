"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  ArrowRight,
  CandlestickChart,
  FileText,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Search,
  Square,
  X,
} from "lucide-react";
import { streamChat, listRuns, type RunSummary } from "@/lib/api";
import { canOperate, fetchMe, type AuthUser } from "@/lib/auth";
import type { AgentEvent, ChatMessage } from "@/lib/types";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { TradingViewChart, toTradingViewSymbol } from "@/components/charts/TradingViewChart";
import { cn } from "@/lib/cn";

type WatchVerdict = "BUY" | "WATCH" | "AVOID" | "UNRATED";
type WatchMarket = "US" | "TW" | "CN";

interface CompanyWatchItem {
  symbol: string;
  name: string;
  market: WatchMarket;
  sector: string;
  peers: string[];
  verdict: WatchVerdict;
  conviction?: number;
  last?: number;
  changePct?: number;
  runs?: number;
}

const INITIAL_WATCHLIST: CompanyWatchItem[] = [
  {
    symbol: "GOOGL",
    name: "Alphabet Inc.",
    market: "US",
    sector: "Internet",
    peers: ["META", "MSFT", "AMZN"],
    verdict: "BUY",
    conviction: 0.7,
    last: 402.62,
    changePct: -2.51,
    runs: 37,
  },
  {
    symbol: "TSM",
    name: "Taiwan Semi.",
    market: "TW",
    sector: "Semiconductors",
    peers: ["NVDA", "ASML", "AMD"],
    verdict: "WATCH",
    conviction: 0.45,
    last: 198.4,
    changePct: 0.72,
    runs: 4,
  },
  {
    symbol: "NVDA",
    name: "NVIDIA Corp.",
    market: "US",
    sector: "AI Chips",
    peers: ["AMD", "AVGO", "INTC"],
    verdict: "WATCH",
    conviction: 0.55,
    last: 142.55,
    changePct: -1.24,
    runs: 6,
  },
  {
    symbol: "AAPL",
    name: "Apple Inc.",
    market: "US",
    sector: "Consumer Tech",
    peers: ["MSFT", "GOOGL", "META"],
    verdict: "WATCH",
    conviction: 0.5,
    last: 234.12,
    changePct: 0.82,
    runs: 2,
  },
  {
    symbol: "MSFT",
    name: "Microsoft",
    market: "US",
    sector: "Cloud",
    peers: ["GOOGL", "AMZN", "ORCL"],
    verdict: "UNRATED",
    last: 442.18,
    changePct: 0.35,
  },
  {
    symbol: "TSLA",
    name: "Tesla, Inc.",
    market: "US",
    sector: "Auto",
    peers: ["GM", "F", "RIVN"],
    verdict: "AVOID",
    conviction: 0.35,
    last: 359.92,
    changePct: 2.14,
    runs: 10,
  },
];

const COMMON_PEERS = [
  "META",
  "MSFT",
  "AMZN",
  "NVDA",
  "AMD",
  "AVGO",
  "ASML",
  "ORCL",
  "CRM",
  "TSM",
  "INTC",
  "QCOM",
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
  const [peerTags, setPeerTags] = useState<string[]>(["META", "MSFT", "AMZN"]);
  const [watchItems, setWatchItems] = useState<CompanyWatchItem[]>(INITIAL_WATCHLIST);
  const [watchSearch, setWatchSearch] = useState("");
  const [verdictFilter, setVerdictFilter] = useState<"ALL" | WatchVerdict>("ALL");
  const [marketFilter, setMarketFilter] = useState<"ALL" | WatchMarket>("ALL");
  const [showAddWatch, setShowAddWatch] = useState(false);
  const [newWatchSymbol, setNewWatchSymbol] = useState("");
  const [newWatchName, setNewWatchName] = useState("");
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadingRuns, setLoadingRuns] = useState(false);
  const [aborter, setAborter] = useState<AbortController | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const [chartItem, setChartItem] = useState<CompanyWatchItem | null>(null);
  const canRunCompanyAgent = canOperate(user, "company_research_pipeline");
  const peerSuggestions = useMemo(
    () =>
      Array.from(
        new Set([
          ...watchItems.map((item) => item.symbol),
          ...watchItems.flatMap((item) => item.peers),
          ...COMMON_PEERS,
        ]),
      ).sort(),
    [watchItems],
  );
  const filteredWatchItems = useMemo(() => {
    const q = watchSearch.trim().toUpperCase();
    return watchItems.filter((item) => {
      const matchesQuery =
        !q ||
        item.symbol.includes(q) ||
        item.name.toUpperCase().includes(q) ||
        item.sector.toUpperCase().includes(q);
      const matchesVerdict = verdictFilter === "ALL" || item.verdict === verdictFilter;
      const matchesMarket = marketFilter === "ALL" || item.market === marketFilter;
      return matchesQuery && matchesVerdict && matchesMarket;
    });
  }, [marketFilter, verdictFilter, watchItems, watchSearch]);

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
    setPeerTags(item.peers.slice(0, 3));
    if (runNow && canRunCompanyAgent) {
      void startRun(item.symbol, item.peers.join(", "));
    }
  }

  function addWatchItem() {
    const cleanSymbol = newWatchSymbol.trim().toUpperCase();
    if (!cleanSymbol) return;
    const existing = watchItems.find((item) => item.symbol === cleanSymbol);
    if (existing) {
      chooseCompany(existing);
      setShowAddWatch(false);
      setNewWatchSymbol("");
      setNewWatchName("");
      return;
    }
    const item: CompanyWatchItem = {
      symbol: cleanSymbol,
      name: newWatchName.trim() || cleanSymbol,
      market: "US",
      sector: "Custom",
      peers: [],
      verdict: "UNRATED",
      runs: 0,
    };
    setWatchItems((prev) => [item, ...prev]);
    setSymbol(item.symbol);
    setPeerTags([]);
    setShowAddWatch(false);
    setNewWatchSymbol("");
    setNewWatchName("");
  }

  async function startRun(targetSymbol = symbol, peerText = peerTags.join(", ")) {
    const cleanSymbol = targetSymbol.trim().toUpperCase();
    if (!cleanSymbol || isRunning || !canRunCompanyAgent) return;
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
    <div className="h-screen overflow-hidden flex flex-col paper-grain">
      <div className="shrink-0 border-b border-[var(--line)] px-8 py-5">
        <div className="flex flex-wrap items-end gap-5">
          <div>
            <div className="eyebrow mb-1.5">RESEARCH DESK · COMPANY AGENT</div>
            <h1 className="h-display text-[32px] text-[var(--ink)]">研究台</h1>
          </div>
          <div className="mb-1 font-mono text-[10px] tracking-[0.18em] text-[var(--ink-faint)]">
            关注 {watchItems.length} · 在跑 {isRunning ? 1 : 0} · 历史 {runs.length}
            {user ? ` · ${user.role.toUpperCase()}` : ""}
          </div>
          <div className="ml-auto mb-1 flex items-center gap-2">
            <Button variant="ghost" onClick={refreshRuns} disabled={loadingRuns}>
              <RefreshCw size={13} className={loadingRuns ? "animate-spin" : ""} />
              刷新
            </Button>
            <Button variant="primary" onClick={() => startRun()} disabled={!canRunCompanyAgent || isRunning || !symbol.trim()}>
              {isRunning ? <Loader2 size={14} className="animate-spin" /> : <Play size={14} />}
              起草新研究
            </Button>
          </div>
        </div>
      </div>

      <div className="grid flex-1 min-h-0 grid-cols-1 lg:grid-cols-[320px_minmax(0,1fr)_340px]">
        <aside className="min-h-0 overflow-y-auto border-b border-[var(--line)] lg:border-b-0 lg:border-r">
          <div className="border-b border-[var(--line)] px-7 py-5">
            <div className="mb-4 flex items-center justify-between">
              <div>
                <div className="eyebrow">WATCHLIST</div>
                <div className="mt-1 font-mono text-[10px] text-[var(--ink-faint)]">
                  {filteredWatchItems.length} / {watchItems.length} companies
                </div>
              </div>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => setShowAddWatch((v) => !v)}
                disabled={!canRunCompanyAgent}
              >
                <Plus size={12} /> 添加
              </Button>
            </div>

            <label className="mb-3 flex h-9 items-center gap-2 border border-[var(--line)] bg-[var(--surface)] px-3">
              <Search size={13} className="text-[var(--ink-faint)]" />
              <input
                value={watchSearch}
                onChange={(e) => setWatchSearch(e.target.value)}
                className="min-w-0 flex-1 bg-transparent font-mono text-[11px] text-[var(--ink-soft)] outline-none placeholder:text-[var(--ink-faint)]"
                placeholder="搜索 symbol / sector"
              />
            </label>

            <div className="space-y-2">
              <SegmentedFilter
                value={verdictFilter}
                onChange={(v) => setVerdictFilter(v as "ALL" | WatchVerdict)}
                options={["ALL", "BUY", "WATCH", "AVOID", "UNRATED"]}
              />
              <SegmentedFilter
                value={marketFilter}
                onChange={(v) => setMarketFilter(v as "ALL" | WatchMarket)}
                options={["ALL", "US", "TW", "CN"]}
              />
            </div>

            {showAddWatch && (
              <div className="mt-4 space-y-2 border-t border-[var(--line)] pt-4">
                <input
                  value={newWatchSymbol}
                  onChange={(e) => setNewWatchSymbol(e.target.value.toUpperCase())}
                  className="h-9 w-full border border-[var(--line-strong)] bg-[var(--surface)] px-3 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
                  placeholder="SYMBOL"
                />
                <input
                  value={newWatchName}
                  onChange={(e) => setNewWatchName(e.target.value)}
                  className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-3 text-[12px] text-[var(--ink-soft)] outline-none focus:border-[var(--accent)]"
                  placeholder="Company name"
                />
                <Button size="sm" variant="primary" onClick={addWatchItem} disabled={!newWatchSymbol.trim()}>
                  添加到研究台
                </Button>
              </div>
            )}
          </div>
          <ul className="divide-y divide-[var(--line)]">
            {filteredWatchItems.map((item) => (
              <li key={item.symbol}>
                {/* Slimmer card: vertical rhythm tightened (px-5 py-3 instead
                    of px-7 py-5), name inline next to symbol, meta + verdict
                    folded into one row, two actions (K线 + 起草) stacked right.
                    Density ≈ 60% of the old card. */}
                <div
                  className={cn(
                    "group relative border-l-2 px-5 py-3 transition-colors hover:bg-[var(--surface-hover)]",
                    symbol === item.symbol ? "border-[var(--gain)] bg-[var(--surface-hover)]" : "border-transparent",
                  )}
                >
                  <button
                    type="button"
                    className="block w-full text-left"
                    onClick={() => chooseCompany(item)}
                  >
                    <div className="flex items-baseline gap-2">
                      <span className="font-display text-[18px] italic leading-none text-[var(--ink)]">
                        {item.symbol}
                      </span>
                      <span className="min-w-0 truncate font-display text-[12px] italic text-[var(--ink-muted)]">
                        {item.name}
                      </span>
                    </div>
                    <div className="mt-1.5 flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[9px] tracking-[0.10em] text-[var(--ink-faint)]">
                      <Badge tone={verdictTone(item.verdict)}>{item.verdict}</Badge>
                      <span>{item.market}</span>
                      <span className="truncate">{item.sector}</span>
                      {item.changePct != null && (
                        <span className={item.changePct >= 0 ? "text-[var(--gain)]" : "text-[var(--loss)]"}>
                          {item.changePct >= 0 ? "+" : ""}
                          {item.changePct.toFixed(2)}%
                        </span>
                      )}
                      {item.runs != null && <span>{item.runs}x</span>}
                    </div>
                  </button>
                  {/* Action row — absolute-positioned so it sits on the right
                      without affecting the button's hit-area width. */}
                  <div className="absolute right-3 top-1/2 -translate-y-1/2 flex items-center gap-1.5 opacity-70 group-hover:opacity-100 transition-opacity">
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        setChartItem(item);
                      }}
                      className="inline-flex h-6 w-6 items-center justify-center rounded border border-[var(--line-strong)] text-[var(--ink-muted)] hover:border-[var(--accent-line)] hover:text-[var(--accent)] transition-colors"
                      title={`查看 ${item.symbol} K 线`}
                      aria-label={`查看 ${item.symbol} K 线`}
                    >
                      <CandlestickChart size={12} />
                    </button>
                    {canRunCompanyAgent && (
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          chooseCompany(item, true);
                        }}
                        className="inline-flex h-6 items-center gap-1 border border-[var(--line-strong)] px-2 font-mono text-[9px] text-[var(--ink-muted)] hover:border-[var(--accent-line)] hover:text-[var(--accent)] transition-colors"
                      >
                        起草 <ArrowRight size={10} />
                      </button>
                    )}
                  </div>
                </div>
              </li>
            ))}
            {filteredWatchItems.length === 0 && (
              <li className="px-5 py-6 text-[12px] leading-relaxed text-[var(--ink-muted)]">
                没有匹配的公司。可以清空筛选，或添加一个新的 ticker。
              </li>
            )}
          </ul>
        </aside>

        <main className="min-h-0 overflow-y-auto px-6 py-8 xl:px-10">
          {/* Flex-wrap form bar: SYMBOL is fixed width, PEERS flexes, buttons
              hug right. Below xl (~14" laptops with two side asides) the
              buttons may wrap to the next row — which is fine, the form
              isn't broken into 4 vertical scraps anymore. */}
          <div className="mb-7 flex flex-wrap items-end gap-3">
            <label className="shrink-0">
              <div className="mb-2 whitespace-nowrap font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
                SYMBOL
              </div>
              <input
                value={symbol}
                onChange={(e) => setSymbol(e.target.value.toUpperCase())}
                readOnly={!canRunCompanyAgent}
                className="h-10 w-[140px] border border-[var(--line-strong)] bg-[var(--surface)] px-3 font-display text-[20px] italic text-[var(--ink)] outline-none focus:border-[var(--accent)]"
              />
            </label>
            <div className="min-w-[220px] flex-1">
              <div className="mb-2 whitespace-nowrap font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
                PEERS · MAX 3
              </div>
              <PeerTagInput
                value={peerTags}
                onChange={setPeerTags}
                suggestions={peerSuggestions}
                disabled={!canRunCompanyAgent}
              />
            </div>
            <div className="flex shrink-0 items-end gap-2">
              {isRunning && (
                <Button variant="outline" onClick={() => aborter?.abort()}>
                  <Square size={13} /> 中止
                </Button>
              )}
              <Button variant="primary" onClick={() => startRun()} disabled={!canRunCompanyAgent || isRunning || !symbol.trim()}>
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
                <Link href={`/company-agent/${activeRunId}`} className="ml-auto text-[var(--accent)] hover:underline">
                  查看档案 →
                </Link>
              )}
            </div>
          </section>

          {error && (
            <div className="mt-4 border border-[color-mix(in_srgb,var(--loss)_40%,transparent)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)] px-4 py-3 font-mono text-[11px] text-[var(--loss)]">
              {error}
            </div>
          )}
          {!canRunCompanyAgent && (
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

        <aside className="min-h-0 overflow-y-auto border-t border-[var(--line)] px-7 py-6 lg:border-l lg:border-t-0">
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
                  <Link href={`/company-agent/${run.id}`} className="block py-4 hover:bg-[var(--surface-hover)]">
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
                href={`/company-agent/${latestRun.id}`}
                className="mt-4 inline-flex items-center gap-2 font-mono text-[11px] tracking-[0.08em] text-[var(--accent)] hover:underline"
              >
                <FileText size={13} /> 打开最近档案
              </Link>
            )}
          </div>
        </aside>
      </div>

      {/* TradingView K线 modal — opens when user clicks the chart icon on
          any watchlist card. ESC / click-backdrop / × button to close.
          We unmount the chart on close (TradingView widget owns its DOM,
          re-mounting is the only clean way to swap symbols). */}
      {chartItem && (
        <ChartModal item={chartItem} onClose={() => setChartItem(null)} />
      )}
    </div>
  );
}

function ChartModal({
  item,
  onClose,
}: {
  item: CompanyWatchItem;
  onClose: () => void;
}) {
  const tvSymbol = toTradingViewSymbol(item);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") onClose();
    }
    document.addEventListener("keydown", onKey);
    // Lock body scroll while modal is open
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prev;
    };
  }, [onClose]);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-6 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        className="relative flex h-[640px] max-h-[88vh] w-[1080px] max-w-[92vw] flex-col overflow-hidden rounded-[var(--r-lg)] border border-[var(--line-strong)] bg-[var(--surface)] shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex shrink-0 items-baseline gap-3 border-b border-[var(--line)] px-5 py-3">
          <div className="font-display text-[22px] italic leading-none text-[var(--ink)]">
            {item.symbol}
          </div>
          <div className="font-display text-[13px] italic text-[var(--ink-muted)]">
            {item.name}
          </div>
          <span className="font-mono text-[10px] tracking-[0.10em] text-[var(--ink-faint)]">
            {tvSymbol} · EMA20 · SMA50
          </span>
          <button
            type="button"
            onClick={onClose}
            className="ml-auto inline-flex h-7 w-7 items-center justify-center rounded border border-[var(--line-strong)] text-[var(--ink-muted)] hover:border-[var(--accent-line)] hover:text-[var(--accent)] transition-colors"
            aria-label="关闭 K 线"
          >
            <X size={13} />
          </button>
        </div>
        <div className="min-h-0 flex-1">
          <TradingViewChart symbol={tvSymbol} />
        </div>
      </div>
    </div>
  );
}

function SegmentedFilter({
  value,
  onChange,
  options,
}: {
  value: string;
  onChange: (value: string) => void;
  options: string[];
}) {
  return (
    <div className="flex flex-wrap gap-1">
      {options.map((option) => (
        <button
          key={option}
          type="button"
          onClick={() => onChange(option)}
          className={cn(
            "rounded-sm border px-2 py-1 font-mono text-[9px] tracking-[0.12em] transition-colors",
            value === option
              ? "border-[var(--accent-line)] bg-[var(--accent-soft)] text-[var(--accent)]"
              : "border-[var(--line)] text-[var(--ink-faint)] hover:text-[var(--ink-soft)]",
          )}
        >
          {option}
        </button>
      ))}
    </div>
  );
}

function PeerTagInput({
  value,
  onChange,
  suggestions,
  disabled,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  suggestions: string[];
  disabled?: boolean;
}) {
  const [query, setQuery] = useState("");
  const normalized = value.map((v) => v.toUpperCase());
  const canAddMore = value.length < 3 && !disabled;
  const matches = useMemo(() => {
    const q = query.trim().toUpperCase();
    if (!q || !canAddMore) return [];
    return suggestions
      .filter((symbol) => symbol.includes(q) && !normalized.includes(symbol))
      .slice(0, 5);
  }, [canAddMore, normalized, query, suggestions]);

  function addTag(raw: string) {
    const tag = raw.trim().replace(/,$/, "").toUpperCase();
    if (!tag || disabled || value.length >= 3 || normalized.includes(tag)) return;
    if (!/^[A-Z0-9.]{1,8}$/.test(tag)) return;
    onChange([...value, tag]);
    setQuery("");
  }

  function removeTag(tag: string) {
    if (disabled) return;
    onChange(value.filter((v) => v !== tag));
  }

  return (
    <div>
      <div
        className={cn(
          "flex min-h-10 flex-wrap items-center gap-1.5 border border-[var(--line-strong)] bg-[var(--surface)] px-2 py-1.5",
          !disabled && "focus-within:border-[var(--accent)]",
        )}
      >
        {value.map((tag) => (
          <span
            key={tag}
            className="inline-flex h-7 items-center gap-1 rounded-sm border border-[var(--accent-line)] bg-[var(--accent-soft)] px-2 font-mono text-[11px] tracking-[0.08em] text-[var(--accent)]"
          >
            {tag}
            {!disabled && (
              <button
                type="button"
                onClick={() => removeTag(tag)}
                className="text-[var(--accent)] opacity-70 hover:opacity-100"
                aria-label={`移除 ${tag}`}
              >
                <X size={12} />
              </button>
            )}
          </span>
        ))}
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value.toUpperCase())}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              addTag(query);
            }
            if (e.key === "Backspace" && !query && value.length > 0) {
              onChange(value.slice(0, -1));
            }
          }}
          disabled={!canAddMore}
          className="h-7 min-w-[120px] flex-1 bg-transparent px-1 font-mono text-[12px] text-[var(--ink-soft)] outline-none placeholder:text-[var(--ink-faint)] disabled:min-w-0"
          placeholder={canAddMore ? "搜索或输入 ticker" : ""}
        />
      </div>
      {matches.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {matches.map((match) => (
            <button
              key={match}
              type="button"
              onClick={() => addTag(match)}
              className="rounded-sm border border-[var(--line)] px-2 py-1 font-mono text-[10px] tracking-[0.08em] text-[var(--ink-muted)] hover:border-[var(--accent-line)] hover:text-[var(--accent)]"
            >
              {match}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
