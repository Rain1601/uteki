/**
 * Trigger metadata accessors.
 *
 * Triggers are now persisted in the DB (P10.1). This module wraps the
 * /api/triggers endpoint with a module-scope cache so consumers can do
 * `await loadTriggers()` once per page and not re-fetch on every render.
 *
 * The fixture this module used to export (AgentTrigger array of 5 items)
 * is gone — page-level consumers fetch directly. Display helpers
 * (KIND_ICON / KIND_LABEL) stay here because they're pure UI metadata.
 */

import {
  Bell,
  CalendarClock,
  FileText,
  Newspaper,
  TrendingUp,
} from "lucide-react";
import { listTriggers, type ApiTrigger } from "./api";

export type TriggerKind = "news" | "earnings" | "event" | "price" | "schedule";

/** UI-shaped trigger. Identical to the API row plus a relative-time hint
 *  field the rendering layer will compute on demand. */
export type AgentTrigger = ApiTrigger;

export const KIND_LABEL: Record<TriggerKind, string> = {
  news: "新闻",
  earnings: "财报",
  event: "事件",
  price: "价格",
  schedule: "定时",
};

export const KIND_ICON: Record<
  TriggerKind,
  React.ComponentType<{ size?: number; className?: string }>
> = {
  news: Newspaper,
  earnings: FileText,
  event: Bell,
  price: TrendingUp,
  schedule: CalendarClock,
};

// Module-scope cache. First caller fetches; concurrent callers share the
// same in-flight promise; later callers get the resolved array.
let cache: AgentTrigger[] | null = null;
let inflight: Promise<AgentTrigger[]> | null = null;

export async function loadTriggers(force = false): Promise<AgentTrigger[]> {
  if (!force && cache) return cache;
  if (!force && inflight) return inflight;
  inflight = listTriggers().then((rows) => {
    cache = rows;
    inflight = null;
    return rows;
  });
  return inflight;
}

/** Invalidate the cache — call after admin edits land. */
export function invalidateTriggers(): void {
  cache = null;
  inflight = null;
}

export async function getTrigger(id: string): Promise<AgentTrigger | undefined> {
  const rows = await loadTriggers();
  return rows.find((t) => t.id === id);
}
