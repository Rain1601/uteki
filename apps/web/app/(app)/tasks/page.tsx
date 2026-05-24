"use client";

import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { TASKS, WATCHLIST, formatRelativeFromNow } from "@/lib/demo";
import { Plus, Play, Pause, MoreHorizontal, CalendarClock } from "lucide-react";

const freqLabel: Record<string, string> = {
  "daily-pre-open":   "每个交易日 · 开盘前",
  "daily-post-close": "每个交易日 · 收盘后",
  "weekly":           "每周",
  "custom":           "自定义 cron",
};

export default function TasksPage() {
  return (
    <PageContainer>
      <PageHeader
        eyebrow="WORKSPACE · TASKS"
        title="调度任务"
        subtitle="把关注列表上的标的与 skill / 时间组合成定时任务。到点自动触发 harness，写一条 run 到 /runs，并按 eval 配置打分。"
        actions={
          <>
            <Badge tone="warn">DEMO DATA</Badge>
            <Button variant="primary"><Plus size={14} /> 新建任务</Button>
          </>
        }
      />

      <div className="space-y-3">
        {TASKS.map((t) => {
          const targets = t.watchlist_ids
            .map((id) => WATCHLIST.find((w) => w.id === id))
            .filter(Boolean);
          return (
            <Card key={t.id} className="overflow-hidden">
              <div className="grid grid-cols-12 gap-4 p-5">
                {/* Left column: name + targets */}
                <div className="col-span-5">
                  <div className="flex items-center gap-2">
                    <span
                      className={`h-2 w-2 rounded-full ${
                        t.enabled ? "bg-[var(--gain)] shadow-[0_0_8px_var(--gain)]" : "bg-[var(--ink-faint)]"
                      }`}
                    />
                    <span className="font-display italic text-[18px] tracking-tight text-[var(--ink)]">
                      {t.name}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {targets.map((w) => (
                      <span
                        key={w!.id}
                        className="inline-flex items-center gap-1.5 rounded-md border border-[var(--line)] bg-[var(--surface-2)] px-2 py-1"
                      >
                        <span className="numeric text-[11px] text-[var(--ink)]">{w!.symbol}</span>
                        <span className="font-mono text-[9px] tracking-[0.1em] text-[var(--ink-faint)]">
                          {w!.market}
                        </span>
                      </span>
                    ))}
                  </div>
                </div>

                {/* Middle: skill + schedule */}
                <div className="col-span-4 grid grid-cols-2 gap-4">
                  <Field label="SKILL">
                    <Badge tone="accent">{t.skill}</Badge>
                  </Field>
                  <Field label="SCHEDULE">
                    <div className="flex items-center gap-1.5">
                      <CalendarClock size={13} className="text-[var(--ink-muted)]" />
                      <span className="text-[12px] text-[var(--ink-soft)]">
                        {freqLabel[t.frequency] ?? t.frequency}
                      </span>
                    </div>
                    {t.cron && (
                      <div className="mt-1 font-mono text-[10px] text-[var(--ink-faint)]">
                        {t.cron}
                      </div>
                    )}
                  </Field>
                </div>

                {/* Right: last + next */}
                <div className="col-span-3 grid grid-cols-2 gap-4">
                  <Field label="LAST">
                    <div className="text-[12px] text-[var(--ink-soft)]">
                      {formatRelativeFromNow(t.last_run_at)}
                    </div>
                    {t.last_status && (
                      <div className="mt-1">
                        <Badge tone={t.last_status === "ok" ? "gain" : t.last_status === "error" ? "loss" : "warn"}>
                          {t.last_status}
                        </Badge>
                      </div>
                    )}
                  </Field>
                  <Field label="NEXT">
                    <div className={`text-[12px] ${t.enabled ? "text-[var(--ink-soft)]" : "text-[var(--ink-faint)]"}`}>
                      {t.enabled ? formatRelativeFromNow(t.next_run_at) : "已暂停"}
                    </div>
                  </Field>
                </div>
              </div>

              {/* Action bar */}
              <div className="flex items-center justify-between border-t border-[var(--line)] bg-[var(--surface)]/60 px-5 py-2">
                <span className="font-mono text-[10px] tracking-[0.08em] text-[var(--ink-faint)]">
                  {t.id}
                </span>
                <div className="flex items-center gap-1">
                  <Button size="sm" variant="ghost">
                    {t.enabled ? <><Pause size={12} /> 暂停</> : <><Play size={12} /> 启用</>}
                  </Button>
                  <Button size="sm" variant="ghost">立即运行</Button>
                  <Button size="sm" variant="ghost"><MoreHorizontal size={14} /></Button>
                </div>
              </div>
            </Card>
          );
        })}
      </div>

      <p className="mt-6 text-[11px] leading-relaxed text-[var(--ink-faint)]">
        ⓘ 调度执行通过后端 <span className="font-mono text-[var(--ink-muted)]">triggers/CronTrigger</span> 注册。当前页面演示交互；接入 apscheduler 后会真实按 cron 触发。
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
