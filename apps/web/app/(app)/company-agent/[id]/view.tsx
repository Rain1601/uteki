"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  CheckCircle2,
  Database,
  ExternalLink,
  FileText,
  Filter,
  GitCompare,
  ShieldCheck,
  XCircle,
  Workflow,
} from "lucide-react";
import { Artifacts } from "@/components/agent/Artifacts";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import type { ArtifactRef, RunDetail } from "@/lib/api";
import { artifactUrl, fetchArtifactText, getRun, listRuns } from "@/lib/api";
import { cn } from "@/lib/cn";

type Tone = "gain" | "loss" | "warn" | "neutral";
type SourceFilter = "cited" | "all" | "high" | "low" | "news";

interface DecisionArtifact {
  schema_version?: string;
  symbol?: string;
  action?: string;
  conviction?: number;
  target_rank?: number | null;
  initial_position_pct?: number | null;
  max_position_pct?: number | null;
  quality_verdict?: string;
  real_order_execution?: boolean;
}

interface CapitalPlanArtifact {
  schema_version?: string;
  symbol?: string;
  action?: string;
  initial_position_pct?: number;
  max_position_pct?: number;
  real_order_execution?: boolean;
  add_triggers?: string[];
  trim_triggers?: string[];
  sell_triggers?: string[];
}

interface RankingCompany {
  symbol?: string;
  rank?: number;
  role?: string;
  scores?: {
    total?: number;
    quality?: number;
    growth?: number;
    moat?: number;
    valuation?: number;
    risk?: number;
  };
}

interface RankingArtifact {
  schema_version?: string;
  target_symbol?: string;
  action?: string;
  target_rank?: number | null;
  ranked_companies?: RankingCompany[];
}

interface CompanyProfileArtifact {
  schema_version?: string;
  symbol?: string;
  market?: string;
  peer_symbols?: string[];
  quote?: {
    summary?: string;
    preview?: Record<string, unknown>;
  };
}

interface SourcePoint {
  id: number;
  key?: string;
  value?: unknown;
  source_type?: string;
  source_url?: string | null;
  publisher?: string | null;
  published_at?: string | null;
  fetched_at?: string | null;
  as_of?: string | null;
  confidence?: string | null;
  excerpt?: string | null;
}

interface SourceCatalogArtifact {
  run_id?: string;
  items?: Record<string, SourcePoint>;
}

interface DiagnosisCheck {
  name?: string;
  status?: "pass" | "warn" | "fail" | string;
  severity?: string;
  detail?: string;
}

interface CompanyRunDiagnosis {
  schema_version?: string;
  symbol?: string;
  status?: "pass" | "warn" | "fail" | string;
  checks?: DiagnosisCheck[];
  metrics?: {
    gate_count?: number;
    source_count?: number;
    citation_markers?: number;
    numeric_citation_count?: number;
    no_source_count?: number;
    orphan_citation_ids?: number[];
    unsupported_claim_count?: number;
    unsupported_core_claim_count?: number;
    unbacked_number_claim_count?: number;
    weak_number_claim_count?: number;
    tier_1_source_count?: number;
    tier_2_source_count?: number;
    tier_3_source_count?: number;
    tier_4_source_count?: number;
    ranked_company_count?: number;
  };
  source_quality?: {
    status?: "pass" | "warn" | "fail" | string;
    metrics?: {
      source_count?: number;
      tier_1_count?: number;
      tier_2_count?: number;
      tier_3_count?: number;
      tier_4_count?: number;
      tier_4_ratio?: number;
      low_confidence_count?: number;
      ungrounded_count?: number;
      search_snippet_count?: number;
    };
  };
  claim_audit_summary?: {
    claim_count?: number;
    core_claim_count?: number;
    unsupported_claim_count?: number;
    unsupported_core_claim_count?: number;
    weak_core_claim_count?: number;
    unbacked_number_claim_count?: number;
    weak_number_claim_count?: number;
  };
}

interface HistoryDiff {
  runId: string;
  startedAt?: number | null;
  actionBefore?: string;
  actionNow?: string;
  maxBefore?: number | null;
  maxNow?: number | null;
  rankBefore?: number | null;
  rankNow?: number | null;
}

// Phase A.2: company_final_verdict.v1 — the structured Gate 7 output.
// Optional fields throughout so mock/legacy runs don't crash the renderer.
interface FisherQuestion {
  id: string;
  question: string;
  answer: string;
  score?: number;
  data_confidence?: string;
}

interface FinalVerdict {
  schema_version?: string;
  symbol?: string;
  verdict?: {
    action?: string;
    conviction?: number;
    quality_verdict?: string;
    position_size_pct?: number;
    hold_horizon?: string;
    one_sentence?: string;
  };
  fisher_qa?: {
    questions?: FisherQuestion[];
    total_score?: number;
    growth_verdict?: string;
    radar_data?: Record<string, number>;
    green_flags?: string[];
    red_flags?: string[];
  };
  moat?: {
    types?: { type?: string; strength?: string; evidence?: string }[];
    width?: string;
    trend?: string;
    durability_years?: number;
    competitive_position?: string;
    threats?: string[];
  };
  management?: Record<string, unknown>;
  reverse_test?: {
    destruction_scenarios?: { scenario?: string; probability?: number; impact?: number; timeline?: string }[];
    red_flags?: { flag?: string; triggered?: boolean; detail?: string }[];
    resilience_score?: number;
    cognitive_biases?: string[];
    worst_case_narrative?: string;
  };
  valuation?: Record<string, unknown>;
  philosophy_scores?: { buffett?: number; fisher?: number; munger?: number };
  master_comments?: { buffett?: string; fisher?: string; munger?: string };
  triggers?: { add?: string[]; sell?: string[] };
}

const GATE_TITLES: Record<string, string> = {
  business_analysis: "生意分析",
  fisher_qa: "成长质量",
  moat_assessment: "护城河",
  management_assessment: "管理层",
  reverse_test: "逆向检验",
  valuation: "估值与时机",
};

const SOURCE_LABELS: Record<string, string> = {
  yfinance: "Y!FIN",
  fmp: "FMP",
  sec_edgar: "EDGAR",
  google_cse: "NEWS",
  web_search: "WEB",
  web_extract: "WEB",
  market_data: "MKT",
  financials: "FIN",
  filing: "FILING",
  news: "NEWS",
  tool_result: "TOOL",
  computed: "CALC",
  company_data: "CO",
  user_input: "USER",
};

const SOURCE_TONES: Record<string, string> = {
  yfinance: "text-[var(--info)]",
  fmp: "text-[var(--gain)]",
  sec_edgar: "text-[var(--warn)]",
  google_cse: "text-[var(--accent)]",
  web_search: "text-[var(--accent)]",
  web_extract: "text-[var(--accent)]",
  market_data: "text-[var(--info)]",
  financials: "text-[var(--gain)]",
  filing: "text-[var(--warn)]",
  news: "text-[var(--accent)]",
  tool_result: "text-[var(--ink-muted)]",
  computed: "text-[var(--ink-muted)]",
  company_data: "text-[var(--ink-muted)]",
  user_input: "text-[var(--ink-muted)]",
};

function actionTone(action?: string): Tone {
  if (action === "BUY") return "gain";
  if (action === "AVOID") return "loss";
  if (action === "WATCH") return "warn";
  return "neutral";
}

function formatTs(ts: number | undefined | null): string {
  if (!ts) return "—";
  return new Date(ts * 1000).toLocaleString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function duration(start?: number, end?: number | null): string {
  if (!start || !end) return "running";
  const seconds = Math.max(0, Math.round(end - start));
  if (seconds < 60) return `${seconds}s`;
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}

function pct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${Number(value).toFixed(1)}%`;
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function parseJson<T>(text: string | undefined): T | null {
  if (!text) return null;
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

function inferSymbol(run: RunDetail): string {
  const text = `${run.user_input ?? ""} ${run.summary ?? ""}`;
  const match = text.match(/\b[A-Z]{1,5}(?:\.[A-Z]{2})?\b|\b\d{6}\.(?:SH|SZ)\b/);
  return match?.[0] ?? "Company";
}

function gateSlug(name: string): string {
  return name.replace(/^gate-\d+-/, "").replace(/\.md$/, "");
}

function gateTitle(artifact: ArtifactRef): string {
  const slug = gateSlug(artifact.name);
  return artifact.display_name?.replace(/^Gate\s+\d+:\s*/, "") || GATE_TITLES[slug] || slug;
}

function extractSection(text: string, heading: string): string {
  const normalized = heading.toLowerCase();
  const lines = text.split("\n");
  const start = lines.findIndex((line) => {
    const match = line.trim().match(/^##\s+(.+)$/);
    return match?.[1]?.trim().toLowerCase() === normalized;
  });
  if (start === -1) return "";
  const body: string[] = [];
  for (let i = start + 1; i < lines.length; i += 1) {
    if (/^#{1,2}\s+/.test(lines[i].trim())) break;
    body.push(lines[i]);
  }
  return body.join("\n").trim();
}

function extractGateLead(text: string): string {
  const conclusion = extractSection(text, "Gate conclusion");
  if (conclusion) return conclusion;
  const findings = extractSection(text, "Key findings");
  if (findings) return findings.replace(/^[-*]\s+/gm, "").trim();
  return text
    .split("\n")
    .map((line) => line.trim())
    .find((line) => line && !line.startsWith("#")) ?? "";
}

function citedIdsFromText(text: string): number[] {
  const ids = new Set<number>();
  const re = /\[src:([\d,\s]+)\]|\[(\d{1,3}(?:,\s*\d{1,3})*)\]/g;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    const raw = match[1] ?? match[2] ?? "";
    for (const part of raw.split(",")) {
      const id = Number.parseInt(part.trim(), 10);
      if (Number.isFinite(id)) ids.add(id);
    }
  }
  return Array.from(ids).sort((a, b) => a - b);
}

function sourceLabel(source?: string): string {
  return SOURCE_LABELS[source ?? ""] ?? (source ? source.slice(0, 6).toUpperCase() : "SRC");
}

function sourceTone(source?: string): string {
  return SOURCE_TONES[source ?? ""] ?? "text-[var(--ink-muted)]";
}

function sourceDate(point: SourcePoint): string {
  return point.published_at?.slice(0, 10) ?? point.fetched_at?.slice(0, 10) ?? "—";
}

function sourceText(point: SourcePoint): string {
  if (point.excerpt) return point.excerpt;
  if (point.key) return point.key;
  if (typeof point.value === "string" || typeof point.value === "number") return String(point.value);
  return "source";
}

function dedupeArtifactRefs(items: ArtifactRef[]): ArtifactRef[] {
  const byName = new Map<string, ArtifactRef>();
  for (const item of items) {
    if (!item.name) continue;
    if (byName.has(item.name)) byName.delete(item.name);
    byName.set(item.name, item);
  }
  return Array.from(byName.values());
}

function shouldEagerLoadArtifact(artifact: ArtifactRef): boolean {
  if (artifact.kind === "binary") return false;
  if (artifact.role === "primary" || artifact.role === "source_catalog" || artifact.role === "diagnosis") {
    return true;
  }
  if (/^gate-\d+-.+\.md$/.test(artifact.name)) return true;
  return [
    "company-profile.json",
    "decision.json",
    "capital-plan.json",
    "ranking.json",
    "source-catalog.json",
    "company-claims.json",
    "company-source-quality.json",
    "company-run-diagnosis.json",
    "trace-diagnosis.json",
  ].includes(artifact.name);
}

function CitationChip({
  id,
  point,
}: {
  id: number;
  point: SourcePoint | null;
}) {
  const label = sourceLabel(point?.source_type);
  const chip = (
    <span
      className={cn(
        "inline-flex align-baseline font-mono text-[9px] leading-none",
        point ? sourceTone(point.source_type) : "text-[var(--ink-faint)]",
      )}
      title={point ? `${label} · ${point.publisher ?? ""} · ${sourceDate(point)}\n${sourceText(point)}` : `src ${id}`}
    >
      <sup>[{id}]</sup>
    </span>
  );
  if (!point?.source_url) return chip;
  return (
    <a href={point.source_url} target="_blank" rel="noreferrer" className="hover:underline">
      {chip}
    </a>
  );
}

function CitedText({
  text,
  catalog,
  className,
}: {
  text: string;
  catalog: Record<string, SourcePoint>;
  className?: string;
}) {
  const nodes: React.ReactNode[] = [];
  const re = /\[src:([\d,\s]+)\]|\[(\d{1,3}(?:,\s*\d{1,3})*)\]/g;
  let lastIdx = 0;
  let key = 0;
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIdx) {
      nodes.push(<InlineText key={`t-${key++}`} text={text.slice(lastIdx, match.index)} />);
    }
    const raw = match[1] ?? match[2] ?? "";
    for (const part of raw.split(",")) {
      const id = Number.parseInt(part.trim(), 10);
      if (Number.isFinite(id)) {
        nodes.push(<CitationChip key={`c-${key++}`} id={id} point={catalog[String(id)] ?? null} />);
      }
    }
    lastIdx = match.index + match[0].length;
  }
  if (lastIdx < text.length) {
    nodes.push(<InlineText key={`t-${key++}`} text={text.slice(lastIdx)} />);
  }
  return <span className={className}>{nodes}</span>;
}

function InlineText({ text }: { text: string }) {
  const clean = text.replace(/`([^`]+)`/g, "$1");
  const parts = clean.split(/(\*\*[^*]+\*\*)/g);
  return (
    <>
      {parts.map((part, i) =>
        part.startsWith("**") && part.endsWith("**") ? (
          <strong key={i} className="font-semibold text-[var(--ink)]">
            {part.slice(2, -2)}
          </strong>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </>
  );
}

export function CompanyDossierView({ run }: { run: RunDetail }) {
  const artifacts = useMemo(() => dedupeArtifactRefs(run.artifacts ?? []), [run.artifacts]);
  const [artifactText, setArtifactText] = useState<Record<string, string>>({});
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("cited");
  const [historyDiff, setHistoryDiff] = useState<HistoryDiff | null>(null);
  const [historyChecked, setHistoryChecked] = useState(false);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const textArtifacts = artifacts.filter(shouldEagerLoadArtifact);
      const entries = await Promise.allSettled(
        textArtifacts.map(async (artifact) => [artifact.name, await fetchArtifactText(run.id, artifact.name)] as const),
      );
      if (cancelled) return;
      const next: Record<string, string> = {};
      for (const entry of entries) {
        if (entry.status === "fulfilled") {
          next[entry.value[0]] = entry.value[1];
        }
      }
      setArtifactText(next);
    }
    void load();
    return () => {
      cancelled = true;
    };
  }, [run.id, artifacts]);

  const decision = useMemo(
    () => parseJson<DecisionArtifact>(artifactText["decision.json"]),
    [artifactText],
  );
  const capitalPlan = useMemo(
    () => parseJson<CapitalPlanArtifact>(artifactText["capital-plan.json"]),
    [artifactText],
  );
  const ranking = useMemo(
    () => parseJson<RankingArtifact>(artifactText["ranking.json"]),
    [artifactText],
  );
  const profile = useMemo(
    () => parseJson<CompanyProfileArtifact>(artifactText["company-profile.json"]),
    [artifactText],
  );
  const diagnosis = useMemo(
    () => parseJson<CompanyRunDiagnosis>(artifactText["company-run-diagnosis.json"]),
    [artifactText],
  );
  const verdict = useMemo(
    () => parseJson<FinalVerdict>(artifactText["final-verdict.json"]),
    [artifactText],
  );
  const catalog = useMemo(() => {
    const parsed = parseJson<SourceCatalogArtifact>(artifactText["source-catalog.json"]);
    return parsed?.items ?? {};
  }, [artifactText]);

  const gateArtifacts = useMemo(
    () => artifacts.filter((a) => /^gate-\d+-.+\.md$/.test(a.name)).sort((a, b) => a.name.localeCompare(b.name)),
    [artifacts],
  );
  const finalArtifact =
    artifacts.find((a) => a.name === "final-report.md") ??
    artifacts.find((a) => a.role === "primary") ??
    null;
  const finalMemo = (finalArtifact ? artifactText[finalArtifact.name] : "") || run.summary || "";
  const action = decision?.action ?? capitalPlan?.action ?? ranking?.action ?? "WATCH";
  const symbol =
    decision?.symbol ?? capitalPlan?.symbol ?? profile?.symbol ?? ranking?.target_symbol ?? inferSymbol(run);
  const peers =
    profile?.peer_symbols ??
    ranking?.ranked_companies?.filter((company) => company.symbol !== symbol).map((company) => company.symbol ?? "") ??
    [];
  const rankedCompanies = ranking?.ranked_companies ?? [];
  const quotePreview = asRecord(profile?.quote?.preview);
  const currentPrice = quotePreview?.price ?? quotePreview?.current_price ?? quotePreview?.regular_market_price;
  const thesis =
    extractSection(finalMemo, "Verdict") ||
    finalMemo
      .split("\n")
      .map((line) => line.trim())
      .find((line) => line.length > 40 && !line.startsWith("#")) ||
    run.summary ||
    "公司深度调研已完成。";

  const citedIds = useMemo(() => {
    const ids = new Set<number>();
    for (const text of Object.values(artifactText)) {
      for (const id of citedIdsFromText(text)) ids.add(id);
    }
    for (const artifact of artifacts) {
      for (const id of artifact.source_refs ?? []) ids.add(id);
    }
    return Array.from(ids).sort((a, b) => a - b);
  }, [artifactText, artifacts]);

  const sourceEntries = useMemo(() => {
    const entries = Object.values(catalog).sort((a, b) => a.id - b.id);
    if (sourceFilter === "all") return entries;
    if (sourceFilter === "high") return entries.filter((entry) => entry.confidence === "high");
    if (sourceFilter === "low") return entries.filter((entry) => entry.confidence !== "high");
    if (sourceFilter === "news") return entries.filter((entry) => entry.source_type === "news" || entry.source_type === "google_cse");
    if (citedIds.length === 0) return entries.slice(0, 24);
    const cited = new Set(citedIds);
    return entries.filter((entry) => cited.has(entry.id));
  }, [catalog, citedIds, sourceFilter]);

  useEffect(() => {
    let cancelled = false;
    async function loadHistory() {
      if (!symbol || symbol === "Company") {
        setHistoryChecked(true);
        return;
      }
      setHistoryChecked(false);
      try {
        const recent = await listRuns({ skill: "company_research_pipeline", limit: 20 });
        const previous = recent.items.find((item) => {
          if (item.id === run.id) return false;
          const haystack = `${item.user_input ?? ""} ${item.summary ?? ""}`.toUpperCase();
          return haystack.includes(symbol.toUpperCase());
        });
        if (!previous) {
          if (!cancelled) setHistoryDiff(null);
          return;
        }
        const previousRun = await getRun(previous.id);
        const previousArtifacts = previousRun.artifacts ?? [];
        const [previousDecisionText, previousCapitalText] = await Promise.all([
          previousArtifacts.some((artifact) => artifact.name === "decision.json")
            ? fetchArtifactText(previous.id, "decision.json")
            : Promise.resolve(""),
          previousArtifacts.some((artifact) => artifact.name === "capital-plan.json")
            ? fetchArtifactText(previous.id, "capital-plan.json")
            : Promise.resolve(""),
        ]);
        const previousDecision = parseJson<DecisionArtifact>(previousDecisionText);
        const previousCapital = parseJson<CapitalPlanArtifact>(previousCapitalText);
        if (!cancelled) {
          setHistoryDiff({
            runId: previous.id,
            startedAt: previous.started_at,
            actionBefore: previousDecision?.action ?? previousCapital?.action,
            actionNow: action,
            maxBefore: previousDecision?.max_position_pct ?? previousCapital?.max_position_pct,
            maxNow: decision?.max_position_pct ?? capitalPlan?.max_position_pct,
            rankBefore: previousDecision?.target_rank,
            rankNow: decision?.target_rank ?? ranking?.target_rank,
          });
        }
      } catch {
        if (!cancelled) setHistoryDiff(null);
      } finally {
        if (!cancelled) setHistoryChecked(true);
      }
    }
    void loadHistory();
    return () => {
      cancelled = true;
    };
  }, [
    action,
    capitalPlan?.max_position_pct,
    decision?.max_position_pct,
    decision?.target_rank,
    ranking?.target_rank,
    run.id,
    symbol,
  ]);

  const chapters = [
    ...gateArtifacts.map((artifact, index) => ({
      number: index + 1,
      title: gateTitle(artifact),
      artifact,
      text: artifactText[artifact.name] ?? "",
      kind: "gate" as const,
    })),
    finalArtifact
      ? {
          number: gateArtifacts.length + 1,
          title: "最终备忘录",
          artifact: finalArtifact,
          text: finalMemo,
          kind: "final" as const,
        }
      : null,
  ].filter(Boolean) as Array<{
    number: number;
    title: string;
    artifact: ArtifactRef;
    text: string;
    kind: "gate" | "final";
  }>;

  return (
    <div className="min-h-screen paper-grain bg-[var(--canvas)]">
      <div className="border-b border-[var(--line)] bg-[var(--surface)]/65 px-6 py-4 xl:px-10">
        <div className="mx-auto flex max-w-[1280px] flex-wrap items-center gap-3">
          <Link
            href="/company-agent"
            className="inline-flex items-center gap-1.5 font-mono text-[11px] tracking-[0.08em] uppercase text-[var(--ink-muted)] hover:text-[var(--ink)]"
          >
            <ArrowLeft size={14} /> 研究台
          </Link>
          <span className="font-mono text-[10px] tracking-[0.18em] text-[var(--ink-faint)]">
            {formatTs(run.started_at)} · {duration(run.started_at, run.ended_at)}
          </span>
          <Badge tone={run.status === "ok" ? "gain" : run.status === "running" ? "warn" : "loss"}>
            {run.status}
          </Badge>
          <Link
            href={`/runs/${run.id}`}
            className="ml-auto inline-flex items-center gap-1.5 font-mono text-[11px] tracking-[0.08em] uppercase text-[var(--accent)] hover:underline"
          >
            <Workflow size={13} /> run trace
          </Link>
        </div>
      </div>

      <main className="mx-auto max-w-[1280px] px-6 py-8 xl:px-10">
        <section className="mb-10 grid gap-8 lg:grid-cols-[minmax(0,1.08fr)_minmax(360px,0.92fr)]">
          <div>
            <div className="eyebrow mb-5">verdict</div>
            <div className="mb-8 inline-flex rotate-[-2deg] flex-col items-center border-2 border-[color-mix(in_srgb,var(--gain)_60%,transparent)] px-9 py-4 shadow-[0_0_0_3px_color-mix(in_srgb,var(--gain)_10%,transparent)]">
              <span
                className={cn(
                  "font-display text-[48px] font-semibold italic leading-none tracking-normal",
                  actionTone(action) === "gain"
                    ? "text-[var(--gain)]"
                    : actionTone(action) === "loss"
                      ? "text-[var(--loss)]"
                      : actionTone(action) === "warn"
                        ? "text-[var(--warn)]"
                        : "text-[var(--ink-muted)]",
                )}
              >
                {action}
              </span>
              <span className="mt-2 font-mono text-[10px] tracking-[0.28em] text-[var(--ink-muted)]">
                CONVICTION · {decision?.conviction != null ? decision.conviction.toFixed(2) : "—"}
              </span>
            </div>

            <h1 className="font-display text-[76px] italic leading-none tracking-normal text-[var(--ink)] md:text-[96px]">
              {symbol}
            </h1>
            <p className="mt-3 font-display text-[20px] italic tracking-normal text-[var(--ink-muted)]">
              {profile?.market ? `${profile.market} market` : "company research dossier"}
            </p>
            <p className="mt-7 max-w-3xl text-[16px] leading-8 text-[var(--ink-soft)]">
              <CitedText text={thesis.slice(0, 520)} catalog={catalog} />
            </p>

            <div className="mt-8 grid grid-cols-2 gap-x-10 gap-y-5 md:grid-cols-5">
              <Metric label="initial">{pct(decision?.initial_position_pct ?? capitalPlan?.initial_position_pct)}</Metric>
              <Metric label="max">{pct(decision?.max_position_pct ?? capitalPlan?.max_position_pct)}</Metric>
              <Metric label="rank">{decision?.target_rank ?? ranking?.target_rank ?? "—"}</Metric>
              <Metric label="price">{typeof currentPrice === "number" ? `$${currentPrice.toFixed(2)}` : "—"}</Metric>
              <Metric label="sources">{Object.keys(catalog).length || "—"}</Metric>
            </div>
          </div>

          <aside className="space-y-6">
            <PanelTitle icon={<CheckCircle2 size={14} />}>run diagnosis</PanelTitle>
            <DiagnosisPanel diagnosis={diagnosis} />

            <PanelTitle icon={<GitCompare size={14} />}>history diff</PanelTitle>
            <HistoryDiffPanel diff={historyDiff} checked={historyChecked} />

            <PanelTitle icon={<ShieldCheck size={14} />}>capital plan</PanelTitle>
            <div className="border-t border-[var(--line)] pt-4">
              <div className="grid grid-cols-2 gap-4">
                <MiniField label="order">{capitalPlan?.real_order_execution ? "enabled" : "disabled"}</MiniField>
                <MiniField label="peers">{peers.filter(Boolean).slice(0, 3).join(" · ") || "—"}</MiniField>
              </div>
              <TriggerList label="add" items={capitalPlan?.add_triggers} tone="gain" />
              <TriggerList label="trim" items={capitalPlan?.trim_triggers} tone="warn" />
              <TriggerList label="sell" items={capitalPlan?.sell_triggers} tone="loss" />
            </div>

            <PanelTitle icon={<Database size={14} />}>peer ranking</PanelTitle>
            {rankedCompanies.length === 0 ? (
              <div className="border-t border-[var(--line)] py-4 text-[12px] text-[var(--ink-muted)]">
                ranking.json 暂不可用。
              </div>
            ) : (
              <ol className="border-t border-[var(--line)]">
                {rankedCompanies.slice(0, 4).map((company) => (
                  <li
                    key={`${company.rank ?? "x"}-${company.symbol ?? "company"}`}
                    className="grid grid-cols-[42px_minmax(0,1fr)_80px] border-b border-[var(--line)] py-3"
                  >
                    <span className="font-mono text-[10px] text-[var(--ink-faint)]">#{company.rank ?? "—"}</span>
                    <span className="font-display text-[18px] italic tracking-normal text-[var(--ink)]">
                      {company.symbol ?? "—"}
                    </span>
                    <span className="numeric text-right text-[12px] text-[var(--ink-soft)]">
                      {company.scores?.total?.toFixed(1) ?? "—"}
                    </span>
                  </li>
                ))}
              </ol>
            )}
          </aside>
        </section>

        {verdict && <VerdictPanel verdict={verdict} catalog={catalog} />}

        <section className="mb-10">
          <div className="mb-5 flex items-baseline gap-3 border-b border-[var(--line-strong)] pb-3">
            <h2 className="font-display text-[30px] italic tracking-normal text-[var(--ink)]">七章档案</h2>
            <span className="font-display text-[14px] italic tracking-normal text-[var(--ink-muted)]">
              seven chapters · {chapters.length} files
            </span>
          </div>

          {chapters.length === 0 ? (
            <FallbackMemo text={finalMemo} catalog={catalog} />
          ) : (
            <div className="grid gap-x-8 gap-y-2 lg:grid-cols-2">
              {chapters.map((chapter) => (
                <Chapter
                  runId={run.id}
                  key={chapter.artifact.name}
                  chapter={chapter}
                  catalog={catalog}
                  expanded={expanded[chapter.artifact.name] ?? chapter.kind === "final"}
                  onToggle={() =>
                    setExpanded((prev) => ({
                      ...prev,
                      [chapter.artifact.name]: !(prev[chapter.artifact.name] ?? chapter.kind === "final"),
                    }))
                  }
                />
              ))}
            </div>
          )}
        </section>

        {Object.keys(catalog).length > 0 && (
          <section className="mb-10 border-t border-[var(--line-strong)] pt-6">
            <div className="mb-4 flex flex-wrap items-center gap-3">
              <div className="eyebrow">source ledger · {sourceEntries.length}/{Object.keys(catalog).length}</div>
              <SourceFilterBar value={sourceFilter} onChange={setSourceFilter} />
            </div>
            <SourceLedger entries={sourceEntries} />
          </section>
        )}

        {artifacts.length > 0 && (
          <Card className="mb-8">
            <CardHeader>
              <div className="flex items-center gap-2">
                <FileText size={15} className="text-[var(--accent)]" />
                <div className="eyebrow">artifacts · {artifacts.length}</div>
              </div>
            </CardHeader>
            <CardBody>
              <Artifacts runId={run.id} items={artifacts} />
            </CardBody>
          </Card>
        )}
      </main>
    </div>
  );
}

function Metric({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)] uppercase">
        {label}
      </div>
      <div className="mt-1 numeric text-[22px] leading-none text-[var(--ink)]">{children}</div>
    </div>
  );
}

function MiniField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)] uppercase">
        {label}
      </div>
      <div className="mt-1 text-[12px] leading-relaxed text-[var(--ink-soft)]">{children}</div>
    </div>
  );
}

function PanelTitle({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="flex items-center gap-2 text-[var(--accent)]">
      {icon}
      <div className="eyebrow">{children}</div>
    </div>
  );
}

function DiagnosisPanel({ diagnosis }: { diagnosis: CompanyRunDiagnosis | null }) {
  if (!diagnosis) {
    return (
      <div className="border-t border-[var(--line)] py-4 text-[12px] leading-relaxed text-[var(--ink-muted)]">
        diagnosis artifact 暂不可用。
      </div>
    );
  }
  const statusTone = diagnosis.status === "fail" ? "loss" : diagnosis.status === "warn" ? "warn" : "gain";
  const visibleChecks = (diagnosis.checks ?? []).slice(0, 6);
  const sourceMetrics = diagnosis.source_quality?.metrics;
  const claimSummary = diagnosis.claim_audit_summary;
  const tier12 =
    (sourceMetrics?.tier_1_count ?? diagnosis.metrics?.tier_1_source_count ?? 0) +
    (sourceMetrics?.tier_2_count ?? diagnosis.metrics?.tier_2_source_count ?? 0);
  const tier4 = sourceMetrics?.tier_4_count ?? diagnosis.metrics?.tier_4_source_count ?? 0;
  const unsupportedCore =
    claimSummary?.unsupported_core_claim_count ?? diagnosis.metrics?.unsupported_core_claim_count ?? 0;
  const unbackedNumbers =
    claimSummary?.unbacked_number_claim_count ?? diagnosis.metrics?.unbacked_number_claim_count ?? 0;
  return (
    <div className="border-t border-[var(--line)] pt-4">
      <div className="mb-4 grid grid-cols-[minmax(0,1fr)_72px] items-center gap-3">
        <div>
          <div className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)] uppercase">
            quality gate
          </div>
          <div
            className={cn(
              "mt-1 font-display text-[26px] italic tracking-normal",
              statusTone === "gain"
                ? "text-[var(--gain)]"
                : statusTone === "loss"
                  ? "text-[var(--loss)]"
                  : "text-[var(--warn)]",
            )}
          >
            {diagnosis.status ?? "unknown"}
          </div>
        </div>
        <div className="text-right">
          <div className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)] uppercase">
            gates
          </div>
          <div className="numeric mt-1 text-[18px] text-[var(--ink)]">
            {diagnosis.metrics?.gate_count ?? "—"}/6
          </div>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-3 border-y border-[var(--line)] py-3">
        <MiniField label="sources">{diagnosis.metrics?.source_count ?? "—"}</MiniField>
        <MiniField label="cites">{diagnosis.metrics?.citation_markers ?? "—"}</MiniField>
        <MiniField label="orphans">{diagnosis.metrics?.orphan_citation_ids?.length ?? 0}</MiniField>
      </div>
      <div className="grid grid-cols-4 gap-3 border-b border-[var(--line)] py-3">
        <MiniField label="tier 1+2">{tier12}</MiniField>
        <MiniField label="tier 4">{tier4}</MiniField>
        <MiniField label="core gaps">{unsupportedCore}</MiniField>
        <MiniField label="num gaps">{unbackedNumbers}</MiniField>
      </div>
      <ul className="mt-3 space-y-2">
        {visibleChecks.map((check) => (
          <li key={check.name} className="grid grid-cols-[18px_minmax(0,1fr)] gap-2 text-[12px] leading-relaxed">
            <span className="pt-0.5">
              {check.status === "pass" ? (
                <CheckCircle2 size={14} className="text-[var(--gain)]" />
              ) : check.status === "fail" ? (
                <XCircle size={14} className="text-[var(--loss)]" />
              ) : (
                <AlertTriangle size={14} className="text-[var(--warn)]" />
              )}
            </span>
            <span className="min-w-0">
              <span className="font-mono text-[10px] tracking-[0.08em] text-[var(--ink)]">
                {check.name ?? "check"}
              </span>
              {check.detail ? (
                <span className="mt-0.5 block text-[var(--ink-muted)]">{check.detail}</span>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function HistoryDiffPanel({
  diff,
  checked,
}: {
  diff: HistoryDiff | null;
  checked: boolean;
}) {
  if (!checked) {
    return (
      <div className="border-t border-[var(--line)] py-4 text-[12px] text-[var(--ink-muted)]">
        loading previous run…
      </div>
    );
  }
  if (!diff) {
    return (
      <div className="border-t border-[var(--line)] py-4 text-[12px] text-[var(--ink-muted)]">
        暂无同公司历史 run。
      </div>
    );
  }
  return (
    <div className="border-t border-[var(--line)] pt-4">
      <div className="mb-3 flex items-center justify-between gap-3">
        <Link
          href={`/company-agent/${diff.runId}`}
          className="font-mono text-[10px] tracking-[0.08em] uppercase text-[var(--accent)] hover:underline"
        >
          previous run
        </Link>
        <span className="font-mono text-[9px] tracking-[0.12em] text-[var(--ink-faint)]">
          {formatTs(diff.startedAt)}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-3">
        <DiffMetric label="action" before={diff.actionBefore ?? "—"} after={diff.actionNow ?? "—"} />
        <DiffMetric label="max" before={pct(diff.maxBefore)} after={pct(diff.maxNow)} />
        <DiffMetric label="rank" before={diff.rankBefore ?? "—"} after={diff.rankNow ?? "—"} />
      </div>
    </div>
  );
}

function DiffMetric({
  label,
  before,
  after,
}: {
  label: string;
  before: React.ReactNode;
  after: React.ReactNode;
}) {
  const changed = String(before) !== String(after);
  return (
    <div>
      <div className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)] uppercase">
        {label}
      </div>
      <div className={cn("mt-1 text-[12px] leading-relaxed", changed ? "text-[var(--warn)]" : "text-[var(--ink-soft)]")}>
        {before} → {after}
      </div>
    </div>
  );
}

function SourceFilterBar({
  value,
  onChange,
}: {
  value: SourceFilter;
  onChange: (value: SourceFilter) => void;
}) {
  const filters: Array<{ value: SourceFilter; label: string }> = [
    { value: "cited", label: "引用" },
    { value: "all", label: "全部" },
    { value: "high", label: "高置信" },
    { value: "low", label: "待核验" },
    { value: "news", label: "新闻" },
  ];
  return (
    <div className="inline-flex flex-wrap items-center gap-1.5">
      <Filter size={13} className="text-[var(--ink-faint)]" />
      {filters.map((filter) => (
        <Button
          key={filter.value}
          variant={value === filter.value ? "primary" : "ghost"}
          onClick={() => onChange(filter.value)}
        >
          {filter.label}
        </Button>
      ))}
    </div>
  );
}

function TriggerList({
  label,
  items,
  tone,
}: {
  label: string;
  items?: string[];
  tone: Tone;
}) {
  if (!items?.length) return null;
  const color =
    tone === "gain" ? "text-[var(--gain)]" : tone === "loss" ? "text-[var(--loss)]" : "text-[var(--warn)]";
  return (
    <div className="mt-5">
      <div className="mb-2 font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)] uppercase">
        {label}
      </div>
      <ul className="space-y-1.5">
        {items.slice(0, 3).map((item) => (
          <li key={item} className={cn("text-[12px] leading-relaxed", color)}>
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Chapter({
  runId,
  chapter,
  catalog,
  expanded,
  onToggle,
}: {
  runId: string;
  chapter: {
    number: number;
    title: string;
    artifact: ArtifactRef;
    text: string;
    kind: "gate" | "final";
  };
  catalog: Record<string, SourcePoint>;
  expanded: boolean;
  onToggle: () => void;
}) {
  const lead = chapter.kind === "gate" ? extractGateLead(chapter.text) : extractSection(chapter.text, "Verdict");
  const roman = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"][chapter.number - 1] ?? String(chapter.number);
  return (
    <article
      className={cn(
        "break-inside-avoid border-b border-dashed border-[color-mix(in_srgb,var(--ink-faint)_38%,transparent)] pb-5 pt-5",
        chapter.kind === "final" && "lg:col-span-2 border-t border-[var(--line-strong)]",
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        className="group flex w-full items-baseline gap-4 text-left"
      >
        <span className="font-display text-[24px] italic tracking-normal text-[var(--ink-muted)]">{roman}</span>
        <span className="font-display text-[24px] italic tracking-normal text-[var(--ink)]">{chapter.title}</span>
        <span className="min-w-0 flex-1" />
        <span className="inline-flex items-center gap-1 font-mono text-[10px] tracking-[0.12em] text-[var(--ink-faint)] group-hover:text-[var(--ink-muted)]">
          {expanded ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
          {chapter.artifact.name}
        </span>
      </button>
      {lead && (
        <p className="mt-4 pl-10 text-[14px] leading-7 text-[var(--ink-soft)]">
          <CitedText text={lead.slice(0, 520)} catalog={catalog} />
        </p>
      )}
      {expanded && (
        <div className="mt-5 pl-10">
          <RichMarkdown text={chapter.text || "No content"} catalog={catalog} />
          <a
            href={artifactUrl(runId, chapter.artifact.name)}
            target="_blank"
            rel="noreferrer"
            className="mt-4 inline-flex items-center gap-1.5 font-mono text-[10px] tracking-[0.08em] uppercase text-[var(--accent)] hover:underline"
          >
            raw artifact <ExternalLink size={12} />
          </a>
        </div>
      )}
    </article>
  );
}

function FallbackMemo({
  text,
  catalog,
}: {
  text: string;
  catalog: Record<string, SourcePoint>;
}) {
  return (
    <div className="border-t border-[var(--line)] pt-5">
      <RichMarkdown text={text || "暂无最终备忘录内容。"} catalog={catalog} />
    </div>
  );
}

function RichMarkdown({
  text,
  catalog,
}: {
  text: string;
  catalog: Record<string, SourcePoint>;
}) {
  const lines = text.split("\n");
  const nodes: React.ReactNode[] = [];
  let list: string[] = [];

  function flushList(key: string) {
    if (!list.length) return;
    nodes.push(
      <ul key={key} className="mb-4 space-y-1.5 border-l border-[var(--line)] pl-4">
        {list.map((item, i) => (
          <li key={i} className="text-[13px] leading-7 text-[var(--ink-soft)]">
            <CitedText text={item} catalog={catalog} />
          </li>
        ))}
      </ul>,
    );
    list = [];
  }

  lines.forEach((rawLine, index) => {
    const line = rawLine.trim();
    if (!line) {
      flushList(`list-${index}`);
      return;
    }
    const bullet = line.match(/^[-*]\s+(.+)$/);
    if (bullet) {
      list.push(bullet[1]);
      return;
    }
    flushList(`list-${index}`);

    if (line.startsWith("# ")) {
      nodes.push(
        <h3 key={index} className="mb-4 mt-1 font-display text-[24px] italic tracking-normal text-[var(--ink)]">
          {line.replace(/^#\s+/, "")}
        </h3>,
      );
      return;
    }
    if (line.startsWith("## ")) {
      nodes.push(
        <h4 key={index} className="mb-3 mt-5 font-mono text-[10px] tracking-[0.18em] text-[var(--ink-faint)] uppercase">
          {line.replace(/^##\s+/, "")}
        </h4>,
      );
      return;
    }
    nodes.push(
      <p key={index} className="mb-3 text-[13px] leading-7 text-[var(--ink-soft)]">
        <CitedText text={line} catalog={catalog} />
      </p>,
    );
  });
  flushList("list-final");

  return <div>{nodes}</div>;
}

function SourceLedger({ entries }: { entries: SourcePoint[] }) {
  if (entries.length === 0) {
    return <div className="text-[12px] text-[var(--ink-muted)]">暂无可展示来源。</div>;
  }
  return (
    <div className="grid gap-x-8 lg:grid-cols-2">
      {entries.map((entry) => (
        <a
          key={entry.id}
          href={entry.source_url ?? undefined}
          target={entry.source_url ? "_blank" : undefined}
          rel="noreferrer"
          className={cn(
            "grid grid-cols-[32px_52px_minmax(0,1fr)] gap-2 border-b border-dashed border-[color-mix(in_srgb,var(--ink-faint)_28%,transparent)] py-3",
            entry.source_url && "hover:bg-[var(--surface-hover)]",
          )}
        >
          <span className="font-mono text-[10px] text-[var(--ink-faint)]">
            {String(entry.id).padStart(2, "0")}
          </span>
          <span className={cn("font-mono text-[9px] font-semibold tracking-[0.16em]", sourceTone(entry.source_type))}>
            {sourceLabel(entry.source_type)}
          </span>
          <span className="min-w-0">
            <span className="block text-[12px] leading-5 text-[var(--ink-soft)]">
              {sourceText(entry)}
            </span>
            <span className="mt-1 block font-mono text-[9px] tracking-[0.12em] text-[var(--ink-faint)]">
              {entry.publisher ?? "—"} · {sourceDate(entry)}
              {entry.confidence ? ` · ${entry.confidence}` : ""}
            </span>
          </span>
        </a>
      ))}
    </div>
  );
}

// ─── Phase A.2 → A.4 — final-verdict.json renderer ───────────────────────
// The structured Gate 7 output drives:
//   - master commentary panel (Buffett / Fisher / Munger quotes)
//   - philosophy score bars
//   - 5-axis radar from fisher_qa.radar_data
//   - Fisher 15Q table (collapsible)
//   - green / red flag lists
//   - moat type chips
//   - add / sell triggers
// All sub-blocks are defensive — missing fields just render nothing,
// so legacy runs without final-verdict.json don't show empty scaffolding.

function VerdictPanel({
  verdict,
  catalog,
}: {
  verdict: FinalVerdict;
  catalog: Record<string, SourcePoint>;
}) {
  return (
    <section className="mb-10">
      <div className="mb-5 flex items-baseline gap-3 border-b border-[var(--line-strong)] pb-3">
        <h2 className="font-display text-[30px] italic tracking-normal text-[var(--ink)]">
          投研裁决
        </h2>
        <span className="font-display text-[14px] italic tracking-normal text-[var(--ink-muted)]">
          final verdict · {verdict.schema_version ?? "v1"}
        </span>
      </div>

      <MasterCommentsRow comments={verdict.master_comments} catalog={catalog} />

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(240px,0.95fr)]">
        <PhilosophyAndFlagsBlock verdict={verdict} catalog={catalog} />
        <RadarBlock radar={verdict.fisher_qa?.radar_data} />
      </div>

      <MoatBlock moat={verdict.moat} catalog={catalog} />
      <ReverseBlock reverse={verdict.reverse_test} catalog={catalog} />
      <TriggersBlock triggers={verdict.triggers} catalog={catalog} />
      <FisherQABlock fisher={verdict.fisher_qa} catalog={catalog} />
    </section>
  );
}

function MasterCommentsRow({
  comments,
  catalog,
}: {
  comments?: { buffett?: string; fisher?: string; munger?: string };
  catalog: Record<string, SourcePoint>;
}) {
  if (!comments || (!comments.buffett && !comments.fisher && !comments.munger)) return null;
  const entries: { name: string; text?: string }[] = [
    { name: "BUFFETT", text: comments.buffett },
    { name: "FISHER", text: comments.fisher },
    { name: "MUNGER", text: comments.munger },
  ];
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {entries.map(({ name, text }) =>
        !text ? null : (
          <div
            key={name}
            className="border-l-[3px] border-[var(--accent)] bg-[var(--surface-1)] px-4 py-3"
          >
            <div className="eyebrow mb-2">{name}</div>
            <CitedText
              text={text}
              catalog={catalog}
              className="font-display italic text-[14px] leading-relaxed text-[var(--ink)]"
            />
          </div>
        ),
      )}
    </div>
  );
}

function PhilosophyAndFlagsBlock({
  verdict,
  catalog,
}: {
  verdict: FinalVerdict;
  catalog: Record<string, SourcePoint>;
}) {
  const scores = verdict.philosophy_scores ?? {};
  const fisher = verdict.fisher_qa;
  return (
    <div>
      {(scores.buffett !== undefined || scores.fisher !== undefined || scores.munger !== undefined) && (
        <div className="mb-6">
          <div className="eyebrow mb-3">philosophy match</div>
          <div className="space-y-2.5">
            <ScoreBar label="Buffett" score={scores.buffett} />
            <ScoreBar label="Fisher" score={scores.fisher} />
            <ScoreBar label="Munger" score={scores.munger} />
          </div>
        </div>
      )}

      {fisher?.green_flags && fisher.green_flags.length > 0 && (
        <FlagList title="green flags · 积极信号" items={fisher.green_flags} tone="gain" catalog={catalog} />
      )}
      {fisher?.red_flags && fisher.red_flags.length > 0 && (
        <FlagList title="red flags · 警示信号" items={fisher.red_flags} tone="loss" catalog={catalog} />
      )}
    </div>
  );
}

function ScoreBar({ label, score }: { label: string; score?: number }) {
  if (score === undefined || score === null) return null;
  const pct = Math.max(0, Math.min(100, (score / 10) * 100));
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="font-mono text-[10px] tracking-[0.14em] text-[var(--ink-muted)]">{label}</span>
        <span className="numeric text-[11px] text-[var(--ink-soft)]">{score.toFixed(1)} / 10</span>
      </div>
      <div className="h-[3px] w-full bg-[var(--line)]">
        <div
          className="h-full bg-[var(--accent)]"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function FlagList({
  title,
  items,
  tone,
  catalog,
}: {
  title: string;
  items: string[];
  tone: "gain" | "loss";
  catalog: Record<string, SourcePoint>;
}) {
  const color = tone === "gain" ? "var(--gain)" : "var(--loss)";
  return (
    <div className="mt-4">
      <div className="eyebrow mb-2" style={{ color }}>
        {title}
      </div>
      <ul className="space-y-1.5">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2 text-[12px] leading-relaxed text-[var(--ink-soft)]">
            <span style={{ color }} className="shrink-0">
              ▸
            </span>
            <CitedText text={item} catalog={catalog} className="" />
          </li>
        ))}
      </ul>
    </div>
  );
}

function RadarBlock({ radar }: { radar?: Record<string, number> }) {
  if (!radar) return null;
  const axes = [
    { key: "market_potential", label: "市场" },
    { key: "innovation", label: "创新" },
    { key: "profitability", label: "盈利" },
    { key: "management", label: "管理" },
    { key: "competitive_edge", label: "护城河" },
  ];
  const cx = 110;
  const cy = 110;
  const radius = 78;
  // Generate pentagon points + data polygon points
  const angle = (i: number) => (-Math.PI / 2) + (i * 2 * Math.PI) / axes.length;
  const ring = axes
    .map((_, i) => {
      const a = angle(i);
      return `${cx + radius * Math.cos(a)},${cy + radius * Math.sin(a)}`;
    })
    .join(" ");
  const dataPts = axes
    .map((ax, i) => {
      const v = Math.max(0, Math.min(10, radar[ax.key] ?? 0));
      const r = (v / 10) * radius;
      const a = angle(i);
      return `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
    })
    .join(" ");

  return (
    <div className="border border-[var(--line)] bg-[var(--surface-1)] p-4">
      <div className="eyebrow mb-2">fisher radar</div>
      <svg viewBox="0 0 220 220" className="mx-auto block w-full max-w-[260px]">
        {/* 4 concentric rings */}
        {[0.25, 0.5, 0.75, 1].map((scale, i) => (
          <polygon
            key={i}
            points={axes
              .map((_, j) => {
                const a = angle(j);
                return `${cx + radius * scale * Math.cos(a)},${cy + radius * scale * Math.sin(a)}`;
              })
              .join(" ")}
            fill="none"
            stroke="var(--line)"
            strokeWidth="1"
          />
        ))}
        {/* Axis lines */}
        {axes.map((_, i) => {
          const a = angle(i);
          return (
            <line
              key={i}
              x1={cx}
              y1={cy}
              x2={cx + radius * Math.cos(a)}
              y2={cy + radius * Math.sin(a)}
              stroke="var(--line)"
              strokeWidth="1"
            />
          );
        })}
        {/* Pentagon outer outline */}
        <polygon points={ring} fill="none" stroke="var(--ink-faint)" strokeWidth="1.5" />
        {/* Data polygon */}
        <polygon
          points={dataPts}
          fill="color-mix(in srgb, var(--accent) 25%, transparent)"
          stroke="var(--accent)"
          strokeWidth="2"
          strokeLinejoin="round"
        />
        {/* Axis labels */}
        {axes.map((ax, i) => {
          const a = angle(i);
          const lx = cx + (radius + 16) * Math.cos(a);
          const ly = cy + (radius + 16) * Math.sin(a) + 4;
          return (
            <text
              key={ax.key}
              x={lx}
              y={ly}
              textAnchor="middle"
              className="fill-[var(--ink-muted)]"
              style={{ fontFamily: "var(--font-mono, monospace)", fontSize: 10, letterSpacing: "0.08em" }}
            >
              {ax.label} {Math.round(radar[ax.key] ?? 0)}
            </text>
          );
        })}
      </svg>
    </div>
  );
}

function MoatBlock({
  moat,
  catalog,
}: {
  moat?: FinalVerdict["moat"];
  catalog: Record<string, SourcePoint>;
}) {
  if (!moat || !moat.types || moat.types.length === 0) return null;
  const strengthColor: Record<string, string> = {
    strong: "var(--gain)",
    moderate: "var(--accent)",
    weak: "var(--loss)",
  };
  return (
    <div className="mt-6 border-t border-[var(--line)] pt-5">
      <div className="mb-3 flex flex-wrap items-baseline gap-3">
        <div className="eyebrow">moat</div>
        {moat.width && (
          <span className="font-mono text-[11px] tracking-[0.12em] text-[var(--ink-soft)]">
            width: {moat.width}
          </span>
        )}
        {moat.trend && (
          <span className="font-mono text-[11px] tracking-[0.12em] text-[var(--ink-soft)]">
            trend: {moat.trend}
          </span>
        )}
        {moat.durability_years !== undefined && moat.durability_years !== null && (
          <span className="font-mono text-[11px] tracking-[0.12em] text-[var(--ink-soft)]">
            durability: {moat.durability_years}y
          </span>
        )}
      </div>
      <div className="grid gap-2 md:grid-cols-3">
        {moat.types.map((t, i) => (
          <div
            key={i}
            className="border border-[var(--line)] bg-[var(--surface-1)] px-3 py-2"
          >
            <div className="mb-1 flex items-baseline justify-between">
              <span className="font-mono text-[10px] font-semibold tracking-[0.16em] text-[var(--accent)]">
                {t.type}
              </span>
              <span
                className="font-mono text-[9px] tracking-[0.14em]"
                style={{ color: strengthColor[t.strength ?? ""] ?? "var(--ink-muted)" }}
              >
                {t.strength}
              </span>
            </div>
            {t.evidence && (
              <CitedText
                text={t.evidence}
                catalog={catalog}
                className="text-[11px] leading-relaxed text-[var(--ink-soft)]"
              />
            )}
          </div>
        ))}
      </div>
      {moat.competitive_position && (
        <div className="mt-3 border-l-2 border-[var(--line)] pl-3">
          <CitedText
            text={moat.competitive_position}
            catalog={catalog}
            className="text-[12px] italic text-[var(--ink-muted)]"
          />
        </div>
      )}
    </div>
  );
}

function ReverseBlock({
  reverse,
  catalog,
}: {
  reverse?: FinalVerdict["reverse_test"];
  catalog: Record<string, SourcePoint>;
}) {
  if (!reverse) return null;
  const scenarios = reverse.destruction_scenarios ?? [];
  const flags = reverse.red_flags ?? [];
  const triggeredFlags = flags.filter((f) => f.triggered);
  if (scenarios.length === 0 && triggeredFlags.length === 0 && !reverse.worst_case_narrative) {
    return null;
  }
  return (
    <div className="mt-6 border-t border-[var(--line)] pt-5">
      <div className="mb-3 flex items-baseline gap-3">
        <div className="eyebrow">reverse test · munger</div>
        {reverse.resilience_score !== undefined && (
          <span className="font-mono text-[11px] tracking-[0.12em] text-[var(--ink-soft)]">
            resilience: {reverse.resilience_score.toFixed(1)} / 10
          </span>
        )}
      </div>
      {scenarios.length > 0 && (
        <div className="mb-3 grid gap-2 md:grid-cols-3">
          {scenarios.slice(0, 3).map((s, i) => (
            <div key={i} className="border border-[var(--line)] bg-[var(--surface-1)] px-3 py-2">
              <div className="mb-1 flex items-baseline justify-between font-mono text-[10px] text-[var(--ink-muted)]">
                <span>P {((s.probability ?? 0) * 100).toFixed(0)}%</span>
                <span>I {(s.impact ?? 0).toFixed(0)}/10</span>
                {s.timeline && <span>{s.timeline}</span>}
              </div>
              {s.scenario && (
                <div className="text-[12px] leading-relaxed text-[var(--ink-soft)]">{s.scenario}</div>
              )}
            </div>
          ))}
        </div>
      )}
      {triggeredFlags.length > 0 && (
        <div className="mb-3">
          <div className="eyebrow mb-2" style={{ color: "var(--loss)" }}>
            triggered red flags
          </div>
          <ul className="space-y-1.5">
            {triggeredFlags.map((f, i) => (
              <li key={i} className="text-[12px] leading-relaxed text-[var(--ink-soft)]">
                <span style={{ color: "var(--loss)" }} className="mr-2">▸</span>
                <strong className="font-medium text-[var(--ink)]">{f.flag}</strong>
                {f.detail && (
                  <>
                    {" — "}
                    <CitedText text={f.detail} catalog={catalog} className="text-[var(--ink-muted)]" />
                  </>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {reverse.worst_case_narrative && (
        <div className="border-l-2 border-[var(--loss)] pl-3">
          <CitedText
            text={reverse.worst_case_narrative}
            catalog={catalog}
            className="text-[12px] italic leading-relaxed text-[var(--ink-soft)]"
          />
        </div>
      )}
    </div>
  );
}

function TriggersBlock({
  triggers,
  catalog,
}: {
  triggers?: FinalVerdict["triggers"];
  catalog: Record<string, SourcePoint>;
}) {
  const adds = triggers?.add ?? [];
  const sells = triggers?.sell ?? [];
  if (adds.length === 0 && sells.length === 0) return null;
  return (
    <div className="mt-6 grid gap-4 border-t border-[var(--line)] pt-5 md:grid-cols-2">
      {adds.length > 0 && (
        <FlagList title="add triggers · 加仓信号" items={adds} tone="gain" catalog={catalog} />
      )}
      {sells.length > 0 && (
        <FlagList title="sell triggers · 止损 / 卖出" items={sells} tone="loss" catalog={catalog} />
      )}
    </div>
  );
}

function FisherQABlock({
  fisher,
  catalog,
}: {
  fisher?: FinalVerdict["fisher_qa"];
  catalog: Record<string, SourcePoint>;
}) {
  const [open, setOpen] = useState(false);
  if (!fisher || !fisher.questions || fisher.questions.length === 0) return null;
  const total = fisher.total_score;
  const verdict = fisher.growth_verdict;
  const verdictLabel: Record<string, string> = {
    compounder: "复利机器",
    cyclical: "周期成长",
    declining: "增长衰退",
    turnaround: "困境反转",
  };

  return (
    <div className="mt-6 border-t border-[var(--line)] pt-5">
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-baseline gap-3 text-left"
      >
        {open ? (
          <ChevronDown size={14} className="text-[var(--ink-muted)]" />
        ) : (
          <ChevronRight size={14} className="text-[var(--ink-muted)]" />
        )}
        <div className="eyebrow">fisher 15 Q</div>
        {total !== undefined && (
          <span className="font-mono text-[11px] tracking-[0.12em] text-[var(--ink-soft)]">
            total: {total} / 150
          </span>
        )}
        {verdict && (
          <span className="font-display text-[14px] italic text-[var(--accent)]">
            {verdictLabel[verdict] ?? verdict}
          </span>
        )}
        <span className="ml-auto font-mono text-[10px] text-[var(--ink-faint)]">
          {fisher.questions.length} 题
        </span>
      </button>
      {open && (
        <ol className="mt-4 space-y-3">
          {fisher.questions.map((q) => (
            <li key={q.id} className="grid gap-2 border-l-2 border-[var(--line)] pl-3 md:grid-cols-[60px_1fr_80px]">
              <div>
                <span className="font-mono text-[11px] font-semibold text-[var(--accent)]">{q.id}</span>
              </div>
              <div>
                <div className="font-display text-[13px] italic text-[var(--ink)]">{q.question}</div>
                {q.answer && (
                  <div className="mt-1">
                    <CitedText
                      text={q.answer}
                      catalog={catalog}
                      className="text-[12px] leading-relaxed text-[var(--ink-soft)]"
                    />
                  </div>
                )}
              </div>
              <div className="flex flex-col items-end gap-0.5 text-right">
                <span className="numeric text-[14px] text-[var(--ink)]">
                  {q.score !== undefined ? q.score.toFixed(1) : "—"}
                </span>
                {q.data_confidence && (
                  <span className="font-mono text-[8px] tracking-[0.16em] uppercase text-[var(--ink-faint)]">
                    {q.data_confidence}
                  </span>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}


// ─── Client-side fetch wrapper ───────────────────────────────────────────
// page.tsx (server component) can't read the user's access token (lives in
// sessionStorage) and was silently 404-ing into a demo@local run shell for
// any cross-user dossier. This wrapper does the fetch on the client, after
// sessionStorage is available, so the user sees their real run.

export function CompanyDossierClient({ runId }: { runId: string }) {
  const [run, setRun] = useState<RunDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    setRun(null);
    getRun(runId)
      .then((r) => {
        if (!cancelled) setRun(r);
      })
      .catch((e: unknown) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, [runId]);

  if (error) {
    return (
      <div className="mx-auto max-w-[1280px] px-6 py-8">
        <Link
          href="/company-agent"
          className="font-mono text-[11px] tracking-[0.08em] uppercase text-[var(--ink-muted)] hover:text-[var(--ink)]"
        >
          ← back to company agent
        </Link>
        <Card className="mt-4 border-[color-mix(in_srgb,var(--loss)_40%,transparent)] p-4 text-[12px] text-[var(--loss)]">
          加载公司档案失败：{error}
        </Card>
      </div>
    );
  }

  if (!run) {
    return (
      <div className="mx-auto max-w-[1280px] px-6 py-12">
        <div className="font-mono text-[11px] tracking-[0.08em] uppercase text-[var(--ink-faint)]">
          loading dossier…
        </div>
      </div>
    );
  }

  return <CompanyDossierView run={run} />;
}
