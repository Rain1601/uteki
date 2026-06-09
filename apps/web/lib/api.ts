import { API_BASE } from "./api-base";
import { authedFetch, getAccessToken } from "./auth";
import type { AgentEvent, ChatMessage } from "./types";

export { API_BASE };

export interface ChatStreamRequest {
  messages: ChatMessage[];
  session_id?: string;
  agent?: string;
  model?: string;
}

/**
 * Stream agent events from POST /api/agent/chat (SSE).
 * Yields a typed AgentEvent for each line. Uses fetch + ReadableStream so it
 * works with POST (EventSource doesn't).
 *
 * M4: injects the access token directly because SSE is a long-lived stream
 * — we can't transparently retry it on 401 the way ``authedFetch`` does for
 * one-shot requests. If the token is expired the page should re-fetch via
 * ``authedFetch`` first (any prior call will have refreshed it) and then
 * call this. Callers handle the 401 by redirecting to /login.
 */
export async function* streamChat(
  req: ChatStreamRequest,
  signal?: AbortSignal,
): AsyncGenerator<AgentEvent> {
  const token = getAccessToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    Accept: "text/event-stream",
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const resp = await fetch(`${API_BASE}/api/agent/chat`, {
    method: "POST",
    headers,
    body: JSON.stringify(req),
    signal,
    credentials: "include",
  });
  if (!resp.ok || !resp.body) {
    const detail = await resp.text().catch(() => "");
    throw new Error(detail || `chat stream failed: ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);

      let dataLine = "";
      for (const line of raw.split("\n")) {
        if (line.startsWith("data:")) {
          dataLine += line.slice(5).trim();
        }
      }
      if (!dataLine) continue;
      try {
        yield JSON.parse(dataLine) as AgentEvent;
      } catch {
        // ignore malformed frames
      }
    }
  }
}

export interface ListRunsParams {
  skill?: string;
  triggered_by?: string;
  limit?: number;
}

export async function listRuns(
  params: ListRunsParams = {},
): Promise<{ items: RunSummary[] }> {
  const qs = new URLSearchParams();
  if (params.skill) qs.set("skill", params.skill);
  if (params.triggered_by) qs.set("triggered_by", params.triggered_by);
  if (params.limit != null) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  const r = await authedFetch(`${API_BASE}/api/runs${suffix}`, {
    cache: "no-store",
  });
  return r.json();
}

export async function getRun(id: string): Promise<RunDetail> {
  const r = await authedFetch(`${API_BASE}/api/runs/${id}`, {
    cache: "no-store",
  });
  return r.json();
}

export async function listAgents(): Promise<{ items: AgentInfo[] }> {
  const r = await authedFetch(`${API_BASE}/api/agents`, { cache: "no-store" });
  return r.json();
}

export async function getAgent(name: string): Promise<AgentDetail> {
  const r = await authedFetch(`${API_BASE}/api/agents/${name}`, {
    cache: "no-store",
  });
  return r.json();
}

export async function listVersions(
  name: string,
): Promise<{ items: SkillVersion[] }> {
  const r = await authedFetch(`${API_BASE}/api/agents/${name}/versions`, {
    cache: "no-store",
  });
  return r.json();
}

export interface CompareRunRequest {
  messages: ChatMessage[];
  agents: string[];
  model?: string;
}

export async function compareRun(
  req: CompareRunRequest,
): Promise<CompareRunResponse> {
  const r = await authedFetch(`${API_BASE}/api/compare/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return r.json();
}

export interface CompareDiffRequest {
  run_ids: string[];
}

export async function compareDiff(
  req: CompareDiffRequest,
): Promise<CompareDiffResponse> {
  const r = await authedFetch(`${API_BASE}/api/compare/diff`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return r.json();
}

export interface RunSummary {
  id: string;
  skill: string;
  skill_version?: string | null;
  triggered_by: string;
  trigger_reason?: string;
  started_at: number;
  ended_at?: number | null;
  status: string;
  user_input?: string;
  summary?: string;
  tags?: string[];
  artifact_count?: number;
  primary_artifact?: ArtifactRef | null;
}

export interface RunDetail extends RunSummary {
  events: AgentEvent[];
  artifacts?: ArtifactRef[];
  events_summary?: Record<string, number>;
}

export interface AgentInfo {
  name: string;
  description: string;
  version: string;
  default_tools?: string[];
  default_model?: string;
  kind?: "skill" | "pipeline";
}

export interface AgentDetail extends AgentInfo {
  current_version?: SkillVersion | null;
}

export interface SkillVersion {
  skill: string;
  version: string;
  prompt: string;
  tool_names: string[];
  model: string;
  params: Record<string, unknown>;
  created_at: number;
  parent_version?: string;
  changelog?: string;
}

export interface CompareRunResponse {
  run_ids: string[];
}

export interface CompareDiffEntry {
  id: string;
  skill: string;
  latency_ms?: number;
  tools_called: string[];
  usage?: Record<string, unknown>;
  summary?: string;
  final_text?: string;
}

export interface CompareDiffResponse {
  runs: CompareDiffEntry[];
}

// ─── Artifacts (M5) ─────────────────────────────────────────────────────

export type ArtifactKind = "markdown" | "json" | "text" | "binary";

export interface Artifact {
  run_id: string;
  name: string;
  kind: ArtifactKind;
  size_bytes: number;
  sha256: string;
  created_at: number;
  written_by: string;
  description: string;
  content_type: string;
}

export interface ArtifactRef {
  name: string;
  kind: ArtifactKind;
  size_bytes: number;
  written_by: string;
  description?: string;
  url: string;
  role?: string;
  display_name?: string;
  source_refs?: number[];
}

export async function listArtifacts(
  runId: string,
): Promise<{ items: Artifact[] }> {
  const r = await authedFetch(`${API_BASE}/api/runs/${runId}/artifacts`, {
    cache: "no-store",
  });
  return r.json();
}

export function artifactUrl(runId: string, name: string): string {
  return `${API_BASE}/api/runs/${runId}/artifacts/${name}`;
}

export async function fetchArtifactText(
  runId: string,
  name: string,
): Promise<string> {
  const r = await authedFetch(artifactUrl(runId, name), { cache: "no-store" });
  return r.text();
}

// ─── Eval history (M7) ─────────────────────────────────────────────────

export interface EvalRecord {
  case_id: string;
  started_at: number;
  pass_rate: number;
  judge_scores: Record<string, number>;
  decision: string | null;
  run_id: string | null;
  notes: string;
}

export async function listEvalCaseHistory(
  caseId: string,
  limit = 50,
): Promise<{ items: EvalRecord[] }> {
  const r = await authedFetch(
    `${API_BASE}/api/eval/cases/${encodeURIComponent(caseId)}/history?limit=${limit}`,
    { cache: "no-store" },
  );
  return r.json();
}

export async function listEvalHistory(
  limit = 100,
): Promise<{ items: EvalRecord[] }> {
  const r = await authedFetch(`${API_BASE}/api/eval/history?limit=${limit}`, {
    cache: "no-store",
  });
  return r.json();
}

export async function reloadSkills(): Promise<{
  cleared: string[];
  skipped: string[];
  count: number;
}> {
  const r = await authedFetch(`${API_BASE}/api/admin/reload-skills`, {
    method: "POST",
  });
  return r.json();
}

// ─── News analysis SSE ─────────────────────────────────────────────

export type NewsAnalyzeEvent =
  | { type: "delta"; content: string }
  | { type: "done"; impact: string | null; analysis: string }
  | { type: "error"; message: string };

/**
 * Stream an AI analysis for a news article. The backend POSTs to
 * /api/news/{id}/analyze and returns SSE frames of the shape above.
 *
 * Caller pattern is identical to ``streamChat`` — for-await-of the
 * generator, abort via the passed AbortSignal.
 */
// ─── Triggers (persisted in DB; replaces hardcoded fixture) ────────

export interface ApiTrigger {
  id: string;
  name: string;
  kind: "news" | "earnings" | "event" | "price" | "schedule" | string;
  skill: string;
  condition: string;
  watchlist_symbols: string[];
  cadence_minutes: number;
  cadence_text: string;
  earnings_window_hours: number;
  boost_in_earnings_window_minutes: number;
  enabled: boolean;
  last_check_at: string | null;
  last_triggered_at: string | null;
  next_check_at: string | null;
  last_status: string;
  sort_order: number;
  created_at: string;
  updated_at: string;
}

export interface ApiTriggerUpsert {
  id: string;
  name: string;
  kind: "news" | "earnings" | "event" | "price" | "schedule";
  skill?: string;
  condition?: string;
  watchlist_symbols?: string[];
  cadence_minutes?: number;
  cadence_text?: string;
  earnings_window_hours?: number;
  boost_in_earnings_window_minutes?: number;
  enabled?: boolean;
  sort_order?: number;
}

export type ApiTriggerPatch = Partial<Omit<ApiTriggerUpsert, "id">>;

export async function listTriggers(enabledOnly = false): Promise<ApiTrigger[]> {
  const qs = enabledOnly ? "?enabled_only=true" : "";
  const r = await authedFetch(`${API_BASE}/api/triggers${qs}`, {
    cache: "no-store",
  });
  if (!r.ok) throw new Error((await r.text()) || `list triggers failed: ${r.status}`);
  return (await r.json()) as ApiTrigger[];
}

export async function upsertTrigger(body: ApiTriggerUpsert): Promise<ApiTrigger> {
  const r = await authedFetch(`${API_BASE}/api/triggers`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.text()) || `upsert trigger failed: ${r.status}`);
  return (await r.json()) as ApiTrigger;
}

export async function patchTrigger(
  id: string,
  patch: ApiTriggerPatch,
): Promise<ApiTrigger> {
  const r = await authedFetch(`${API_BASE}/api/triggers/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error((await r.text()) || `patch trigger failed: ${r.status}`);
  return (await r.json()) as ApiTrigger;
}

export async function deleteTrigger(id: string): Promise<void> {
  const r = await authedFetch(`${API_BASE}/api/triggers/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error((await r.text()) || `delete trigger failed: ${r.status}`);
}

// ─── Earnings calendar ─────────────────────────────────────────────

export interface EarningsEvent {
  id: string;
  symbol: string;
  fiscal_period: string;
  expected_date: string;
  bmo_amc: "BMO" | "AMC" | "DURING" | string;
  status: "scheduled" | "delivered" | "missed" | string;
  delivered_at: string | null;
  related_accession: string | null;
  eps_estimate: number | null;
  eps_actual: number | null;
  revenue_estimate: number | null;
  revenue_actual: number | null;
  call_url: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface EarningsCreate {
  symbol: string;
  fiscal_period: string;
  expected_date: string; // ISO timestamp
  bmo_amc?: "BMO" | "AMC" | "DURING";
  status?: "scheduled" | "delivered" | "missed";
  eps_estimate?: number | null;
  eps_actual?: number | null;
  revenue_estimate?: number | null;
  revenue_actual?: number | null;
  delivered_at?: string | null;
  related_accession?: string | null;
  call_url?: string | null;
  notes?: string;
}

export type EarningsPatch = Partial<EarningsCreate>;

export async function listEarnings(opts?: {
  symbol?: string;
  status?: "scheduled" | "delivered" | "missed";
  upcomingOnly?: boolean;
}): Promise<EarningsEvent[]> {
  const qs = new URLSearchParams();
  if (opts?.symbol) qs.set("symbol", opts.symbol);
  if (opts?.status) qs.set("status", opts.status);
  if (opts?.upcomingOnly) qs.set("upcoming_only", "true");
  const url = `${API_BASE}/api/earnings${qs.toString() ? "?" + qs : ""}`;
  const r = await authedFetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error((await r.text()) || `list earnings failed: ${r.status}`);
  return (await r.json()) as EarningsEvent[];
}

export async function listEarningsNext(): Promise<Record<string, EarningsEvent>> {
  const r = await authedFetch(`${API_BASE}/api/earnings/next`, { cache: "no-store" });
  if (!r.ok) throw new Error((await r.text()) || `earnings/next failed: ${r.status}`);
  return (await r.json()) as Record<string, EarningsEvent>;
}

export async function createEarnings(body: EarningsCreate): Promise<EarningsEvent> {
  const r = await authedFetch(`${API_BASE}/api/earnings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.text()) || `create earnings failed: ${r.status}`);
  return (await r.json()) as EarningsEvent;
}

export async function patchEarnings(
  id: string,
  patch: EarningsPatch,
): Promise<EarningsEvent> {
  const r = await authedFetch(`${API_BASE}/api/earnings/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error((await r.text()) || `patch earnings failed: ${r.status}`);
  return (await r.json()) as EarningsEvent;
}

export async function deleteEarnings(id: string): Promise<void> {
  const r = await authedFetch(`${API_BASE}/api/earnings/${id}`, { method: "DELETE" });
  if (!r.ok) throw new Error((await r.text()) || `delete earnings failed: ${r.status}`);
}

// ─── Companies (watchlist) ─────────────────────────────────────────

export interface Company {
  symbol: string;
  name: string;
  market: "US" | "CN" | "HK" | "TW" | string;
  sector: string;
  peers: string[];
  cik: string | null;
  ir_rss_url: string | null;
  watch: boolean;
  verdict: "BUY" | "WATCH" | "AVOID" | "UNRATED" | string;
  conviction: number | null;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface CompanyCreate {
  symbol: string;
  name: string;
  market?: "US" | "CN" | "HK" | "TW";
  sector?: string;
  peers?: string[];
  cik?: string | null;
  ir_rss_url?: string | null;
  verdict?: "BUY" | "WATCH" | "AVOID" | "UNRATED";
  conviction?: number | null;
  notes?: string;
}

export type CompanyPatch = Partial<CompanyCreate & { watch: boolean }>;

export async function listCompanies(
  watchOnly = true,
): Promise<Company[]> {
  const qs = new URLSearchParams({ watch_only: String(watchOnly) }).toString();
  const r = await authedFetch(`${API_BASE}/api/companies?${qs}`, {
    cache: "no-store",
  });
  if (!r.ok) throw new Error((await r.text()) || `list companies failed: ${r.status}`);
  return (await r.json()) as Company[];
}

export async function createCompany(body: CompanyCreate): Promise<Company> {
  const r = await authedFetch(`${API_BASE}/api/companies`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.text()) || `create company failed: ${r.status}`);
  return (await r.json()) as Company;
}

export async function patchCompany(
  symbol: string,
  patch: CompanyPatch,
): Promise<Company> {
  const r = await authedFetch(`${API_BASE}/api/companies/${symbol}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(patch),
  });
  if (!r.ok) throw new Error((await r.text()) || `patch company failed: ${r.status}`);
  return (await r.json()) as Company;
}

export async function deleteCompany(symbol: string, hard = false): Promise<void> {
  const qs = hard ? "?hard=true" : "";
  const r = await authedFetch(`${API_BASE}/api/companies/${symbol}${qs}`, {
    method: "DELETE",
  });
  if (!r.ok) throw new Error((await r.text()) || `delete company failed: ${r.status}`);
}

export interface NewsFeedbackResponse {
  article_id: string;
  my_feedback: "like" | "dislike" | null;
  like_count: number;
  dislike_count: number;
}

/** Toggle / set / clear a user's feedback on a news article.
 *  Pass null as kind to clear. */
export async function setNewsFeedback(
  articleId: string,
  kind: "like" | "dislike" | null,
): Promise<NewsFeedbackResponse> {
  const r = await authedFetch(`${API_BASE}/api/news/${articleId}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind }),
  });
  if (!r.ok) throw new Error((await r.text()) || `feedback failed: ${r.status}`);
  return (await r.json()) as NewsFeedbackResponse;
}

export async function* streamNewsAnalyze(
  articleId: string,
  signal?: AbortSignal,
): AsyncGenerator<NewsAnalyzeEvent> {
  const token = getAccessToken();
  const headers: Record<string, string> = {
    Accept: "text/event-stream",
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  const resp = await fetch(`${API_BASE}/api/news/${articleId}/analyze`, {
    method: "POST",
    headers,
    signal,
    credentials: "include",
  });
  if (!resp.ok || !resp.body) {
    const detail = await resp.text().catch(() => "");
    throw new Error(detail || `analyze stream failed: ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) !== -1) {
      const raw = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);

      let dataLine = "";
      for (const line of raw.split("\n")) {
        if (line.startsWith("data:")) dataLine += line.slice(5).trim();
      }
      if (!dataLine) continue;
      try {
        yield JSON.parse(dataLine) as NewsAnalyzeEvent;
      } catch {
        // malformed frame
      }
    }
  }
}
