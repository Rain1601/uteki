/**
 * Demo data — clearly NOT backed by a real API. Frontend showcase only.
 * When the backend gains watchlist + tasks endpoints, replace these with
 * fetch calls (the shapes are designed to map 1:1).
 */

export type Market = "US" | "CN";
export type AssetKind = "stock" | "etf";

export interface WatchItem {
  id: string;
  symbol: string;
  name: string;
  market: Market;
  kind: AssetKind;
  sector?: string;
  last?: number;
  change_pct?: number;
}

export const WATCHLIST: WatchItem[] = [
  // US Stocks
  { id: "us-aapl", symbol: "AAPL",   name: "Apple Inc.",       market: "US", kind: "stock", sector: "Tech",      last: 234.12, change_pct: 0.82 },
  { id: "us-nvda", symbol: "NVDA",   name: "NVIDIA",           market: "US", kind: "stock", sector: "Semi",      last: 142.55, change_pct: -1.24 },
  { id: "us-tsla", symbol: "TSLA",   name: "Tesla",            market: "US", kind: "stock", sector: "Auto",      last: 359.92, change_pct: 2.14 },
  { id: "us-msft", symbol: "MSFT",   name: "Microsoft",        market: "US", kind: "stock", sector: "Tech",      last: 442.18, change_pct: 0.35 },

  // CN Stocks (A股)
  { id: "cn-300750", symbol: "300750.SZ", name: "宁德时代",  market: "CN", kind: "stock", sector: "新能源",   last: 268.40, change_pct: 1.65 },
  { id: "cn-600519", symbol: "600519.SH", name: "贵州茅台",  market: "CN", kind: "stock", sector: "消费",     last: 1418.0, change_pct: -0.42 },
  { id: "cn-000858", symbol: "000858.SZ", name: "五粮液",    market: "CN", kind: "stock", sector: "消费",     last: 152.30, change_pct: -1.05 },

  // US ETFs
  { id: "us-spy",  symbol: "SPY",  name: "SPDR S&P 500",         market: "US", kind: "etf", sector: "宽基",   last: 612.45, change_pct: 0.18 },
  { id: "us-qqq",  symbol: "QQQ",  name: "Invesco QQQ Trust",    market: "US", kind: "etf", sector: "科技",   last: 528.10, change_pct: 0.62 },
  { id: "us-soxx", symbol: "SOXX", name: "iShares Semi ETF",     market: "US", kind: "etf", sector: "半导体", last: 245.80, change_pct: -1.85 },

  // CN ETFs
  { id: "cn-510300", symbol: "510300.SH", name: "沪深300 ETF",     market: "CN", kind: "etf", sector: "宽基",   last: 4.12, change_pct: 0.45 },
  { id: "cn-159915", symbol: "159915.SZ", name: "创业板 ETF",      market: "CN", kind: "etf", sector: "宽基",   last: 2.86, change_pct: 1.28 },
];

export type Frequency = "daily-pre-open" | "daily-post-close" | "weekly" | "custom";

export interface ScheduledTask {
  id: string;
  name: string;
  watchlist_ids: string[];
  skill: string;
  frequency: Frequency;
  cron?: string;
  enabled: boolean;
  last_run_at?: number;
  next_run_at?: number;
  last_status?: "ok" | "error" | "running";
}

const now = Date.now() / 1000;
const ONE_DAY = 86400;

export const TASKS: ScheduledTask[] = [
  {
    id: "task-001",
    name: "宁德时代 · 每日盘后研报",
    watchlist_ids: ["cn-300750"],
    skill: "research",
    frequency: "daily-post-close",
    cron: "0 16 * * 1-5",
    enabled: true,
    last_run_at: now - 3 * 3600,
    next_run_at: now + 0.4 * ONE_DAY,
    last_status: "ok",
  },
  {
    id: "task-002",
    name: "美股科技 · 每日开盘前简报",
    watchlist_ids: ["us-aapl", "us-nvda", "us-msft", "us-tsla"],
    skill: "recap",
    frequency: "daily-pre-open",
    cron: "0 8 * * 1-5",
    enabled: true,
    last_run_at: now - 16 * 3600,
    next_run_at: now + 0.55 * ONE_DAY,
    last_status: "ok",
  },
  {
    id: "task-003",
    name: "宽基 ETF · 周策略复盘",
    watchlist_ids: ["us-spy", "us-qqq", "cn-510300", "cn-159915"],
    skill: "recap",
    frequency: "weekly",
    cron: "0 17 * * 5",
    enabled: true,
    last_run_at: now - 4 * ONE_DAY,
    next_run_at: now + 3 * ONE_DAY,
    last_status: "ok",
  },
  {
    id: "task-004",
    name: "半导体板块 · 选股扫描",
    watchlist_ids: ["us-nvda", "us-soxx"],
    skill: "screener",
    frequency: "weekly",
    cron: "0 9 * * 1",
    enabled: false,
    last_run_at: now - 7 * ONE_DAY,
    last_status: "error",
  },
];

export function formatRelativeFromNow(ts: number | undefined): string {
  if (ts == null) return "—";
  const nowSec = Date.now() / 1000;
  const diff = ts - nowSec;
  const abs = Math.abs(diff);
  const sign = diff >= 0 ? "in " : "";
  const suffix = diff >= 0 ? "" : " ago";
  if (abs < 60) return `${sign}${Math.round(abs)}s${suffix}`;
  if (abs < 3600) return `${sign}${Math.round(abs / 60)}m${suffix}`;
  if (abs < 86400) return `${sign}${Math.round(abs / 3600)}h${suffix}`;
  return `${sign}${Math.round(abs / 86400)}d${suffix}`;
}
