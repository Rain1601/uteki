"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  Calendar,
  Check,
  Clock,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  TriangleAlert,
  X,
} from "lucide-react";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import {
  createEarnings,
  deleteEarnings,
  listEarnings,
  listCompanies,
  patchEarnings,
  type Company,
  type EarningsEvent,
} from "@/lib/api";
import { canAdmin, fetchMe, type AuthUser } from "@/lib/auth";
import { cn } from "@/lib/cn";

const BMO_AMC = ["BMO", "DURING", "AMC"] as const;
const STATUSES = ["scheduled", "delivered", "missed"] as const;

function statusTone(status: string): "gain" | "loss" | "warn" | "neutral" | "accent" {
  if (status === "delivered") return "gain";
  if (status === "missed") return "loss";
  if (status === "scheduled") return "accent";
  return "neutral";
}

function relativeDays(iso: string): { label: string; tone: "soon" | "near" | "later" | "past" } {
  const days = Math.round(
    (new Date(iso).getTime() - Date.now()) / (1000 * 60 * 60 * 24),
  );
  if (days < 0) return { label: `${Math.abs(days)}天前`, tone: "past" };
  if (days === 0) return { label: "今天", tone: "soon" };
  if (days <= 3) return { label: `${days}天后`, tone: "soon" };
  if (days <= 14) return { label: `${days}天后`, tone: "near" };
  return { label: `${days}天后`, tone: "later" };
}

function shortDate(iso: string): string {
  return new Date(iso).toLocaleDateString("zh-CN", {
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  });
}

export default function AdminEarningsPage() {
  const router = useRouter();
  const [me, setMe] = useState<AuthUser | null>(null);
  const [checkedAuth, setCheckedAuth] = useState(false);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [events, setEvents] = useState<EarningsEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMe().then((u) => {
      setMe(u);
      setCheckedAuth(true);
      if (!canAdmin(u)) router.replace("/");
    });
  }, [router]);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [companyRows, eventRows] = await Promise.all([
        listCompanies(true),
        listEarnings(),
      ]);
      setCompanies(companyRows);
      setEvents(eventRows);
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (canAdmin(me)) void refresh();
  }, [me, refresh]);

  // Group events by symbol so we can show one row per company.
  const bySymbol = useMemo(() => {
    const map = new Map<string, EarningsEvent[]>();
    for (const ev of events) {
      const arr = map.get(ev.symbol) ?? [];
      arr.push(ev);
      map.set(ev.symbol, arr);
    }
    // expected_date desc within each company (scheduled near top, then delivered desc).
    for (const arr of map.values()) {
      arr.sort((a, b) => {
        if (a.status === "scheduled" && b.status !== "scheduled") return -1;
        if (a.status !== "scheduled" && b.status === "scheduled") return 1;
        return new Date(b.expected_date).getTime() - new Date(a.expected_date).getTime();
      });
    }
    return map;
  }, [events]);

  const upcomingMap = useMemo(() => {
    const out = new Map<string, EarningsEvent>();
    const now = Date.now();
    for (const ev of events) {
      if (ev.status !== "scheduled") continue;
      if (new Date(ev.expected_date).getTime() < now) continue;
      const existing = out.get(ev.symbol);
      if (
        !existing ||
        new Date(ev.expected_date).getTime() < new Date(existing.expected_date).getTime()
      ) {
        out.set(ev.symbol, ev);
      }
    }
    return out;
  }, [events]);

  async function handleCreate(body: {
    symbol: string;
    fiscal_period: string;
    expected_date: string;
    bmo_amc: "BMO" | "AMC" | "DURING";
    eps_estimate?: number | null;
  }) {
    setError(null);
    try {
      await createEarnings(body);
      setCreating(false);
      void refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "create failed");
    }
  }

  async function handlePatch(id: string, patch: Partial<EarningsEvent>) {
    setError(null);
    try {
      const next = await patchEarnings(id, patch as Parameters<typeof patchEarnings>[1]);
      setEvents((prev) => prev.map((ev) => (ev.id === next.id ? next : ev)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "update failed");
    }
  }

  async function handleDelete(ev: EarningsEvent) {
    if (
      !window.confirm(
        `删除 ${ev.symbol} ${ev.fiscal_period}？\n这条事件会从日历移除，但相关 8-K filing 不受影响。`,
      )
    )
      return;
    setError(null);
    try {
      await deleteEarnings(ev.id);
      setEvents((prev) => prev.filter((e) => e.id !== ev.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "delete failed");
    }
  }

  if (!checkedAuth) {
    return (
      <PageContainer>
        <div className="flex h-64 items-center justify-center text-[12px] text-[var(--ink-muted)]">
          <Loader2 size={14} className="mr-2 animate-spin" />
          loading…
        </div>
      </PageContainer>
    );
  }
  if (!canAdmin(me)) return null;

  return (
    <PageContainer>
      <PageHeader
        eyebrow="ADMIN · EARNINGS CALENDAR"
        title="财报日历"
        subtitle="watchlist 公司未来财报日期 + 历史交付记录。SEC 8-K Item 2.02 一旦命中相邻日期会自动标 delivered（P9.4 实施后）；当前需要手动 mark。"
        actions={
          <>
            <Badge tone="gain">
              {upcomingMap.size} upcoming
            </Badge>
            <Badge tone="neutral">
              {events.filter((e) => e.status === "delivered").length} delivered
            </Badge>
            <Button variant="ghost" onClick={refresh} disabled={loading}>
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
              刷新
            </Button>
            <Button variant="primary" onClick={() => setCreating(true)} disabled={creating}>
              <Plus size={13} /> 新建事件
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
            <CreateForm
              companies={companies}
              onSubmit={handleCreate}
              onCancel={() => setCreating(false)}
            />
          </CardBody>
        </Card>
      )}

      <div className="space-y-4">
        {companies.map((c) => {
          const list = bySymbol.get(c.symbol) ?? [];
          const upcoming = upcomingMap.get(c.symbol);
          return (
            <CompanyEarningsCard
              key={c.symbol}
              company={c}
              events={list}
              upcoming={upcoming}
              onPatch={handlePatch}
              onDelete={handleDelete}
            />
          );
        })}
        {companies.length === 0 && !loading && (
          <Card>
            <CardBody className="py-10 text-center text-[12px] text-[var(--ink-muted)]">
              没有 watchlist 公司。先去
              <Link href="/admin/companies" className="ml-1 text-[var(--accent)] hover:underline">
                /admin/companies
              </Link>
              添加。
            </CardBody>
          </Card>
        )}
      </div>

      <p className="mt-6 text-[11px] leading-relaxed text-[var(--ink-faint)]">
        预测事件由 seed 脚本根据上次财报 +90 天估算，仅供参考；admin 应在公司 IR 公布确切日期后修正。
        BMO = before market open · AMC = after market close · DURING = 盘中。
      </p>
    </PageContainer>
  );
}

// ─── Company card ────────────────────────────────────────────────────

function CompanyEarningsCard({
  company,
  events,
  upcoming,
  onPatch,
  onDelete,
}: {
  company: Company;
  events: EarningsEvent[];
  upcoming: EarningsEvent | undefined;
  onPatch: (id: string, patch: Partial<EarningsEvent>) => void;
  onDelete: (ev: EarningsEvent) => void;
}) {
  return (
    <Card>
      <div className="flex flex-wrap items-baseline gap-3 border-b border-[var(--line)] px-5 py-3">
        <div className="font-display text-[20px] italic leading-none text-[var(--ink)]">
          {company.symbol}
        </div>
        <div className="min-w-0 truncate font-display text-[13px] italic text-[var(--ink-muted)]">
          {company.name}
        </div>
        <Badge tone="neutral">{company.market}</Badge>
        {upcoming && <Countdown ev={upcoming} />}
        <span className="ml-auto font-mono text-[10px] tracking-[0.05em] text-[var(--ink-faint)]">
          {events.length} events
        </span>
      </div>
      <CardBody className="p-0">
        {events.length === 0 ? (
          <div className="px-5 py-8 text-center text-[12px] text-[var(--ink-muted)]">
            还没有事件。点上方"新建事件"录入。
          </div>
        ) : (
          <ul className="divide-y divide-[var(--line)]">
            {events.map((ev) => (
              <EventRow
                key={ev.id}
                event={ev}
                onPatch={(patch) => onPatch(ev.id, patch)}
                onDelete={() => onDelete(ev)}
              />
            ))}
          </ul>
        )}
      </CardBody>
    </Card>
  );
}

function Countdown({ ev }: { ev: EarningsEvent }) {
  const rel = relativeDays(ev.expected_date);
  const toneClass =
    rel.tone === "soon"
      ? "text-[var(--loss)] border-[color-mix(in_srgb,var(--loss)_40%,transparent)]"
      : rel.tone === "near"
        ? "text-[var(--warn)] border-[color-mix(in_srgb,var(--warn)_40%,transparent)]"
        : "text-[var(--accent)] border-[var(--accent-line)]";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm border px-2 py-0.5 font-mono text-[10px] tracking-[0.05em]",
        toneClass,
      )}
    >
      <Clock size={10} />
      {rel.label} · {shortDate(ev.expected_date)}
    </span>
  );
}

function EventRow({
  event,
  onPatch,
  onDelete,
}: {
  event: EarningsEvent;
  onPatch: (patch: Partial<EarningsEvent>) => void;
  onDelete: () => void;
}) {
  const [open, setOpen] = useState(false);
  const rel = relativeDays(event.expected_date);

  return (
    <li>
      <div
        className={cn(
          "grid grid-cols-[1fr_120px_90px_90px_140px_60px] items-center gap-3 px-5 py-3 transition-colors hover:bg-[var(--surface-hover)]",
          event.status === "delivered" && "opacity-75",
        )}
      >
        <div className="min-w-0">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="text-left"
          >
            <div className="font-mono text-[12px] tracking-[0.04em] text-[var(--ink)]">
              {event.fiscal_period}
            </div>
            <div className="mt-0.5 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
              {event.notes || (event.related_accession
                ? `linked: ${event.related_accession}`
                : "")}
            </div>
          </button>
        </div>
        <div className="text-[12px] text-[var(--ink-soft)]">
          {shortDate(event.expected_date)}
        </div>
        <div className="font-mono text-[10px] tracking-[0.05em] text-[var(--ink-muted)]">
          {event.bmo_amc}
        </div>
        <div>
          <Badge tone={statusTone(event.status)}>{event.status}</Badge>
        </div>
        <div className="font-mono text-[10px] tracking-[0.05em] text-[var(--ink-muted)]">
          {event.status === "scheduled" ? (
            <span className={rel.tone === "soon" ? "text-[var(--loss)]" : ""}>
              {rel.label}
            </span>
          ) : event.eps_actual != null ? (
            `EPS ${event.eps_actual.toFixed(2)}`
          ) : event.eps_estimate != null ? (
            `est ${event.eps_estimate.toFixed(2)}`
          ) : (
            "—"
          )}
        </div>
        <div className="text-right">
          <button
            type="button"
            onClick={onDelete}
            title="删除"
            className="inline-flex h-6 w-6 items-center justify-center rounded text-[var(--ink-faint)] transition-colors hover:text-[var(--loss)]"
          >
            <Trash2 size={11} />
          </button>
        </div>
      </div>
      {open && (
        <div
          className="border-t border-[var(--line)] bg-[var(--surface)] px-5 py-4"
          style={{ animation: "label-in 220ms var(--ease-out) both" }}
        >
          <EditPanel event={event} onPatch={onPatch} />
        </div>
      )}
    </li>
  );
}

// ─── Edit panel (expanded row) ───────────────────────────────────────

function EditPanel({
  event,
  onPatch,
}: {
  event: EarningsEvent;
  onPatch: (patch: Partial<EarningsEvent>) => void;
}) {
  const [dateInput, setDateInput] = useState(event.expected_date.slice(0, 10));
  const [bmoAmc, setBmoAmc] = useState(event.bmo_amc);
  const [epsEst, setEpsEst] = useState(
    event.eps_estimate?.toString() ?? "",
  );
  const [epsAct, setEpsAct] = useState(event.eps_actual?.toString() ?? "");
  const [notes, setNotes] = useState(event.notes);

  function commit<K extends keyof EarningsEvent>(field: K, value: EarningsEvent[K]) {
    onPatch({ [field]: value } as Partial<EarningsEvent>);
  }

  function commitDate() {
    // Preserve the time-of-day from the original timestamp so "AMC" semantics survive.
    const oldDt = new Date(event.expected_date);
    const newDate = new Date(dateInput);
    newDate.setHours(oldDt.getUTCHours(), oldDt.getUTCMinutes(), 0, 0);
    commit("expected_date", newDate.toISOString());
  }

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
      <Field label="EXPECTED DATE">
        <input
          type="date"
          value={dateInput}
          onChange={(e) => setDateInput(e.target.value)}
          onBlur={commitDate}
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
      <Field label="BMO / AMC / DURING">
        <div className="flex gap-1">
          {BMO_AMC.map((opt) => (
            <button
              key={opt}
              type="button"
              onClick={() => {
                setBmoAmc(opt);
                commit("bmo_amc", opt);
              }}
              className={cn(
                "rounded-sm border px-2 py-1 font-mono text-[10px] tracking-[0.04em] transition-colors",
                bmoAmc === opt
                  ? "border-[var(--accent-line)] bg-[var(--accent-soft)] text-[var(--accent)]"
                  : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink-soft)]",
              )}
            >
              {opt}
            </button>
          ))}
        </div>
      </Field>
      <Field label="STATUS">
        <div className="flex gap-1">
          {STATUSES.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => commit("status", s)}
              className={cn(
                "rounded-sm border px-2 py-1 font-mono text-[10px] tracking-[0.04em] transition-colors",
                event.status === s
                  ? `border-[var(--accent-line)] bg-[var(--accent-soft)] text-[var(--accent)]`
                  : "border-[var(--line)] text-[var(--ink-muted)] hover:text-[var(--ink-soft)]",
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </Field>
      <Field label="EPS ESTIMATE">
        <input
          type="number"
          step="0.01"
          value={epsEst}
          onChange={(e) => setEpsEst(e.target.value)}
          onBlur={() =>
            commit("eps_estimate", epsEst === "" ? null : parseFloat(epsEst))
          }
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
      <Field label="EPS ACTUAL">
        <input
          type="number"
          step="0.01"
          value={epsAct}
          onChange={(e) => setEpsAct(e.target.value)}
          onBlur={() =>
            commit("eps_actual", epsAct === "" ? null : parseFloat(epsAct))
          }
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
      <Field label="NOTES" wide>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          onBlur={() => commit("notes", notes)}
          rows={2}
          className="w-full border border-[var(--line)] bg-[var(--surface)] px-2 py-1.5 text-[12px] text-[var(--ink-soft)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
    </div>
  );
}

function Field({
  label,
  children,
  wide,
}: {
  label: string;
  children: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div className={wide ? "md:col-span-3" : undefined}>
      <div className="mb-1.5 font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
        {label}
      </div>
      {children}
    </div>
  );
}

// ─── Create form ─────────────────────────────────────────────────────

function CreateForm({
  companies,
  onSubmit,
  onCancel,
}: {
  companies: Company[];
  onSubmit: (body: {
    symbol: string;
    fiscal_period: string;
    expected_date: string;
    bmo_amc: "BMO" | "AMC" | "DURING";
    eps_estimate?: number | null;
  }) => void;
  onCancel: () => void;
}) {
  const [symbol, setSymbol] = useState(companies[0]?.symbol ?? "");
  const [fiscalPeriod, setFiscalPeriod] = useState("");
  const [date, setDate] = useState("");
  const [bmoAmc, setBmoAmc] = useState<"BMO" | "AMC" | "DURING">("AMC");
  const [eps, setEps] = useState("");

  const valid = symbol && fiscalPeriod && date;

  function submit() {
    if (!valid) return;
    // Combine date with a default hour based on BMO/AMC convention.
    const dt = new Date(date);
    dt.setHours(bmoAmc === "BMO" ? 12 : bmoAmc === "AMC" ? 20 : 16, 0, 0, 0);
    onSubmit({
      symbol,
      fiscal_period: fiscalPeriod,
      expected_date: dt.toISOString(),
      bmo_amc: bmoAmc,
      eps_estimate: eps ? parseFloat(eps) : null,
    });
  }

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-[120px_180px_140px_120px_120px_auto]">
      <Field label="SYMBOL">
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          className="h-9 w-full border border-[var(--line-strong)] bg-[var(--surface)] px-2 font-display text-[14px] italic text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        >
          {companies.map((c) => (
            <option key={c.symbol} value={c.symbol}>
              {c.symbol}
            </option>
          ))}
        </select>
      </Field>
      <Field label="FISCAL PERIOD">
        <input
          value={fiscalPeriod}
          onChange={(e) => setFiscalPeriod(e.target.value)}
          placeholder="FY2026 Q3"
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
      <Field label="EXPECTED DATE">
        <input
          type="date"
          value={date}
          onChange={(e) => setDate(e.target.value)}
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
      <Field label="BMO / AMC">
        <select
          value={bmoAmc}
          onChange={(e) => setBmoAmc(e.target.value as "BMO" | "AMC" | "DURING")}
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[11px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        >
          {BMO_AMC.map((b) => (
            <option key={b} value={b}>
              {b}
            </option>
          ))}
        </select>
      </Field>
      <Field label="EPS EST. (opt)">
        <input
          type="number"
          step="0.01"
          value={eps}
          onChange={(e) => setEps(e.target.value)}
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
      <div className="flex items-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          <X size={12} /> 取消
        </Button>
        <Button variant="primary" onClick={submit} disabled={!valid}>
          <Check size={12} /> 创建
        </Button>
      </div>
    </div>
  );
}
