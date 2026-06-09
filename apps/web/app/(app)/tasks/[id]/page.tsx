"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  ExternalLink,
  Loader2,
  RefreshCw,
  Sparkles,
  Square,
  ThumbsDown,
  ThumbsUp,
  XCircle,
} from "lucide-react";
import { PageContainer } from "@/components/ui/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { API_BASE } from "@/lib/api-base";
import { setNewsFeedback, streamNewsAnalyze } from "@/lib/api";
import { authedFetch } from "@/lib/auth";
import { getTrigger, KIND_ICON, KIND_LABEL } from "@/lib/triggers";
import { cn } from "@/lib/cn";

// ─── Types ──────────────────────────────────────────────────────────

interface Tag {
  id: string;
  group_id: string;
  name: string;
  description: string;
  sort_order: number;
  color: string | null;
}

interface TagGroup {
  id: string;
  name: string;
  description: string;
  mode: "single" | "multi" | string;
  sort_order: number;
  tags: Tag[];
}

interface ArticleSummary {
  id: string;
  title: string;
  title_zh: string | null;
  summary: string;
  summary_zh: string | null;
  source: string;
  author: string | null;
  url: string;
  symbols: string[];
  published_at: string;
  impact: string | null;
  ai_analysis_status: string;
  like_count: number;
  dislike_count: number;
  tag_ids: string[];
  my_feedback: "like" | "dislike" | null;
}

interface ArticleListResponse {
  items: ArticleSummary[];
  total: number;
  limit: number;
  offset: number;
}

// ─── Formatting helpers ─────────────────────────────────────────────

function formatTs(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function relativeFromNow(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "刚刚";
  if (seconds < 3600) return `${Math.round(seconds / 60)} 分钟前`;
  if (seconds < 86400) return `${Math.round(seconds / 3600)} 小时前`;
  return `${Math.round(seconds / 86400)} 天前`;
}

// ─── Page ───────────────────────────────────────────────────────────

export default function TriggerDetailPage() {
  const params = useParams<{ id: string }>();
  const triggerId = params.id;
  const trigger = getTrigger(triggerId);

  const [groups, setGroups] = useState<TagGroup[]>([]);
  const [articles, setArticles] = useState<ArticleSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [selectedTagIds, setSelectedTagIds] = useState<Set<string>>(
    () => new Set(),
  );
  const [loadingTaxonomy, setLoadingTaxonomy] = useState(false);
  const [loadingArticles, setLoadingArticles] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Hydrate taxonomy once.
  useEffect(() => {
    setLoadingTaxonomy(true);
    authedFetch(`${API_BASE}/api/tag-groups`, { cache: "no-store" })
      .then(async (r) => {
        if (!r.ok) throw new Error(await r.text());
        return (await r.json()) as TagGroup[];
      })
      .then((data) =>
        setGroups(data.slice().sort((a, b) => a.sort_order - b.sort_order)),
      )
      .catch((e: unknown) => setError(e instanceof Error ? e.message : "load failed"))
      .finally(() => setLoadingTaxonomy(false));
  }, []);

  const [selectedSymbol, setSelectedSymbol] = useState<string | null>(null);

  // Re-fetch articles whenever the filter changes.
  const fetchArticles = useCallback(async () => {
    setLoadingArticles(true);
    setError(null);
    try {
      // Per-ticker mode (trg-news-002): pull a wider window so we can
      // group + filter client-side. Standard mode: 100 is plenty.
      const limit = triggerId === "trg-news-002" ? "1000" : "100";
      const qs = new URLSearchParams({ limit });
      if (selectedTagIds.size > 0) {
        qs.set("tag_ids", Array.from(selectedTagIds).join(","));
      }
      const r = await authedFetch(
        `${API_BASE}/api/triggers/${triggerId}/news?${qs}`,
        { cache: "no-store" },
      );
      if (!r.ok) throw new Error(await r.text());
      const body = (await r.json()) as ArticleListResponse;
      setArticles(body.items);
      setTotal(body.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoadingArticles(false);
    }
  }, [selectedTagIds, triggerId]);

  useEffect(() => {
    void fetchArticles();
  }, [fetchArticles]);

  function toggleTag(tag: Tag, group: TagGroup) {
    setSelectedTagIds((prev) => {
      const next = new Set(prev);
      if (group.mode === "single") {
        // Pull out any other tag from this group, then toggle.
        const groupTagIds = new Set(group.tags.map((t) => t.id));
        const wasSelected = prev.has(tag.id);
        for (const id of prev) {
          if (groupTagIds.has(id)) next.delete(id);
        }
        if (!wasSelected) next.add(tag.id);
      } else {
        if (next.has(tag.id)) next.delete(tag.id);
        else next.add(tag.id);
      }
      return next;
    });
  }

  function clearFilters() {
    setSelectedTagIds(new Set());
  }

  // Build tag-id → tag for quick chip rendering on each article card.
  const tagById = useMemo(() => {
    const map = new Map<string, Tag>();
    for (const g of groups) for (const t of g.tags) map.set(t.id, t);
    return map;
  }, [groups]);

  // Per-ticker mode (trg-news-002): count articles per symbol so the
  // sidebar can show "AAPL 142" / "NVDA 134" etc., and filter the feed
  // when a symbol is picked.
  const isPerTicker = triggerId === "trg-news-002";
  const symbolCounts = useMemo(() => {
    if (!isPerTicker) return new Map<string, number>();
    const counts = new Map<string, number>();
    for (const a of articles) {
      for (const s of a.symbols) {
        counts.set(s, (counts.get(s) ?? 0) + 1);
      }
    }
    return counts;
  }, [articles, isPerTicker]);
  const orderedSymbols = useMemo(
    () => Array.from(symbolCounts.entries()).sort((a, b) => b[1] - a[1]),
    [symbolCounts],
  );
  const articlesShownInFeed = useMemo(
    () =>
      isPerTicker && selectedSymbol
        ? articles.filter((a) => a.symbols.includes(selectedSymbol))
        : articles,
    [articles, isPerTicker, selectedSymbol],
  );

  // Auto-select most-recent ticker on first load (only in per-ticker mode).
  useEffect(() => {
    if (isPerTicker && !selectedSymbol && orderedSymbols.length > 0) {
      setSelectedSymbol(orderedSymbols[0][0]);
    }
  }, [isPerTicker, orderedSymbols, selectedSymbol]);

  if (!trigger) {
    return (
      <PageContainer>
        <div className="rounded-md border border-[var(--line)] bg-[var(--surface)] p-6 text-[13px] text-[var(--ink-muted)]">
          <div className="font-display text-[18px] italic text-[var(--ink)]">
            未找到 trigger
          </div>
          <p className="mt-2">ID: {triggerId}</p>
          <Link
            href="/tasks"
            className="mt-4 inline-flex items-center gap-1 text-[12px] text-[var(--accent)] hover:underline"
          >
            <ArrowLeft size={12} /> 返回 trigger 列表
          </Link>
        </div>
      </PageContainer>
    );
  }

  const Icon = KIND_ICON[trigger.kind];

  // Viewport-locked layout: header strip at top stays put, left aside is
  // fixed in viewport (filter + calendar always visible), only the right
  // main column scrolls. Matches the /company-agent shell pattern.
  return (
    <div className="flex h-screen flex-col overflow-hidden paper-grain">
      {/* Header strip — non-scrolling. Compact PageHeader-style layout
          plus the trigger meta inline so the top doesn't eat too much
          vertical space (4 rows of meta + 3 lines of header = too tall). */}
      <div className="shrink-0 border-b border-[var(--line)] px-8 py-5">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <div className="min-w-0">
            <div className="eyebrow mb-2">
              TRIGGER · {KIND_LABEL[trigger.kind].toUpperCase()}
            </div>
            <div className="flex items-center gap-3">
              <span
                className={cn(
                  "inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-md border",
                  trigger.enabled
                    ? "border-[var(--accent-line)] bg-[var(--accent-soft)] text-[var(--accent)]"
                    : "border-[var(--line)] text-[var(--ink-faint)]",
                )}
              >
                <Icon size={15} />
              </span>
              <h1 className="font-display text-[26px] italic leading-none text-[var(--ink)]">
                {trigger.name}
              </h1>
              <Badge tone={trigger.enabled ? "gain" : "neutral"}>
                {trigger.enabled ? "listening" : "paused"}
              </Badge>
              <Badge>{trigger.skill}</Badge>
            </div>
            <div className="mt-2 max-w-3xl text-[12px] leading-relaxed text-[var(--ink-muted)]">
              {trigger.condition} · <span className="text-[var(--ink-faint)]">{trigger.cadence}</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Link
              href="/tasks"
              className="inline-flex items-center gap-1 font-mono text-[11px] tracking-[0.05em] text-[var(--ink-muted)] hover:text-[var(--ink)]"
            >
              <ArrowLeft size={12} /> 全部 trigger
            </Link>
            <Button variant="ghost" onClick={fetchArticles} disabled={loadingArticles}>
              <RefreshCw
                size={13}
                className={loadingArticles ? "animate-spin" : ""}
              />
              刷新
            </Button>
          </div>
        </div>
      </div>

      {/* Body: fixed-width aside (no scroll on the column itself, internal
          scroll if filter is super tall) + flexible main with its own
          scrollbar so long feeds don't push the aside out of view. */}
      <div className="grid min-h-0 flex-1 grid-cols-1 lg:grid-cols-[280px_minmax(0,1fr)]">
        {/* Filter rail — fixed in viewport */}
        <aside className="min-h-0 overflow-y-auto border-r border-[var(--line)] px-6 py-5 lg:border-b-0">
          <div className="space-y-5">
            {isPerTicker && orderedSymbols.length > 0 && (
              <TickerRail
                symbols={orderedSymbols}
                selected={selectedSymbol}
                onPick={setSelectedSymbol}
              />
            )}
            {articlesShownInFeed.length > 0 && (
              <MiniDensityCalendar
                articles={articlesShownInFeed}
                onPickDate={(date) => {
                  const target = articlesShownInFeed.find((a) =>
                    a.published_at.startsWith(date),
                  );
                  if (target) {
                    document
                      .getElementById(`article-${target.id}`)
                      ?.scrollIntoView({ behavior: "smooth", block: "start" });
                  }
                }}
              />
            )}
            <div className="flex items-center justify-between">
              <div className="eyebrow">FILTER</div>
              {selectedTagIds.size > 0 && (
                <button
                  type="button"
                  onClick={clearFilters}
                  className="inline-flex items-center gap-1 font-mono text-[10px] tracking-[0.05em] text-[var(--ink-muted)] hover:text-[var(--accent)]"
                >
                  <XCircle size={11} />
                  清空 ({selectedTagIds.size})
                </button>
              )}
            </div>
            {loadingTaxonomy && (
              <div className="flex items-center gap-2 text-[11px] text-[var(--ink-muted)]">
                <Loader2 size={12} className="animate-spin" /> loading taxonomy…
              </div>
            )}
            {groups.map((group) => (
              <FilterGroup
                key={group.id}
                group={group}
                selectedIds={selectedTagIds}
                onToggle={(tag) => toggleTag(tag, group)}
              />
            ))}
            {!loadingTaxonomy && groups.length === 0 && (
              <p className="text-[11px] leading-relaxed text-[var(--ink-faint)]">
                还没有标签 taxonomy。
                <Link
                  href="/admin/tags"
                  className="ml-1 text-[var(--accent)] hover:underline"
                >
                  去管理 →
                </Link>
              </p>
            )}
          </div>
        </aside>

        {/* News feed — own scrollbar */}
        <main className="min-h-0 overflow-y-auto px-6 py-5 xl:px-8">
          <div className="mb-3 flex items-center justify-between font-mono text-[10px] tracking-[0.08em] text-[var(--ink-faint)]">
            <span>
              {isPerTicker && selectedSymbol
                ? `${articlesShownInFeed.length} / ${total} articles · ${selectedSymbol}`
                : `${total} articles`}
            </span>
            {selectedTagIds.size > 0 && (
              <span>filtered by {selectedTagIds.size} tag(s)</span>
            )}
          </div>
          {error && (
            <div className="mb-3 border border-[color-mix(in_srgb,var(--loss)_40%,transparent)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)] px-4 py-3 font-mono text-[11px] text-[var(--loss)]">
              {error}
            </div>
          )}
          {loadingArticles && articles.length === 0 && (
            <div className="flex h-32 items-center justify-center text-[12px] text-[var(--ink-muted)]">
              <Loader2 size={14} className="mr-2 animate-spin" />
              loading…
            </div>
          )}
          {!loadingArticles && articles.length === 0 && (
            <Card>
              <CardBody className="py-10 text-center text-[12px] text-[var(--ink-muted)]">
                {selectedTagIds.size > 0
                  ? "当前筛选没有匹配的新闻。试试清空筛选或换一组 tag。"
                  : "这个 trigger 还没有命中过任何新闻。"}
              </CardBody>
            </Card>
          )}
          <div className="space-y-3">
            {articlesShownInFeed.map((article) => (
              <ArticleCard
                key={article.id}
                article={article}
                tagById={tagById}
                onPatch={(patch) =>
                  setArticles((prev) =>
                    prev.map((a) => (a.id === article.id ? { ...a, ...patch } : a)),
                  )
                }
              />
            ))}
          </div>
        </main>
      </div>
    </div>
  );
}

// ─── Subcomponents ──────────────────────────────────────────────────

function Meta({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
        {label}
      </div>
      <div className="text-[12px] text-[var(--ink-soft)]">{children}</div>
    </div>
  );
}

function TickerRail({
  symbols,
  selected,
  onPick,
}: {
  symbols: [string, number][]; // [symbol, count]
  selected: string | null;
  onPick: (symbol: string) => void;
}) {
  const total = symbols.reduce((sum, [, c]) => sum + c, 0);
  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <div className="eyebrow">公司</div>
        <span className="font-mono text-[9px] tracking-[0.1em] text-[var(--ink-faint)]">
          {symbols.length} tickers · {total}
        </span>
      </div>
      <ul className="space-y-px">
        {symbols.map(([sym, count]) => {
          const active = sym === selected;
          return (
            <li key={sym}>
              <button
                type="button"
                onClick={() => onPick(sym)}
                className={cn(
                  "flex w-full items-baseline justify-between rounded-sm border-l-2 px-2 py-1.5 transition-colors",
                  active
                    ? "border-[var(--accent)] bg-[var(--accent-soft)]"
                    : "border-transparent hover:bg-[var(--surface-hover)]",
                )}
              >
                <span
                  className={cn(
                    "font-display text-[14px] italic leading-none",
                    active ? "text-[var(--accent)]" : "text-[var(--ink)]",
                  )}
                >
                  {sym}
                </span>
                <span className="font-mono text-[10px] tracking-[0.05em] text-[var(--ink-faint)]">
                  {count}
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function FilterGroup({
  group,
  selectedIds,
  onToggle,
}: {
  group: TagGroup;
  selectedIds: Set<string>;
  onToggle: (tag: Tag) => void;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline justify-between">
        <div className="font-display text-[14px] italic text-[var(--ink)]">
          {group.name}
        </div>
        <span className="font-mono text-[9px] tracking-[0.1em] text-[var(--ink-faint)]">
          {group.mode === "single" ? "单选" : "多选"}
        </span>
      </div>
      {group.description && (
        <div className="mb-2 text-[11px] leading-relaxed text-[var(--ink-muted)]">
          {group.description}
        </div>
      )}
      <div className="flex flex-wrap gap-1.5">
        {group.tags.map((tag) => {
          const active = selectedIds.has(tag.id);
          return (
            <button
              key={tag.id}
              type="button"
              onClick={() => onToggle(tag)}
              title={tag.description || undefined}
              className={cn(
                "rounded-sm border px-2.5 py-1 font-mono text-[10px] tracking-[0.04em] transition-colors",
                active
                  ? "border-[var(--accent-line)] bg-[var(--accent-soft)] text-[var(--accent)]"
                  : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink-soft)]",
              )}
            >
              {tag.name}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function ArticleCard({
  article,
  tagById,
  onPatch,
}: {
  article: ArticleSummary;
  tagById: Map<string, Tag>;
  onPatch: (patch: Partial<ArticleSummary>) => void;
}) {
  const articleTags = article.tag_ids
    .map((id) => tagById.get(id))
    .filter((t): t is Tag => Boolean(t));

  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeText, setAnalyzeText] = useState("");
  const [analyzeImpact, setAnalyzeImpact] = useState<string | null>(article.impact);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [aborter, setAborter] = useState<AbortController | null>(null);
  const [feedbackPending, setFeedbackPending] = useState(false);
  const expanded = analyzing || analyzeText.length > 0 || analyzeError !== null;

  async function vote(kind: "like" | "dislike") {
    // Toggle: clicking the active vote clears it.
    const next = article.my_feedback === kind ? null : kind;
    setFeedbackPending(true);
    try {
      const result = await setNewsFeedback(article.id, next);
      onPatch({
        my_feedback: result.my_feedback,
        like_count: result.like_count,
        dislike_count: result.dislike_count,
      });
    } catch {
      // Swallow — keep UI responsive; user can retry.
    } finally {
      setFeedbackPending(false);
    }
  }

  async function runAnalyze() {
    setAnalyzeText("");
    setAnalyzeError(null);
    setAnalyzing(true);
    const controller = new AbortController();
    setAborter(controller);
    try {
      for await (const event of streamNewsAnalyze(article.id, controller.signal)) {
        if (event.type === "delta") {
          setAnalyzeText((prev) => prev + event.content);
        } else if (event.type === "done") {
          setAnalyzeImpact(event.impact);
          if (event.analysis) setAnalyzeText(event.analysis);
        } else if (event.type === "error") {
          setAnalyzeError(event.message);
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") {
        setAnalyzeError(e instanceof Error ? e.message : "stream failed");
      }
    } finally {
      setAnalyzing(false);
      setAborter(null);
    }
  }

  function stopAnalyze() {
    aborter?.abort();
  }

  return (
    <Card className="overflow-hidden scroll-mt-6" as="article">
      <div id={`article-${article.id}`} />
      <CardHeader>
        <div className="flex flex-wrap items-start gap-3">
          <div className="min-w-0 flex-1">
            {article.title_zh && (
              <div className="font-display text-[18px] italic leading-snug text-[var(--ink)]">
                {article.title_zh}
              </div>
            )}
            <div
              className={cn(
                "font-mono leading-snug",
                article.title_zh
                  ? "mt-1 text-[11px] tracking-[0.02em] text-[var(--ink-muted)]"
                  : "text-[14px] text-[var(--ink)]",
              )}
            >
              {article.title}
            </div>
          </div>
          {article.impact && (
            <Badge tone={impactTone(article.impact)}>{article.impact}</Badge>
          )}
        </div>
        <div className="mt-2 flex flex-wrap items-center gap-3 font-mono text-[10px] tracking-[0.05em] text-[var(--ink-faint)]">
          <span>{article.source.toUpperCase()}</span>
          <span>·</span>
          <span title={article.published_at}>{relativeFromNow(article.published_at)}</span>
          <span>·</span>
          <span>{formatTs(article.published_at)}</span>
          {article.url && !article.url.startsWith("demo://") && (
            <>
              <span>·</span>
              <a
                href={article.url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[var(--ink-muted)] hover:text-[var(--accent)]"
              >
                外链 <ExternalLink size={9} />
              </a>
            </>
          )}
        </div>
      </CardHeader>
      <CardBody>
        {article.summary_zh && (
          <p className="text-[13px] leading-relaxed text-[var(--ink-soft)]">
            {article.summary_zh}
          </p>
        )}
        {article.summary && (
          <p
            className={cn(
              "leading-relaxed",
              article.summary_zh
                ? "mt-2 text-[11px] text-[var(--ink-muted)]"
                : "text-[13px] text-[var(--ink-soft)]",
            )}
          >
            {article.summary}
          </p>
        )}

        <div className="mt-3 flex flex-wrap items-center gap-2">
          {article.symbols.map((symbol) => (
            <span
              key={symbol}
              className="numeric inline-flex items-center rounded-sm border border-[var(--line)] bg-[var(--surface)] px-2 py-0.5 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-soft)]"
            >
              {symbol}
            </span>
          ))}
          <span className="grow" />
          {articleTags.map((t) => (
            <span
              key={t.id}
              className="inline-flex items-center rounded-sm border border-[var(--line)] bg-[var(--surface)] px-2 py-0.5 font-mono text-[10px] tracking-[0.04em]"
              style={t.color ? { color: t.color, borderColor: t.color } : undefined}
              title={t.description || undefined}
            >
              {t.name}
            </span>
          ))}
          <FeedbackButton
            kind="like"
            active={article.my_feedback === "like"}
            count={article.like_count}
            pending={feedbackPending}
            onClick={() => vote("like")}
          />
          <FeedbackButton
            kind="dislike"
            active={article.my_feedback === "dislike"}
            count={article.dislike_count}
            pending={feedbackPending}
            onClick={() => vote("dislike")}
          />
          <Button
            size="sm"
            variant="ghost"
            onClick={() => (analyzing ? stopAnalyze() : runAnalyze())}
          >
            {analyzing ? (
              <>
                <Square size={11} /> 中止
              </>
            ) : analyzeText ? (
              <>
                <Sparkles size={11} /> 重新分析
              </>
            ) : (
              <>
                <Sparkles size={11} /> AI 分析
              </>
            )}
          </Button>
        </div>

        {expanded && (
          <div
            className="mt-4 overflow-hidden border-t border-[var(--line)] pt-3"
            style={{ animation: "label-in 220ms var(--ease-out) both" }}
          >
            <div className="mb-2 flex items-center gap-2">
              <span className="eyebrow">AI ANALYSIS</span>
              {analyzing && (
                <Loader2 size={11} className="animate-spin text-[var(--ink-muted)]" />
              )}
              {!analyzing && analyzeImpact && (
                <Badge tone={impactTone(analyzeImpact)}>{analyzeImpact}</Badge>
              )}
            </div>
            {analyzeError ? (
              <div className="font-mono text-[11px] text-[var(--loss)]">
                {analyzeError}
              </div>
            ) : (
              <div className="whitespace-pre-wrap text-[12.5px] leading-relaxed text-[var(--ink-soft)]">
                {analyzeText || (analyzing ? "…" : "")}
              </div>
            )}
          </div>
        )}
      </CardBody>
    </Card>
  );
}

function impactTone(impact: string): "gain" | "loss" | "warn" | "neutral" {
  if (impact === "positive") return "gain";
  if (impact === "negative") return "loss";
  if (impact === "neutral") return "neutral";
  return "warn";
}

function FeedbackButton({
  kind,
  active,
  count,
  pending,
  onClick,
}: {
  kind: "like" | "dislike";
  active: boolean;
  count: number;
  pending: boolean;
  onClick: () => void;
}) {
  const Icon = kind === "like" ? ThumbsUp : ThumbsDown;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={pending}
      title={kind === "like" ? "有帮助" : "不准确 / 没价值"}
      className={cn(
        "inline-flex h-7 items-center gap-1 rounded-sm border px-2 font-mono text-[10px] tracking-[0.04em] transition-colors",
        active
          ? kind === "like"
            ? "border-[color-mix(in_srgb,var(--gain)_50%,transparent)] bg-[color-mix(in_srgb,var(--gain)_8%,transparent)] text-[var(--gain)]"
            : "border-[color-mix(in_srgb,var(--loss)_50%,transparent)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)] text-[var(--loss)]"
          : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink-soft)]",
        pending && "opacity-50",
      )}
    >
      <Icon size={11} />
      {count > 0 && <span>{count}</span>}
    </button>
  );
}

// ─── Mini calendar (article density) ─────────────────────────────────

/** Compact density grid showing the last 28 days of article volume.
 *  Each cell is colored by article count for that day; dots flag the
 *  highest-impact article on that day. Click → scroll feed to first
 *  article from that date. Decorative — doesn't filter, just navigates. */
function MiniDensityCalendar({
  articles,
  onPickDate,
}: {
  articles: ArticleSummary[];
  onPickDate: (date: string) => void;
}) {
  const byDate = useMemo(() => {
    const map = new Map<string, { count: number; topImpact: string | null }>();
    for (const a of articles) {
      const day = a.published_at.slice(0, 10);
      const cur = map.get(day) ?? { count: 0, topImpact: null };
      cur.count += 1;
      // critical (negative) > high (positive) > low — rough ordering for color
      if (!cur.topImpact || rankImpact(a.impact) > rankImpact(cur.topImpact)) {
        cur.topImpact = a.impact;
      }
      map.set(day, cur);
    }
    return map;
  }, [articles]);

  const today = new Date();
  const days: { iso: string; label: number; count: number; topImpact: string | null }[] = [];
  for (let i = 27; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const iso = d.toISOString().slice(0, 10);
    const stat = byDate.get(iso);
    days.push({
      iso,
      label: d.getDate(),
      count: stat?.count ?? 0,
      topImpact: stat?.topImpact ?? null,
    });
  }

  return (
    <div>
      <div className="mb-2 flex items-baseline justify-between">
        <div className="eyebrow">DENSITY · 28D</div>
        <span className="font-mono text-[9px] tracking-[0.1em] text-[var(--ink-faint)]">
          {articles.length} hits
        </span>
      </div>
      <div className="grid grid-cols-7 gap-[3px]">
        {days.map((d) => (
          <button
            key={d.iso}
            type="button"
            onClick={() => d.count > 0 && onPickDate(d.iso)}
            disabled={d.count === 0}
            title={`${d.iso} — ${d.count} 篇`}
            className={cn(
              "group relative aspect-square rounded-[3px] border transition-all",
              d.count === 0
                ? "border-[var(--line)] bg-[var(--surface)] opacity-40"
                : "border-[var(--line-strong)] hover:scale-110 cursor-pointer",
            )}
            style={
              d.count > 0
                ? {
                    backgroundColor: densityColor(d.count, d.topImpact),
                  }
                : undefined
            }
          >
            <span className="absolute inset-0 flex items-center justify-center font-mono text-[8px] tracking-[0.02em] text-[var(--ink-faint)] group-hover:text-[var(--ink-soft)]">
              {d.label}
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}

function rankImpact(impact: string | null): number {
  if (impact === "negative") return 3;
  if (impact === "positive") return 2;
  if (impact === "neutral") return 1;
  return 0;
}

function densityColor(count: number, impact: string | null): string {
  // Hue from impact, alpha from count.
  const base =
    impact === "negative"
      ? "176, 82, 74"
      : impact === "positive"
        ? "111, 175, 141"
        : "109, 164, 199";
  const alpha = Math.min(0.18 + count * 0.18, 0.65);
  return `rgba(${base}, ${alpha})`;
}
