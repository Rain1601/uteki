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
