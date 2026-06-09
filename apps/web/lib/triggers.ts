/**
 * Hardcoded trigger fixtures.
 *
 * Triggers don't live in the DB yet — the backend's TriggerRegistry is
 * in-memory and the frontend has historically owned the displayable
 * trigger metadata. Extracted from /tasks/page.tsx so the trigger
 * detail page can look them up by ID without duplicating the constant.
 *
 * When triggers become persisted (and this constant becomes a fetched
 * /api/triggers response), the consuming pages can swap the lookup
 * source without changing their UI.
 */

import {
  Bell,
  CalendarClock,
  FileText,
  Newspaper,
  TrendingUp,
} from "lucide-react";

export type TriggerKind = "news" | "earnings" | "event" | "price" | "schedule";

export interface AgentTrigger {
  id: string;
  name: string;
  kind: TriggerKind;
  watchlist_ids: string[];
  skill: string;
  condition: string;
  cadence: string;
  enabled: boolean;
  last_triggered_at?: number;
  next_check_at?: number;
  last_status?: "ok" | "error" | "listening";
}

const NOW = Date.now() / 1000;
const HOUR = 3600;
const DAY = 86400;

export const TRIGGERS: AgentTrigger[] = [
  {
    id: "trg-news-001",
    name: "宏观经济 · 非公司个体新闻",
    kind: "news",
    watchlist_ids: [],
    skill: "uteki",
    condition:
      "CNBC macro feed (jeff-cox) + Fed / CPI / GDP / 政策事件。明确不收公司个体新闻 — 公司流走 trg-news-002。",
    cadence: "每 30 分钟扫描",
    enabled: true,
    last_triggered_at: NOW - 5 * HOUR,
    next_check_at: NOW + 18 * 60,
    last_status: "listening",
  },
  {
    id: "trg-news-002",
    name: "公司个体 · Yahoo per-ticker 新闻流",
    kind: "news",
    watchlist_ids: ["us-aapl", "us-nvda", "us-msft", "us-googl", "us-tsla"],
    skill: "uteki",
    condition:
      "Yahoo Finance Search per-ticker；启发式相关度过滤（title 含 ticker / 公司主词 / Yahoo primary tag）。",
    cadence: "每 60 分钟扫描",
    enabled: true,
    last_triggered_at: NOW - 1 * HOUR,
    next_check_at: NOW + 8 * 60,
    last_status: "listening",
  },
  {
    id: "trg-earnings-002",
    name: "财报发布 / 电话会 transcript",
    kind: "earnings",
    watchlist_ids: ["us-nvda", "us-msft", "us-aapl"],
    skill: "company_research_pipeline",
    condition: "10-Q / 10-K / earnings transcript becomes available",
    cadence: "交易日盘前 + 盘后",
    enabled: true,
    last_triggered_at: NOW - 2 * DAY,
    next_check_at: NOW + 3 * HOUR,
    last_status: "ok",
  },
  {
    id: "trg-event-003",
    name: "监管 / 诉讼 / 并购事件",
    kind: "event",
    watchlist_ids: ["us-googl", "us-tsla"],
    skill: "research",
    condition: "SEC filing, antitrust, M&A, guidance revision",
    cadence: "事件源 webhook + 每日补扫",
    enabled: true,
    last_triggered_at: NOW - 9 * HOUR,
    next_check_at: NOW + 42 * 60,
    last_status: "ok",
  },
  {
    id: "trg-price-004",
    name: "价格 / 成交量异常",
    kind: "price",
    watchlist_ids: ["us-nvda", "us-soxx", "us-qqq"],
    skill: "uteki",
    condition: "price move > 5% OR volume > 2.5x 20D average",
    cadence: "盘中每 15 分钟",
    enabled: false,
    last_triggered_at: NOW - 6 * DAY,
    last_status: "error",
  },
  {
    id: "trg-cron-005",
    name: "每周组合复盘",
    kind: "schedule",
    watchlist_ids: ["us-spy", "us-qqq", "cn-510300", "cn-159915"],
    skill: "research_pipeline",
    condition: "cron: 0 17 * * 5",
    cadence: "每周五收盘后",
    enabled: true,
    last_triggered_at: NOW - 4 * DAY,
    next_check_at: NOW + 3 * DAY,
    last_status: "ok",
  },
];

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

export function getTrigger(id: string): AgentTrigger | undefined {
  return TRIGGERS.find((t) => t.id === id);
}
