"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Loader2,
  Play,
  RefreshCw,
} from "lucide-react";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import { API_BASE } from "@/lib/api-base";
import { authedFetch } from "@/lib/auth";
import { cn } from "@/lib/cn";

interface SearchStrategy {
  name: string;
  label: string;
  configured: boolean;
  in_chain: boolean;
  use_case: string;
  cost_note: string | null;
  config_note: string | null;
}

interface CompareHit {
  title: string;
  url: string;
  snippet: string;
  source: string;
}

interface CompareStrategy {
  name: string;
  ok: boolean;
  elapsed_ms: number;
  items: CompareHit[];
  error: string | null;
}

interface CompareResponse {
  query: string;
  results: CompareStrategy[];
}

// Seed queries chosen for fisher_qa gate 2 blind spots — they target the
// dimensions where the LLM keeps scoring 0 because the evidence pipeline
// doesn't have the data. Useful as one-click "does this backend solve
// our actual problem" probes.
const SEED_QUERIES: { label: string; query: string }[] = [
  { label: "Q14 · 财报 transcript", query: "Alphabet Q4 2025 earnings call transcript management commentary" },
  { label: "Q7 · 雇员评价", query: "Apple AAPL Glassdoor employee review 2025" },
  { label: "Q9 · 接班梯队", query: "Nvidia executive succession plan named officers DEF 14A" },
  { label: "Q4 · 销售组织", query: "Tesla sales organization direct delivery channel partner" },
];

export default function AdminToolsPage() {
  const [strategies, setStrategies] = useState<SearchStrategy[]>([]);
  const [loadingList, setLoadingList] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Compare form state
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<Set<string>>(
    () => new Set(["vertex_grounding", "google_cse", "ddgs"]),
  );
  const [limit, setLimit] = useState(3);
  const [running, setRunning] = useState(false);
  const [compareResult, setCompareResult] = useState<CompareResponse | null>(null);
  const [compareError, setCompareError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoadingList(true);
    setError(null);
    try {
      const r = await authedFetch(`${API_BASE}/api/admin/search/strategies`);
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      setStrategies(await r.json());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingList(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const togglePick = (name: string) => {
    setPicked((cur) => {
      const next = new Set(cur);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const runCompare = useCallback(async () => {
    if (!query.trim() || picked.size === 0) return;
    setRunning(true);
    setCompareError(null);
    setCompareResult(null);
    try {
      const r = await authedFetch(`${API_BASE}/api/admin/search/compare`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          query: query.trim(),
          strategies: Array.from(picked),
          limit,
        }),
      });
      if (!r.ok) {
        const text = await r.text().catch(() => "");
        throw new Error(text || `HTTP ${r.status}`);
      }
      setCompareResult(await r.json());
    } catch (e) {
      setCompareError(e instanceof Error ? e.message : String(e));
    } finally {
      setRunning(false);
    }
  }, [query, picked, limit]);

  const pickableNames = useMemo(
    () => strategies.map((s) => s.name),
    [strategies],
  );

  return (
    <PageContainer>
      <PageHeader
        title="工具配置"
        subtitle="可切换的搜索后端,以及同一 query 在多后端上的并排对比。"
        actions={
          <Button variant="ghost" size="sm" onClick={() => void refresh()}>
            <RefreshCw size={13} className={loadingList ? "animate-spin" : ""} />
            刷新
          </Button>
        }
      />

      <section className="mb-8">
        <h2 className="mb-3 font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--ink-faint)]">
          网页搜索 · web_search
        </h2>
        {error && (
          <div className="mb-3 rounded-[var(--r)] border border-[color-mix(in_srgb,var(--loss)_40%,transparent)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)] p-3 text-[12px] text-[var(--loss)]">
            {error}
          </div>
        )}
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
          {strategies.map((s) => (
            <StrategyCard key={s.name} strategy={s} />
          ))}
        </div>
      </section>

      <section>
        <h2 className="mb-3 font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--ink-faint)]">
          对比测试
        </h2>
        <Card>
          <CardBody className="space-y-3">
            <div>
              <label className="mb-1 block font-mono text-[10px] tracking-[0.14em] uppercase text-[var(--ink-faint)]">
                Query
              </label>
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="输入搜索关键词,或点下方种子查询"
                className="w-full rounded-sm border border-[var(--line)] bg-[var(--canvas)] px-3 py-2 text-[13px] outline-none focus:border-[var(--accent)]"
                disabled={running}
              />
              <div className="mt-2 flex flex-wrap gap-1">
                {SEED_QUERIES.map((s) => (
                  <button
                    key={s.label}
                    type="button"
                    onClick={() => setQuery(s.query)}
                    disabled={running}
                    className="rounded-sm border border-[var(--line)] px-2 py-[2px] font-mono text-[10px] tracking-[0.05em] text-[var(--ink-muted)] hover:border-[var(--accent-line)] hover:text-[var(--accent)] disabled:opacity-40"
                  >
                    {s.label}
                  </button>
                ))}
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[10px] tracking-[0.14em] uppercase text-[var(--ink-faint)]">
                策略
              </span>
              {pickableNames.map((name) => {
                const s = strategies.find((x) => x.name === name);
                const active = picked.has(name);
                const usable = s?.configured ?? false;
                return (
                  <button
                    key={name}
                    type="button"
                    onClick={() => togglePick(name)}
                    disabled={running || !usable}
                    title={!usable ? s?.config_note ?? "" : ""}
                    className={cn(
                      "rounded-sm border px-2 py-[3px] font-mono text-[10px] tracking-[0.05em] transition-colors",
                      active && usable
                        ? "border-[var(--accent-line)] bg-[var(--accent-soft)] text-[var(--accent)]"
                        : "border-[var(--line)] text-[var(--ink-muted)] hover:border-[var(--accent-line)]",
                      !usable && "opacity-40",
                    )}
                  >
                    {name}
                  </button>
                );
              })}
              <div className="ml-auto flex items-center gap-2">
                <label className="font-mono text-[10px] tracking-[0.14em] uppercase text-[var(--ink-faint)]">
                  Limit
                </label>
                <input
                  type="number"
                  min={1}
                  max={10}
                  value={limit}
                  onChange={(e) => setLimit(Math.min(10, Math.max(1, parseInt(e.target.value) || 3)))}
                  className="w-14 rounded-sm border border-[var(--line)] bg-[var(--canvas)] px-2 py-1 text-[12px] outline-none focus:border-[var(--accent)]"
                  disabled={running}
                />
                <Button
                  size="sm"
                  onClick={() => void runCompare()}
                  disabled={running || !query.trim() || picked.size === 0}
                >
                  {running ? <Loader2 size={13} className="animate-spin" /> : <Play size={13} />}
                  {running ? "运行中…" : "Run"}
                </Button>
              </div>
            </div>
          </CardBody>
        </Card>

        {compareError && (
          <div className="mt-3 rounded-[var(--r)] border border-[color-mix(in_srgb,var(--loss)_40%,transparent)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)] p-3 text-[12px] text-[var(--loss)]">
            {compareError}
          </div>
        )}

        {compareResult && (
          <div className="mt-4">
            <div className="mb-2 font-mono text-[10px] tracking-[0.14em] uppercase text-[var(--ink-faint)]">
              结果 · query: <span className="text-[var(--ink-soft)] normal-case">&ldquo;{compareResult.query}&rdquo;</span>
            </div>
            <div
              className="grid gap-3"
              style={{
                gridTemplateColumns: `repeat(${Math.min(compareResult.results.length, 4)}, minmax(0, 1fr))`,
              }}
            >
              {compareResult.results.map((r) => (
                <CompareColumn key={r.name} result={r} />
              ))}
            </div>
          </div>
        )}
      </section>
    </PageContainer>
  );
}

function StrategyCard({ strategy }: { strategy: SearchStrategy }) {
  return (
    <Card>
      <CardBody className="space-y-2">
        <div className="flex items-start justify-between gap-2">
          <div>
            <div className="font-display text-[15px] italic text-[var(--ink)]">{strategy.label}</div>
            <div className="font-mono text-[10px] tracking-[0.06em] text-[var(--ink-faint)]">
              {strategy.name}
            </div>
          </div>
          <div className="flex flex-col items-end gap-1">
            {strategy.configured ? (
              <Badge tone="gain">
                <CheckCircle2 size={9} />
                配置OK
              </Badge>
            ) : (
              <Badge tone="warn">
                <AlertTriangle size={9} />
                未配置
              </Badge>
            )}
            {strategy.in_chain && <Badge tone="accent">in chain</Badge>}
          </div>
        </div>
        <p className="text-[12px] leading-relaxed text-[var(--ink-soft)]">{strategy.use_case}</p>
        <div className="flex items-center justify-between gap-2 pt-1 text-[11px]">
          <span className="font-mono text-[10px] text-[var(--ink-muted)]">
            {strategy.cost_note ?? ""}
          </span>
          {strategy.config_note && (
            <span className="font-mono text-[10px] text-[var(--warn)]">
              {strategy.config_note}
            </span>
          )}
        </div>
      </CardBody>
    </Card>
  );
}

function CompareColumn({ result }: { result: CompareStrategy }) {
  return (
    <Card className="overflow-hidden">
      <div className="border-b border-[var(--line)] bg-[var(--canvas-soft)] px-3 py-2">
        <div className="flex items-center justify-between gap-2">
          <div className="font-mono text-[11px] font-semibold tracking-[0.06em] text-[var(--ink)]">
            {result.name}
          </div>
          <div className="flex items-center gap-2 font-mono text-[10px] text-[var(--ink-muted)]">
            <span>{result.elapsed_ms}ms</span>
            {result.ok ? (
              <Badge tone="gain">OK · {result.items.length}</Badge>
            ) : (
              <Badge tone="loss">FAIL</Badge>
            )}
          </div>
        </div>
        {result.error && (
          <div className="mt-1 font-mono text-[10px] leading-snug text-[var(--loss)]">
            {result.error}
          </div>
        )}
      </div>
      <CardBody className="space-y-2 p-3">
        {result.items.length === 0 && !result.error && (
          <div className="font-mono text-[10px] italic text-[var(--ink-faint)]">无结果</div>
        )}
        {result.items.map((hit, i) => (
          <div key={i} className="border-b border-[var(--line-soft)] pb-2 last:border-0 last:pb-0">
            <a
              href={hit.url || undefined}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-start gap-1 text-[12px] leading-snug text-[var(--ink)] hover:text-[var(--accent)]"
            >
              <span>{hit.title || "(no title)"}</span>
              <ExternalLink size={10} className="mt-[3px] shrink-0 opacity-50" />
            </a>
            <div className="mt-[2px] font-mono text-[10px] text-[var(--ink-faint)]">
              {hit.source}
            </div>
            {hit.snippet && (
              <div className="mt-1 line-clamp-3 text-[11px] leading-snug text-[var(--ink-muted)]">
                {hit.snippet}
              </div>
            )}
          </div>
        ))}
      </CardBody>
    </Card>
  );
}
