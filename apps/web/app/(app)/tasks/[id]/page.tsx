"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import {
  ArrowLeft,
  ExternalLink,
  Loader2,
  RefreshCw,
  XCircle,
} from "lucide-react";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { API_BASE } from "@/lib/api-base";
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

  // Re-fetch articles whenever the filter changes.
  const fetchArticles = useCallback(async () => {
    setLoadingArticles(true);
    setError(null);
    try {
      const qs = new URLSearchParams({ limit: "100" });
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

  return (
    <PageContainer>
      <PageHeader
        eyebrow={`TRIGGER · ${KIND_LABEL[trigger.kind].toUpperCase()}`}
        title={trigger.name}
        subtitle={trigger.condition}
        actions={
          <>
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
          </>
        }
      />

      {/* Trigger meta strip */}
      <Card className="mb-6">
        <CardBody className="grid gap-4 md:grid-cols-4">
          <Meta label="AGENT">
            <Badge>{trigger.skill}</Badge>
          </Meta>
          <Meta label="CADENCE">{trigger.cadence}</Meta>
          <Meta label="STATUS">
            <Badge tone={trigger.enabled ? "gain" : "neutral"}>
              {trigger.enabled ? "listening" : "paused"}
            </Badge>
          </Meta>
          <Meta label="ICON">
            <span
              className={cn(
                "inline-flex h-7 w-7 items-center justify-center rounded-md border",
                trigger.enabled
                  ? "border-[var(--accent-line)] bg-[var(--accent-soft)] text-[var(--accent)]"
                  : "border-[var(--line)] text-[var(--ink-faint)]",
              )}
            >
              <Icon size={14} />
            </span>
          </Meta>
        </CardBody>
      </Card>

      <div className="grid gap-6 lg:grid-cols-[260px_minmax(0,1fr)]">
        {/* Filter rail */}
        <aside className="space-y-4">
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
        </aside>

        {/* News feed */}
        <main className="space-y-3">
          <div className="flex items-center justify-between font-mono text-[10px] tracking-[0.08em] text-[var(--ink-faint)]">
            <span>{total} articles</span>
            {selectedTagIds.size > 0 && <span>filtered by {selectedTagIds.size} tag(s)</span>}
          </div>
          {error && (
            <div className="border border-[color-mix(in_srgb,var(--loss)_40%,transparent)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)] px-4 py-3 font-mono text-[11px] text-[var(--loss)]">
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
          {articles.map((article) => (
            <ArticleCard
              key={article.id}
              article={article}
              tagById={tagById}
            />
          ))}
        </main>
      </div>
    </PageContainer>
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
}: {
  article: ArticleSummary;
  tagById: Map<string, Tag>;
}) {
  const articleTags = article.tag_ids
    .map((id) => tagById.get(id))
    .filter((t): t is Tag => Boolean(t));

  return (
    <Card className="overflow-hidden">
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
        </div>
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
