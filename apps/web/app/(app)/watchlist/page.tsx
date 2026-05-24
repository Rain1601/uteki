"use client";

import { useState } from "react";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { WATCHLIST, type Market, type AssetKind } from "@/lib/demo";
import { Plus, Globe, MapPin } from "lucide-react";

type FilterMarket = "all" | Market;
type FilterKind = "all" | AssetKind;

export default function WatchlistPage() {
  const [market, setMarket] = useState<FilterMarket>("all");
  const [kind, setKind] = useState<FilterKind>("all");

  const items = WATCHLIST.filter(
    (i) => (market === "all" || i.market === market) && (kind === "all" || i.kind === kind),
  );

  return (
    <PageContainer>
      <PageHeader
        eyebrow="WORKSPACE · WATCHLIST"
        title="关注列表"
        subtitle="按市场（中国 / 美国）与品类（公司 / ETF）维护标的。任务页基于本表创建调度。"
        actions={
          <>
            <Badge tone="warn">DEMO DATA</Badge>
            <Button variant="primary"><Plus size={14} /> 新增标的</Button>
          </>
        }
      />

      {/* Filter rails */}
      <div className="mb-6 flex flex-wrap items-center gap-6">
        <FilterRail
          icon={<Globe size={14} className="text-[var(--ink-faint)]" />}
          label="MARKET"
          value={market}
          onChange={(v) => setMarket(v as FilterMarket)}
          options={[
            { value: "all", label: "All" },
            { value: "US",  label: "US" },
            { value: "CN",  label: "中国" },
          ]}
        />
        <FilterRail
          icon={<MapPin size={14} className="text-[var(--ink-faint)]" />}
          label="KIND"
          value={kind}
          onChange={(v) => setKind(v as FilterKind)}
          options={[
            { value: "all",   label: "All" },
            { value: "stock", label: "公司" },
            { value: "etf",   label: "ETF" },
          ]}
        />
        <div className="ml-auto font-mono text-[11px] tracking-[0.08em] text-[var(--ink-faint)]">
          {items.length} / {WATCHLIST.length}
        </div>
      </div>

      {/* Table */}
      <div className="overflow-hidden rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface)]">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[var(--line)] bg-[var(--surface-1)]">
              <Th>SYMBOL</Th>
              <Th>NAME</Th>
              <Th>MARKET</Th>
              <Th>KIND</Th>
              <Th>SECTOR</Th>
              <Th align="right">LAST</Th>
              <Th align="right">CHG %</Th>
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr
                key={item.id}
                className="border-b border-[var(--line)] last:border-0 hover:bg-[var(--surface-hover)] transition-colors"
              >
                <td className="px-5 py-3 numeric text-[13px] text-[var(--ink)] tracking-tight">
                  {item.symbol}
                </td>
                <td className="px-5 py-3 font-display italic text-[15px] text-[var(--ink)]">
                  {item.name}
                </td>
                <td className="px-5 py-3">
                  <Badge tone={item.market === "US" ? "accent" : "warn"}>{item.market}</Badge>
                </td>
                <td className="px-5 py-3">
                  <Badge>{item.kind === "stock" ? "公司" : "ETF"}</Badge>
                </td>
                <td className="px-5 py-3 text-[12px] text-[var(--ink-muted)]">{item.sector}</td>
                <td className="px-5 py-3 text-right numeric text-[13px] text-[var(--ink)]">
                  {item.last?.toFixed(2) ?? "—"}
                </td>
                <td className="px-5 py-3 text-right">
                  <span
                    className={`numeric text-[13px] ${
                      (item.change_pct ?? 0) >= 0
                        ? "text-[var(--gain)]"
                        : "text-[var(--loss)]"
                    }`}
                  >
                    {(item.change_pct ?? 0) >= 0 ? "+" : ""}
                    {item.change_pct?.toFixed(2) ?? "0.00"}%
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="mt-6 text-[11px] leading-relaxed text-[var(--ink-faint)]">
        ⓘ 本页展示数据 / 交互骨架，未接入实时行情。后端就位后将通过 <span className="font-mono text-[var(--ink-muted)]">GET /api/watchlist</span> 拉取。
      </p>
    </PageContainer>
  );
}

function Th({ children, align = "left" }: { children: React.ReactNode; align?: "left" | "right" }) {
  return (
    <th
      className={`px-5 py-3 font-mono text-[9px] font-semibold tracking-[0.18em] uppercase text-[var(--ink-faint)] ${
        align === "right" ? "text-right" : "text-left"
      }`}
    >
      {children}
    </th>
  );
}

function FilterRail({
  icon,
  label,
  value,
  onChange,
  options,
}: {
  icon: React.ReactNode;
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="flex items-center gap-2">
      {icon}
      <span className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
        {label}
      </span>
      <div className="flex gap-1 rounded-md border border-[var(--line)] bg-[var(--surface-1)] p-[2px]">
        {options.map((o) => (
          <button
            key={o.value}
            onClick={() => onChange(o.value)}
            className={`px-2.5 py-1 font-mono text-[11px] tracking-[0.04em] rounded-[3px] transition-colors ${
              value === o.value
                ? "bg-[var(--surface-2)] text-[var(--ink)]"
                : "text-[var(--ink-muted)] hover:text-[var(--ink-soft)]"
            }`}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
