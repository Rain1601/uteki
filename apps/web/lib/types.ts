// Mirrors uteki_api/schemas/events.py — keep in sync until `make types`
// auto-generates them from the FastAPI OpenAPI schema.

export type EventType =
  | "run_start"
  | "plan"
  | "step_start"
  | "step_end"
  | "thinking"
  | "tool_call"
  | "tool_result"
  | "delta"
  | "citation"
  | "usage"
  | "log"
  | "artifact_written"
  | "await_review"
  | "subagent_start"
  | "subagent_end"
  | "error"
  | "done";

export interface AgentEvent {
  type: EventType;
  run_id?: string;
  step_id?: string;
  parent_id?: string;
  data: Record<string, unknown>;
  ts: number;
}

export interface ChatMessage {
  role: "system" | "user" | "assistant" | "tool";
  content: string;
}
