"use client";

import { useCallback, useEffect, useState } from "react";
import {
  AlertTriangle,
  Pause,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody } from "@/components/ui/Card";
import {
  deleteTrigger,
  listTriggers,
  patchTrigger,
  upsertTrigger,
  type ApiTrigger,
} from "@/lib/api";
import { invalidateTriggers } from "@/lib/triggers";
import { cn } from "@/lib/cn";

const KINDS = ["news", "earnings", "event", "price", "schedule"] as const;
type Kind = (typeof KINDS)[number];

const KIND_LABEL: Record<Kind, string> = {
  news: "新闻",
  earnings: "财报",
  event: "事件",
  price: "价格",
  schedule: "定时",
};

function formatRelative(iso: string | null): string {
  if (!iso) return "—";
  const seconds = (Date.now() - new Date(iso).getTime()) / 1000;
  const abs = Math.abs(seconds);
  const suffix = seconds >= 0 ? "前" : "后";
  if (abs < 60) return seconds >= 0 ? "刚刚" : "马上";
  if (abs < 3600) return `${Math.round(abs / 60)} 分钟${suffix}`;
  if (abs < 86400) return `${Math.round(abs / 3600)} 小时${suffix}`;
  return `${Math.round(abs / 86400)} 天${suffix}`;
}

function statusTone(status: string): "gain" | "loss" | "warn" | "neutral" {
  if (status === "ok") return "gain";
  if (status === "error") return "loss";
  if (status === "listening") return "warn";
  return "neutral";
}

export default function AdminTriggersPage() {
  const [triggers, setTriggers] = useState<ApiTrigger[]>([]);
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const rows = await listTriggers();
      setTriggers(rows);
      invalidateTriggers(); // bust other pages' cached fixture
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function handlePatch(id: string, patch: Partial<ApiTrigger>) {
    setError(null);
    try {
      const updated = await patchTrigger(
        id,
        patch as Parameters<typeof patchTrigger>[1],
      );
      setTriggers((prev) => prev.map((t) => (t.id === updated.id ? updated : t)));
      invalidateTriggers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "update failed");
    }
  }

  async function handleDelete(t: ApiTrigger) {
    if (
      !window.confirm(
        `删除 trigger "${t.name}"？\n${t.id} 这条规则将不再调度运行。已有 trigger_hit 历史记录保留但会孤立（详情页跳到 404）。`,
      )
    )
      return;
    setError(null);
    try {
      await deleteTrigger(t.id);
      setTriggers((prev) => prev.filter((x) => x.id !== t.id));
      invalidateTriggers();
    } catch (e) {
      setError(e instanceof Error ? e.message : "delete failed");
    }
  }

  async function handleCreate(body: {
    id: string;
    name: string;
    kind: Kind;
    cadence_minutes: number;
  }) {
    setError(null);
    try {
      await upsertTrigger({
        id: body.id,
        name: body.name,
        kind: body.kind,
        cadence_minutes: body.cadence_minutes,
        cadence_text: `每 ${body.cadence_minutes} 分钟`,
        enabled: true,
        sort_order: triggers.length + 1,
      });
      setCreating(false);
      void refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "create failed");
    }
  }

  return (
    <PageContainer>
      <PageHeader
        eyebrow="ADMIN · TRIGGER REGISTRY"
        title="触发器管理"
        subtitle="trigger 是一条监听规则：规则命中后由 scheduler (P10.2) 拉数据 + 触发 agent。改完即时生效（其他页面下次拉数据会刷新）。"
        actions={
          <>
            <Badge tone="accent">{triggers.length} triggers</Badge>
            <Button variant="ghost" onClick={refresh} disabled={loading}>
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
              刷新
            </Button>
            <Button variant="primary" onClick={() => setCreating(true)} disabled={creating}>
              <Plus size={13} /> 新建触发器
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
              onSubmit={handleCreate}
              onCancel={() => setCreating(false)}
            />
          </CardBody>
        </Card>
      )}

      <div className="space-y-3">
        {triggers.map((t) => (
          <TriggerCard
            key={t.id}
            trigger={t}
            expanded={expandedId === t.id}
            onToggle={() => setExpandedId(expandedId === t.id ? null : t.id)}
            onPatch={(p) => handlePatch(t.id, p)}
            onDelete={() => handleDelete(t)}
          />
        ))}
      </div>

      <p className="mt-6 text-[11px] leading-relaxed text-[var(--ink-faint)]">
        cadence_minutes = 0 表示 event-driven（不轮询，等 webhook）。
        earnings_window_hours + boost_minutes 联动：财报事件临近窗口内会改用更快的 boost 节奏。
      </p>
    </PageContainer>
  );
}

// ─── Card per trigger ────────────────────────────────────────────────

function TriggerCard({
  trigger,
  expanded,
  onToggle,
  onPatch,
  onDelete,
}: {
  trigger: ApiTrigger;
  expanded: boolean;
  onToggle: () => void;
  onPatch: (p: Partial<ApiTrigger>) => void;
  onDelete: () => void;
}) {
  return (
    <Card className={cn("overflow-hidden", !trigger.enabled && "opacity-65")}>
      <div className="grid gap-4 p-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)_minmax(0,0.7fr)_auto]">
        <div>
          <div className="flex items-center gap-2">
            <Badge tone={trigger.enabled ? "gain" : "neutral"}>
              {trigger.enabled ? "enabled" : "paused"}
            </Badge>
            <Badge tone="accent">{KIND_LABEL[trigger.kind as Kind] ?? trigger.kind}</Badge>
            <Badge tone={statusTone(trigger.last_status)}>{trigger.last_status}</Badge>
          </div>
          <button
            type="button"
            onClick={onToggle}
            className="mt-2 block text-left"
          >
            <div className="font-display text-[18px] italic text-[var(--ink)]">
              {trigger.name}
            </div>
            <div className="font-mono text-[10px] tracking-[0.06em] text-[var(--ink-faint)]">
              {trigger.id} · skill={trigger.skill}
            </div>
          </button>
        </div>

        <div className="text-[12px] leading-relaxed text-[var(--ink-soft)]">
          {trigger.condition || (
            <span className="italic text-[var(--ink-faint)]">无 condition</span>
          )}
          <div className="mt-2 flex flex-wrap gap-1">
            {trigger.watchlist_symbols.length === 0 ? (
              <span className="font-mono text-[9px] tracking-[0.1em] text-[var(--ink-faint)]">
                全 watchlist
              </span>
            ) : (
              trigger.watchlist_symbols.map((s) => (
                <span
                  key={s}
                  className="rounded-sm border border-[var(--line)] bg-[var(--surface-2)] px-1.5 py-0.5 font-mono text-[9px] text-[var(--ink)]"
                >
                  {s}
                </span>
              ))
            )}
          </div>
        </div>

        <div className="space-y-1 font-mono text-[10px] text-[var(--ink-muted)]">
          <div>
            cadence:{" "}
            <span className="text-[var(--ink-soft)]">
              {trigger.cadence_minutes === 0
                ? "event-driven"
                : `${trigger.cadence_minutes} min`}
            </span>
          </div>
          {trigger.earnings_window_hours > 0 && (
            <div className="text-[var(--warn)]">
              earnings boost: {trigger.boost_in_earnings_window_minutes}min ±
              {trigger.earnings_window_hours}h
            </div>
          )}
          <div>last: {formatRelative(trigger.last_triggered_at)}</div>
          {trigger.enabled && trigger.next_check_at && (
            <div>next: {formatRelative(trigger.next_check_at)}</div>
          )}
        </div>

        <div className="flex items-start gap-1">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => onPatch({ enabled: !trigger.enabled })}
          >
            {trigger.enabled ? (
              <>
                <Pause size={12} /> 暂停
              </>
            ) : (
              <>
                <Play size={12} /> 启用
              </>
            )}
          </Button>
          <button
            type="button"
            onClick={onDelete}
            title="删除"
            className="inline-flex h-7 w-7 items-center justify-center rounded border border-[var(--line)] text-[var(--ink-faint)] transition-colors hover:border-[color-mix(in_srgb,var(--loss)_40%,transparent)] hover:text-[var(--loss)]"
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      {expanded && (
        <div
          className="border-t border-[var(--line)] bg-[var(--surface)] px-5 py-4"
          style={{ animation: "label-in 220ms var(--ease-out) both" }}
        >
          <EditPanel trigger={trigger} onPatch={onPatch} />
        </div>
      )}

      {trigger.last_status === "error" && (
        <div className="flex items-center gap-2 border-t border-[var(--line)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)] px-5 py-2 font-mono text-[10px] text-[var(--loss)]">
          <AlertTriangle size={11} />
          last run failed — check scheduler logs
        </div>
      )}
    </Card>
  );
}

// ─── Edit panel (expanded) ───────────────────────────────────────────

function EditPanel({
  trigger,
  onPatch,
}: {
  trigger: ApiTrigger;
  onPatch: (p: Partial<ApiTrigger>) => void;
}) {
  const [name, setName] = useState(trigger.name);
  const [condition, setCondition] = useState(trigger.condition);
  const [cadenceMin, setCadenceMin] = useState(trigger.cadence_minutes.toString());
  const [cadenceText, setCadenceText] = useState(trigger.cadence_text);
  const [symbolsCsv, setSymbolsCsv] = useState(trigger.watchlist_symbols.join(", "));
  const [earningsWindow, setEarningsWindow] = useState(trigger.earnings_window_hours.toString());
  const [boost, setBoost] = useState(trigger.boost_in_earnings_window_minutes.toString());

  function commit<K extends keyof ApiTrigger>(field: K, value: ApiTrigger[K]) {
    onPatch({ [field]: value } as Partial<ApiTrigger>);
  }

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
      <Field label="NAME">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          onBlur={() => name !== trigger.name && commit("name", name)}
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 text-[13px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
      <Field label="WATCHLIST SYMBOLS (CSV, 空 = 全部)">
        <input
          value={symbolsCsv}
          onChange={(e) => setSymbolsCsv(e.target.value)}
          onBlur={() => {
            const arr = symbolsCsv
              .split(",")
              .map((s) => s.trim().toUpperCase())
              .filter(Boolean);
            commit("watchlist_symbols", arr);
          }}
          placeholder="AAPL, NVDA, MSFT"
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
      <Field label="CONDITION" wide>
        <textarea
          value={condition}
          onChange={(e) => setCondition(e.target.value)}
          onBlur={() => condition !== trigger.condition && commit("condition", condition)}
          rows={2}
          className="w-full border border-[var(--line)] bg-[var(--surface)] px-2 py-1.5 text-[12px] text-[var(--ink-soft)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
      <Field label="CADENCE (分钟，0 = event-driven)">
        <input
          type="number"
          min="0"
          max="10080"
          value={cadenceMin}
          onChange={(e) => setCadenceMin(e.target.value)}
          onBlur={() => commit("cadence_minutes", parseInt(cadenceMin || "0", 10))}
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
      <Field label="CADENCE 显示文本">
        <input
          value={cadenceText}
          onChange={(e) => setCadenceText(e.target.value)}
          onBlur={() => commit("cadence_text", cadenceText)}
          placeholder="每 60 分钟"
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
      <Field label="EARNINGS WINDOW (小时，0 = 关闭)">
        <input
          type="number"
          min="0"
          max="72"
          value={earningsWindow}
          onChange={(e) => setEarningsWindow(e.target.value)}
          onBlur={() => commit("earnings_window_hours", parseInt(earningsWindow || "0", 10))}
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
      <Field label="BOOST CADENCE (分钟)">
        <input
          type="number"
          min="0"
          max="1440"
          value={boost}
          onChange={(e) => setBoost(e.target.value)}
          onBlur={() => commit("boost_in_earnings_window_minutes", parseInt(boost || "0", 10))}
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
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
    <div className={wide ? "md:col-span-2" : undefined}>
      <div className="mb-1.5 font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
        {label}
      </div>
      {children}
    </div>
  );
}

// ─── Create form ─────────────────────────────────────────────────────

function CreateForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (body: { id: string; name: string; kind: Kind; cadence_minutes: number }) => void;
  onCancel: () => void;
}) {
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [kind, setKind] = useState<Kind>("news");
  const [cadenceMin, setCadenceMin] = useState("60");

  const valid = id.trim() && name.trim();

  return (
    <div className="grid grid-cols-1 gap-3 md:grid-cols-[180px_1fr_120px_120px_auto]">
      <Field label="ID">
        <input
          autoFocus
          value={id}
          onChange={(e) => setId(e.target.value)}
          placeholder="trg-news-003"
          className="h-9 w-full border border-[var(--line-strong)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
      <Field label="NAME">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="新闻监听 · ..."
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 text-[13px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
      <Field label="KIND">
        <select
          value={kind}
          onChange={(e) => setKind(e.target.value as Kind)}
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        >
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {KIND_LABEL[k]}
            </option>
          ))}
        </select>
      </Field>
      <Field label="CADENCE (分钟)">
        <input
          type="number"
          min="0"
          value={cadenceMin}
          onChange={(e) => setCadenceMin(e.target.value)}
          className="h-9 w-full border border-[var(--line)] bg-[var(--surface)] px-2 font-mono text-[12px] text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </Field>
      <div className="flex items-end gap-2">
        <Button variant="ghost" onClick={onCancel}>
          <X size={12} /> 取消
        </Button>
        <Button
          variant="primary"
          onClick={() =>
            valid &&
            onSubmit({
              id: id.trim(),
              name: name.trim(),
              kind,
              cadence_minutes: parseInt(cadenceMin || "0", 10),
            })
          }
          disabled={!valid}
        >
          创建
        </Button>
      </div>
    </div>
  );
}
