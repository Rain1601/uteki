"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { WATCHLIST, formatRelativeFromNow } from "@/lib/demo";
import {
  AlertTriangle,
  ChevronRight,
  MoreHorizontal,
  Pause,
  Play,
  Plus,
  Radio,
} from "lucide-react";
import {
  KIND_ICON as kindIcon,
  KIND_LABEL as kindLabel,
  TRIGGERS,
  type TriggerKind,
} from "@/lib/triggers";

type TriggerFilter = "all" | TriggerKind;
type StatusFilter = "all" | "enabled" | "paused";

export default function TasksPage() {
  const [kind, setKind] = useState<TriggerFilter>("all");
  const [status, setStatus] = useState<StatusFilter>("all");

  const triggers = useMemo(
    () =>
      TRIGGERS.filter((trigger) => {
        const matchesKind = kind === "all" || trigger.kind === kind;
        const matchesStatus =
          status === "all" ||
          (status === "enabled" && trigger.enabled) ||
          (status === "paused" && !trigger.enabled);
        return matchesKind && matchesStatus;
      }),
    [kind, status],
  );

  return (
    <PageContainer>
      <PageHeader
        eyebrow="WORKSPACE · TRIGGERS"
        title="触发器"
        subtitle="Trigger 不是只有 cron。它负责监听关注列表里的公司新闻、财报发布、重大事件、价格/成交量异常，并在命中规则时启动对应 agent。"
        actions={
          <>
            <Badge tone="accent">trigger registry</Badge>
            <Button variant="primary">
              <Plus size={14} /> 新建触发器
            </Button>
          </>
        }
      />

      <div className="mb-6 flex flex-wrap items-center gap-4">
        <FilterRail
          label="TYPE"
          value={kind}
          onChange={(v) => setKind(v as TriggerFilter)}
          options={[
            { value: "all", label: "All" },
            { value: "news", label: "新闻" },
            { value: "earnings", label: "财报" },
            { value: "event", label: "事件" },
            { value: "price", label: "价格" },
            { value: "schedule", label: "定时" },
          ]}
        />
        <FilterRail
          label="STATUS"
          value={status}
          onChange={(v) => setStatus(v as StatusFilter)}
          options={[
            { value: "all", label: "All" },
            { value: "enabled", label: "监听中" },
            { value: "paused", label: "暂停" },
          ]}
        />
        <div className="ml-auto font-mono text-[11px] tracking-[0.08em] text-[var(--ink-faint)]">
          {triggers.length} / {TRIGGERS.length} triggers
        </div>
      </div>

      <div className="space-y-3">
        {triggers.map((trigger) => {
          const targets = trigger.watchlist_ids
            .map((id) => WATCHLIST.find((w) => w.id === id))
            .filter(Boolean);
          const Icon = kindIcon[trigger.kind];
          return (
            <Card key={trigger.id} className="overflow-hidden">
              <div className="grid gap-4 p-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1.2fr)_minmax(0,0.8fr)]">
                <div>
                  <div className="flex items-start gap-3">
                    <span
                      className={`mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-md border ${
                        trigger.enabled
                          ? "border-[var(--accent-line)] bg-[var(--accent-soft)] text-[var(--accent)]"
                          : "border-[var(--line)] text-[var(--ink-faint)]"
                      }`}
                    >
                      <Icon size={15} />
                    </span>
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={trigger.enabled ? "gain" : "neutral"}>
                          {trigger.enabled ? "listening" : "paused"}
                        </Badge>
                        <Badge tone="accent">{kindLabel[trigger.kind]}</Badge>
                      </div>
                      <div className="mt-2 font-display text-[21px] italic leading-tight text-[var(--ink)]">
                        {trigger.name}
                      </div>
                      <div className="mt-2 font-mono text-[10px] tracking-[0.06em] text-[var(--ink-faint)]">
                        {trigger.id}
                      </div>
                    </div>
                  </div>
                </div>

                <div>
                  <Field label="LISTENING CONDITION">
                    <div className="text-[12px] leading-relaxed text-[var(--ink-soft)]">
                      {trigger.condition}
                    </div>
                  </Field>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {targets.map((target) => (
                      <span
                        key={target!.id}
                        className="inline-flex items-center gap-1.5 rounded-sm border border-[var(--line)] bg-[var(--surface-2)] px-2 py-1"
                      >
                        <span className="numeric text-[11px] text-[var(--ink)]">
                          {target!.symbol}
                        </span>
                        <span className="font-mono text-[9px] tracking-[0.1em] text-[var(--ink-faint)]">
                          {target!.market}
                        </span>
                      </span>
                    ))}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-4 lg:grid-cols-1">
                  <Field label="AGENT">
                    <Badge>{trigger.skill}</Badge>
                  </Field>
                  <Field label="CADENCE">
                    <div className="flex items-center gap-1.5 text-[12px] text-[var(--ink-soft)]">
                      <Radio size={13} className="text-[var(--ink-muted)]" />
                      {trigger.cadence}
                    </div>
                  </Field>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-3 border-t border-[var(--line)] bg-[var(--surface)]/60 px-5 py-2">
                <span className="font-mono text-[10px] tracking-[0.08em] text-[var(--ink-faint)]">
                  last: {formatRelativeFromNow(trigger.last_triggered_at)}
                </span>
                <span className="font-mono text-[10px] tracking-[0.08em] text-[var(--ink-faint)]">
                  next check: {trigger.enabled ? formatRelativeFromNow(trigger.next_check_at) : "paused"}
                </span>
                {trigger.last_status === "error" && (
                  <span className="inline-flex items-center gap-1 font-mono text-[10px] text-[var(--loss)]">
                    <AlertTriangle size={12} /> last trigger failed
                  </span>
                )}
                <div className="ml-auto flex items-center gap-1">
                  <Link
                    href={`/tasks/${trigger.id}`}
                    className="inline-flex h-7 items-center gap-1 rounded-sm border border-[var(--line-strong)] px-2 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-soft)] transition-colors hover:border-[var(--accent-line)] hover:text-[var(--accent)]"
                  >
                    查看新闻流 <ChevronRight size={11} />
                  </Link>
                  <Button size="sm" variant="ghost">
                    {trigger.enabled ? <><Pause size={12} /> 暂停</> : <><Play size={12} /> 启用</>}
                  </Button>
                  <Button size="sm" variant="ghost">立即检查</Button>
                  <Button size="sm" variant="ghost">
                    <MoreHorizontal size={14} />
                  </Button>
                </div>
              </div>
            </Card>
          );
        })}
      </div>

      <p className="mt-6 text-[11px] leading-relaxed text-[var(--ink-faint)]">
        当前页面表达 trigger contract：规则命中后由后端 trigger registry 启动 harness，并把触发来源写入 run。cron 只是 schedule 类型；新闻、财报和事件监听是更核心的入口。
      </p>
    </PageContainer>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1 font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
        {label}
      </div>
      {children}
    </div>
  );
}

function FilterRail({
  label,
  value,
  onChange,
  options,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  options: { value: string; label: string }[];
}) {
  return (
    <div className="flex items-center gap-2">
      <span className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
        {label}
      </span>
      <div className="flex flex-wrap gap-1 rounded-md border border-[var(--line)] bg-[var(--surface-1)] p-[2px]">
        {options.map((option) => (
          <button
            key={option.value}
            onClick={() => onChange(option.value)}
            className={`rounded-[3px] px-2.5 py-1 font-mono text-[11px] tracking-[0.04em] transition-colors ${
              value === option.value
                ? "bg-[var(--surface-2)] text-[var(--ink)]"
                : "text-[var(--ink-muted)] hover:text-[var(--ink-soft)]"
            }`}
          >
            {option.label}
          </button>
        ))}
      </div>
    </div>
  );
}
