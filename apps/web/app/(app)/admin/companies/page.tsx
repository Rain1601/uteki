"use client";

import { useCallback, useEffect, useState } from "react";
import {
  Archive,
  ArchiveRestore,
  ExternalLink,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import {
  createCompany,
  deleteCompany,
  listCompanies,
  patchCompany,
  type Company,
  type CompanyCreate,
} from "@/lib/api";
import { cn } from "@/lib/cn";

const MARKETS = ["US", "CN", "HK", "TW"] as const;
const VERDICTS = ["BUY", "WATCH", "AVOID", "UNRATED"] as const;

function verdictTone(v: string): "gain" | "loss" | "warn" | "neutral" {
  if (v === "BUY") return "gain";
  if (v === "AVOID") return "loss";
  if (v === "WATCH") return "warn";
  return "neutral";
}

export default function AdminCompaniesPage() {
  // Auth + redirect handled by /admin layout.
  const [companies, setCompanies] = useState<Company[]>([]);
  const [includeArchived, setIncludeArchived] = useState(false);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setCompanies(await listCompanies(!includeArchived));
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }, [includeArchived]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handleCreate(body: CompanyCreate) {
    setError(null);
    try {
      const created = await createCompany(body);
      setCompanies((prev) => {
        const without = prev.filter((c) => c.symbol !== created.symbol);
        return [created, ...without];
      });
      setCreating(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "create failed");
    }
  }

  async function handlePatch(symbol: string, patch: Partial<Company>) {
    setError(null);
    try {
      // Patch shapes overlap; the API accepts any subset and validates.
      const updated = await patchCompany(
        symbol,
        patch as Parameters<typeof patchCompany>[1],
      );
      setCompanies((prev) =>
        prev.map((c) => (c.symbol === updated.symbol ? updated : c)),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "update failed");
    }
  }

  async function handleArchive(company: Company) {
    if (!window.confirm(`归档 ${company.symbol}（${company.name}）？可以稍后恢复。`)) return;
    setError(null);
    try {
      await deleteCompany(company.symbol, false);
      if (includeArchived) {
        setCompanies((prev) =>
          prev.map((c) =>
            c.symbol === company.symbol ? { ...c, watch: false } : c,
          ),
        );
      } else {
        setCompanies((prev) => prev.filter((c) => c.symbol !== company.symbol));
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "archive failed");
    }
  }

  async function handleHardDelete(company: Company) {
    if (
      !window.confirm(
        `永久删除 ${company.symbol}？这会移除所有相关记录，不能撤销。`,
      )
    )
      return;
    setError(null);
    try {
      await deleteCompany(company.symbol, true);
      setCompanies((prev) => prev.filter((c) => c.symbol !== company.symbol));
    } catch (e) {
      setError(e instanceof Error ? e.message : "delete failed");
    }
  }

  return (
    <PageContainer>
      <PageHeader
        eyebrow="ADMIN · COMPANY WATCHLIST"
        title="公司管理"
        subtitle="watchlist 是整套 ingestion 的 source-of-truth。这里录入的 ticker / CIK / IR RSS 被研究台、SEC EDGAR connector、新闻拉取共用。归档 = watch=false（数据保留），仅在右上勾选才会显示。"
        actions={
          <>
            <Badge tone="accent">
              {companies.filter((c) => c.watch).length} 关注
            </Badge>
            <label className="inline-flex items-center gap-1.5 font-mono text-[10px] tracking-[0.05em] text-[var(--ink-muted)]">
              <input
                type="checkbox"
                checked={includeArchived}
                onChange={(e) => setIncludeArchived(e.target.checked)}
                className="accent-[var(--accent)]"
              />
              显示归档
            </label>
            <Button variant="ghost" onClick={refresh} disabled={loading}>
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
              刷新
            </Button>
            <Button
              variant="primary"
              onClick={() => setCreating(true)}
              disabled={creating}
            >
              <Plus size={13} /> 添加公司
            </Button>
          </>
        }
      />

      {error && (
        <div className="mb-4 border border-[color-mix(in_srgb,var(--loss)_40%,transparent)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)] px-4 py-3 font-mono text-[11px] text-[var(--loss)]">
          {error}
        </div>
      )}

      {creating && (
        <Card className="mb-5">
          <CardBody>
            <CreateCompanyForm
              existingSymbols={new Set(companies.map((c) => c.symbol))}
              onSubmit={handleCreate}
              onCancel={() => setCreating(false)}
            />
          </CardBody>
        </Card>
      )}

      <Card>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left">
            <thead className="border-b border-[var(--line)] font-mono text-[9px] uppercase tracking-[0.18em] text-[var(--ink-faint)]">
              <tr>
                <th className="px-5 py-3">Company</th>
                <th className="px-5 py-3">Market</th>
                <th className="px-5 py-3">Sector / Peers</th>
                <th className="px-5 py-3">Verdict</th>
                <th className="px-5 py-3">CIK / IR</th>
                <th className="px-5 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--line)]">
              {companies.map((c) => (
                <CompanyRow
                  key={c.symbol}
                  company={c}
                  expanded={expandedId === c.symbol}
                  onToggle={() =>
                    setExpandedId(expandedId === c.symbol ? null : c.symbol)
                  }
                  onPatch={(p) => handlePatch(c.symbol, p)}
                  onArchive={() => handleArchive(c)}
                  onHardDelete={() => handleHardDelete(c)}
                />
              ))}
              {companies.length === 0 && !loading && (
                <tr>
                  <td colSpan={6} className="px-5 py-12 text-center text-[12px] text-[var(--ink-muted)]">
                    还没有公司。点右上"添加公司"开始，或运行 `uv run python services/api/scripts/seed_companies.py` 灌入默认 6 家。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <p className="mt-6 text-[11px] leading-relaxed text-[var(--ink-faint)]">
        CIK 是 SEC EDGAR 的 Central Index Key，零填充 10 位（如 AAPL = 0000320193）。
        填了之后 P7 SEC EDGAR connector 会按这个值订阅 8-K / 10-Q / 10-K。
        IR RSS 可选，是公司投资者关系页的 RSS feed。
      </p>
    </PageContainer>
  );
}

// ─── Row ─────────────────────────────────────────────────────────────

function CompanyRow({
  company,
  expanded,
  onToggle,
  onPatch,
  onArchive,
  onHardDelete,
}: {
  company: Company;
  expanded: boolean;
  onToggle: () => void;
  onPatch: (p: Partial<Company>) => void;
  onArchive: () => void;
  onHardDelete: () => void;
}) {
  return (
    <>
      <tr
        className={cn(
          "hover:bg-[var(--surface-hover)]",
          !company.watch && "opacity-50",
        )}
      >
        <td className="px-5 py-3.5">
          <button
            type="button"
            onClick={onToggle}
            className="block min-w-0 text-left"
          >
            <div className="font-display text-[16px] italic text-[var(--ink)]">
              {company.symbol}
              {!company.watch && (
                <span className="ml-2 font-mono text-[9px] tracking-[0.12em] text-[var(--ink-faint)]">
                  · 已归档
                </span>
              )}
            </div>
            <div className="font-mono text-[11px] text-[var(--ink-muted)]">
              {company.name}
            </div>
          </button>
        </td>
        <td className="px-5 py-3.5">
          <Badge tone="neutral">{company.market}</Badge>
        </td>
        <td className="px-5 py-3.5">
          <div className="text-[12px] text-[var(--ink-soft)]">
            {company.sector || <span className="italic text-[var(--ink-faint)]">—</span>}
          </div>
          {company.peers.length > 0 && (
            <div className="mt-1 flex flex-wrap gap-1">
              {company.peers.slice(0, 3).map((p) => (
                <span
                  key={p}
                  className="font-mono text-[9px] tracking-[0.04em] text-[var(--ink-faint)]"
                >
                  {p}
                </span>
              ))}
              {company.peers.length > 3 && (
                <span className="font-mono text-[9px] text-[var(--ink-faint)]">
                  +{company.peers.length - 3}
                </span>
              )}
            </div>
          )}
        </td>
        <td className="px-5 py-3.5">
          <div className="flex flex-col gap-1">
            <Badge tone={verdictTone(company.verdict)}>{company.verdict}</Badge>
            {company.conviction != null && (
              <span className="font-mono text-[9px] tracking-[0.06em] text-[var(--ink-faint)]">
                conv {company.conviction.toFixed(2)}
              </span>
            )}
          </div>
        </td>
        <td className="px-5 py-3.5">
          <div className="space-y-0.5 font-mono text-[10px] text-[var(--ink-muted)]">
            <div>{company.cik || <span className="italic text-[var(--ink-faint)]">no CIK</span>}</div>
            {company.ir_rss_url && (
              <a
                href={company.ir_rss_url}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 text-[var(--accent)] hover:underline"
              >
                IR <ExternalLink size={9} />
              </a>
            )}
          </div>
        </td>
        <td className="px-5 py-3.5 text-right">
          <div className="inline-flex gap-1">
            {company.watch ? (
              <Button size="sm" variant="ghost" onClick={onArchive}>
                <Archive size={11} />
                归档
              </Button>
            ) : (
              <Button
                size="sm"
                variant="ghost"
                onClick={() => onPatch({ watch: true })}
              >
                <ArchiveRestore size={11} />
                恢复
              </Button>
            )}
            <Button size="sm" variant="ghost" onClick={onHardDelete}>
              <Trash2 size={11} />
            </Button>
          </div>
        </td>
      </tr>
      {expanded && (
        <tr className="bg-[var(--surface)]">
          <td colSpan={6} className="px-5 py-4">
            <EditPanel company={company} onPatch={onPatch} />
          </td>
        </tr>
      )}
    </>
  );
}

// ─── Edit panel (expanded row) ───────────────────────────────────────

function EditPanel({
  company,
  onPatch,
}: {
  company: Company;
  onPatch: (p: Partial<Company>) => void;
}) {
  const [name, setName] = useState(company.name);
  const [sector, setSector] = useState(company.sector);
  const [peers, setPeers] = useState(company.peers.join(", "));
  const [cik, setCik] = useState(company.cik ?? "");
  const [irUrl, setIrUrl] = useState(company.ir_rss_url ?? "");
  const [notes, setNotes] = useState(company.notes);

  function commit(field: keyof Company, value: unknown) {
    onPatch({ [field]: value } as Partial<Company>);
  }

  return (
    <div className="grid gap-4 md:grid-cols-2">
      <EditField label="NAME" value={name} onChange={setName} onCommit={(v) => commit("name", v)} />
      <EditField
        label="SECTOR"
        value={sector}
        onChange={setSector}
        onCommit={(v) => commit("sector", v)}
      />
      <EditField
        label="PEERS (CSV)"
        value={peers}
        onChange={setPeers}
        onCommit={(v) =>
          commit(
            "peers",
            v.split(",").map((s) => s.trim().toUpperCase()).filter(Boolean),
          )
        }
      />
      <EditField
        label="CIK (SEC EDGAR)"
        value={cik}
        onChange={setCik}
        onCommit={(v) => commit("cik", v || null)}
        placeholder="0000320193"
      />
      <div className="md:col-span-2">
        <EditField
          label="IR RSS URL"
          value={irUrl}
          onChange={setIrUrl}
          onCommit={(v) => commit("ir_rss_url", v || null)}
          placeholder="https://investor.apple.com/rss/news-releases.aspx"
        />
      </div>
      <div className="md:col-span-2">
        <EditTextarea
          label="NOTES"
          value={notes}
          onChange={setNotes}
          onCommit={(v) => commit("notes", v)}
        />
      </div>
      <div>
        <FieldLabel>VERDICT</FieldLabel>
        <div className="flex gap-1">
          {VERDICTS.map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => commit("verdict", v)}
              className={cn(
                "rounded-sm border px-2.5 py-1 font-mono text-[10px] tracking-[0.04em] transition-colors",
                company.verdict === v
                  ? "border-[var(--accent-line)] bg-[var(--accent-soft)] text-[var(--accent)]"
                  : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink-soft)]",
              )}
            >
              {v}
            </button>
          ))}
        </div>
      </div>
      <div>
        <FieldLabel>CONVICTION (0–1)</FieldLabel>
        <input
          type="number"
          step="0.05"
          min="0"
          max="1"
          defaultValue={company.conviction ?? ""}
          onBlur={(e) => {
            const v = e.target.value;
            commit("conviction", v === "" ? null : parseFloat(v));
          }}
          className="h-9 w-32 border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </div>
    </div>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="mb-1.5 font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
      {children}
    </div>
  );
}

function EditField({
  label,
  value,
  onChange,
  onCommit,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  onCommit: (v: string) => void;
  placeholder?: string;
}) {
  return (
    <div>
      <FieldLabel>{label}</FieldLabel>
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={() => onCommit(value)}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            (e.target as HTMLInputElement).blur();
          }
        }}
        placeholder={placeholder}
        className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none placeholder:text-[var(--ink-faint)] focus:border-[var(--accent)]"
      />
    </div>
  );
}

function EditTextarea({
  label,
  value,
  onChange,
  onCommit,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  onCommit: (v: string) => void;
}) {
  return (
    <div>
      <FieldLabel>{label}</FieldLabel>
      <textarea
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onBlur={() => onCommit(value)}
        rows={3}
        placeholder="自由形式备注，比如最近研究结论、关键风险等。"
        className="w-full border border-[var(--line)] bg-[var(--surface)] px-2 py-2 text-[12px] text-[var(--ink-soft)] outline-none placeholder:text-[var(--ink-faint)] focus:border-[var(--accent)]"
      />
    </div>
  );
}

// ─── Create form ─────────────────────────────────────────────────────

function CreateCompanyForm({
  existingSymbols,
  onSubmit,
  onCancel,
}: {
  existingSymbols: Set<string>;
  onSubmit: (body: CompanyCreate) => void;
  onCancel: () => void;
}) {
  const [symbol, setSymbol] = useState("");
  const [name, setName] = useState("");
  const [market, setMarket] = useState<(typeof MARKETS)[number]>("US");
  const [sector, setSector] = useState("");
  const [cik, setCik] = useState("");

  const trimmedSym = symbol.trim().toUpperCase();
  const conflict = trimmedSym && existingSymbols.has(trimmedSym);

  function submit() {
    if (!trimmedSym || !name.trim()) return;
    onSubmit({
      symbol: trimmedSym,
      name: name.trim(),
      market,
      sector,
      peers: [],
      cik: cik.trim() || null,
      verdict: "UNRATED",
    });
  }

  return (
    <div className="grid gap-3 md:grid-cols-[120px_1fr_80px_1fr_140px_auto]">
      <div>
        <FieldLabel>SYMBOL</FieldLabel>
        <input
          autoFocus
          value={symbol}
          onChange={(e) => setSymbol(e.target.value.toUpperCase())}
          placeholder="AAPL"
          className="h-9 w-full border border-[var(--line-strong)] bg-[var(--surface)] px-2 font-display text-[15px] italic text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </div>
      <div>
        <FieldLabel>NAME</FieldLabel>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Apple Inc."
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 text-[13px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </div>
      <div>
        <FieldLabel>MARKET</FieldLabel>
        <select
          value={market}
          onChange={(e) => setMarket(e.target.value as (typeof MARKETS)[number])}
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        >
          {MARKETS.map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>
      <div>
        <FieldLabel>SECTOR</FieldLabel>
        <input
          value={sector}
          onChange={(e) => setSector(e.target.value)}
          placeholder="Consumer Tech"
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </div>
      <div>
        <FieldLabel>CIK (可选)</FieldLabel>
        <input
          value={cik}
          onChange={(e) => setCik(e.target.value)}
          placeholder="0000320193"
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </div>
      <div className="flex items-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          <X size={12} /> 取消
        </Button>
        <Button
          variant="primary"
          onClick={submit}
          disabled={!trimmedSym || !name.trim()}
          title={conflict ? "已存在 — 提交会更新该公司" : undefined}
        >
          {conflict ? "更新" : "创建"}
        </Button>
      </div>
    </div>
  );
}
