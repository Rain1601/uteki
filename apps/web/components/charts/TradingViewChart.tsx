"use client";

// TradingView Advanced Chart embed — ported from uteki.open.
//
// We use TradingView's free embed widget (script-loaded), NOT the licensed
// charting library. The widget is a fire-and-forget iframe: we inject a
// <script> with a JSON config, the script renders a <div> with the chart.
//
// Defaults applied (matching uteki.open's TradingViewEmbed):
//   - EMA(20) auto-overlay        — short-term trend
//   - SMA(50) auto-overlay         — medium-term trend
//   - 日 K (interval=D) default    — most common for fundamental research
//   - theme follows the page's data-theme attribute (light/dark)
//
// Lifecycle: the widget is mounted once on first render and intentionally
// never re-renders. To swap symbols, unmount + remount the parent. This
// matches the uteki.open pattern and avoids the widget's own state machine
// fighting React's.

import { useEffect, useRef } from "react";

interface Props {
  /** TradingView symbol, e.g. "NASDAQ:GOOGL", "TPE:2330", "SSE:600519". If
   *  the exchange prefix is omitted (e.g. "AAPL"), TradingView auto-resolves
   *  to the most likely listing. */
  symbol: string;
  /** Optional explicit theme override. When omitted, reads
   *  `document.documentElement.getAttribute("data-theme")` on mount —
   *  `"light"` → light theme, anything else → dark (uteki default). */
  theme?: "dark" | "light";
}

export function TradingViewChart({ symbol, theme }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mountedRef = useRef(false);

  useEffect(() => {
    if (mountedRef.current || !containerRef.current) return;
    mountedRef.current = true;

    const resolvedTheme: "dark" | "light" =
      theme ??
      (typeof document !== "undefined" &&
      document.documentElement.getAttribute("data-theme") === "light"
        ? "light"
        : "dark");

    const wrapper = document.createElement("div");
    wrapper.className = "tradingview-widget-container";
    wrapper.style.width = "100%";
    wrapper.style.height = "100%";

    const widgetDiv = document.createElement("div");
    widgetDiv.className = "tradingview-widget-container__widget";
    widgetDiv.style.width = "100%";
    widgetDiv.style.height = "100%";
    wrapper.appendChild(widgetDiv);

    const script = document.createElement("script");
    script.type = "text/javascript";
    script.async = true;
    script.src =
      "https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js";
    script.textContent = JSON.stringify({
      symbol,
      interval: "D",
      timezone: "Etc/UTC",
      theme: resolvedTheme,
      style: "1",
      locale: "zh_CN",
      allow_symbol_change: false,
      hide_top_toolbar: false,
      hide_side_toolbar: false,
      // EMA + SMA auto-overlays — same as uteki.open
      studies: ["MAExp@tv-basicstudies", "MASimple@tv-basicstudies"],
      studies_overrides: {
        "moving average exponential.length": 20,
        "moving average.length": 50,
      },
      width: "100%",
      height: "100%",
    });

    wrapper.appendChild(script);
    containerRef.current.appendChild(wrapper);
  }, [symbol, theme]);

  return (
    <div
      ref={containerRef}
      className="h-full w-full overflow-hidden"
      style={{ background: theme === "light" ? "#fff" : "#131722" }}
    />
  );
}

/**
 * Map an internal CompanyWatchItem-style symbol/market to a TradingView
 * symbol. Returns just the raw symbol with no prefix when TradingView's
 * auto-resolution is the safe path (most US tickers).
 *
 * Examples:
 *   { symbol: "GOOGL", market: "US" }       → "NASDAQ:GOOGL"
 *   { symbol: "TSM", market: "US" }          → "NYSE:TSM"  (caller hint)
 *   { symbol: "2330", market: "TW" }         → "TPE:2330"
 *   { symbol: "300750.SZ", market: "CN" }   → "SZSE:300750"
 *   { symbol: "600519.SH", market: "CN" }   → "SSE:600519"
 */
export function toTradingViewSymbol(item: {
  symbol: string;
  market?: string;
}): string {
  const raw = item.symbol.trim().toUpperCase();
  const market = (item.market ?? "").toUpperCase();

  if (market === "CN" || /\.(SH|SZ)$/.test(raw)) {
    if (raw.endsWith(".SH")) return `SSE:${raw.replace(".SH", "")}`;
    if (raw.endsWith(".SZ")) return `SZSE:${raw.replace(".SZ", "")}`;
    return raw;
  }
  if (market === "TW") {
    return `TPE:${raw.replace(/\.TW$/, "")}`;
  }
  if (market === "HK" || raw.endsWith(".HK")) {
    return `HKEX:${raw.replace(".HK", "")}`;
  }
  // US: prefer NASDAQ for tickers TradingView most commonly resolves there.
  // The widget will silently fall back to NYSE for symbols not on NASDAQ,
  // so this prefix is just a hint, not a hard constraint.
  if (market === "US") {
    return `NASDAQ:${raw}`;
  }
  // Unknown market — let TradingView auto-resolve.
  return raw;
}
