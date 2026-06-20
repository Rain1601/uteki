import Link from "next/link";
import {
  ArrowUpRight,
  CalendarClock,
  Workflow,
  ClipboardCheck,
  GitCompareArrows,
  Activity,
  Boxes,
} from "lucide-react";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { SectionTitle } from "@/components/ui/SectionTitle";
import { API_BASE } from "@/lib/api";

export default async function Home() {
  // Best-effort fetch from running API. Falls back gracefully if down.
  let agents: { name: string; description: string; version: string }[] = [];
  let runsCount = 0;
  try {
    const a = await fetch(`${API_BASE}/api/agents`, { cache: "no-store" });
    if (a.ok) agents = (await a.json()).items ?? [];
    const r = await fetch(`${API_BASE}/api/runs?limit=100`, { cache: "no-store" });
    if (r.ok) runsCount = ((await r.json()).items ?? []).length;
  } catch {}

  return (
    <PageContainer>
      <PageHeader
        eyebrow="An investment-research agent framework"
        title="Trigger. Harness. Skill. Run."
        subtitle="uteki 把投研流程拆成四个固定环节：你在研究台维护关注公司，触发器监听新闻 / 财报 / 事件 / 定时规则，harness 编排 skill 调度工具，每次执行落成一条可回放、可评测、可对比的 run。"
        actions={
          <Link
            href="/runs"
            className="inline-flex items-center gap-2 rounded-md border border-[var(--accent-line)] bg-[var(--accent-soft)] px-4 py-2 font-mono text-[11px] tracking-[0.08em] uppercase text-[var(--accent)] hover:brightness-110 transition"
          >
            View Runs <ArrowUpRight size={14} />
          </Link>
        }
      />

      {/* Live stats row */}
      <div className="mb-12 grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatCell label="SKILLS" value={String(agents.length || 4)} hint="research · recap · screener · qna" />
        <StatCell label="TOOLS"  value="7" hint="kline · financials · news · …" />
        <StatCell label="RUNS"   value={String(runsCount)} hint="captured by harness" />
        <StatCell label="EVENTS" value="13" hint="typed AgentEvent vocabulary" />
      </div>

      {/* The flow — 5 stages, horizontally */}
      <SectionTitle eyebrow="LIFECYCLE" title="A run in five movements" />
      <div className="mb-14 grid gap-3 md:grid-cols-5">
        <FlowCard
          n="01"
          title="Trigger"
          body="news · earnings · event · cron · user"
          href="/tasks"
          icon={CalendarClock}
        />
        <FlowCard
          n="02"
          title="Harness"
          body="orchestrates · enforces limits · binds version"
          href="/runs"
          icon={Workflow}
          accent
        />
        <FlowCard
          n="03"
          title="Skill"
          body="yields plan · thinking · tool_call · delta"
          href="/skills"
          icon={Boxes}
        />
        <FlowCard
          n="04"
          title="Run"
          body="every event captured · replayable"
          href="/runs"
          icon={Activity}
        />
        <FlowCard
          n="05"
          title="Evaluate"
          body="run quality · judge + 人工打标"
          href="/runs"
          icon={ClipboardCheck}
        />
      </div>

      {/* Two-column: Workspace + Engine */}
      <div className="grid gap-6 md:grid-cols-2">
        <Card className="p-6">
          <div className="mb-4 flex items-center justify-between">
            <SectionTitle eyebrow="Workspace" title="研究台 + 触发器" className="mb-0" />
            <Badge tone="accent">agent triggers</Badge>
          </div>
          <p className="mb-5 text-[13px] leading-relaxed text-[var(--ink-soft)]">
            研究台维护关注公司和同行标签；触发器监听新闻、财报、重大事件、价格异常或 cron。规则命中后启动 harness，skill 跑研究，报告落库。
          </p>
          <div className="space-y-2">
            <NavRow href="/company-agent" icon={Activity} label="研究台 / 关注列表" hint="company watchlist · peer tags" />
            <NavRow href="/tasks"         icon={CalendarClock} label="触发器" hint="news · earnings · events · cron" />
            <NavRow href="/runs"          icon={Activity} label="执行报告" hint={`${runsCount} runs captured`} />
          </div>
        </Card>

        <Card className="p-6">
          <SectionTitle eyebrow="Engine" title="对比 · 评测 · 演化" className="mb-4" />
          <p className="mb-5 text-[13px] leading-relaxed text-[var(--ink-soft)]">
            把同一个问题喂给不同 skill 做横向对比；维护 eval case 集做回归；每个 skill 的 prompt / tool / model 变更自动写入版本历史，run 与版本绑定。
          </p>
          <div className="space-y-2">
            <NavRow href="/runs"    icon={Activity} label="Runs" hint="prod run quality · 人工打标" />
            <NavRow href="/compare" icon={GitCompareArrows} label="Compare" hint="A/B between skills" />
            <NavRow href="/skills"  icon={Boxes} label="Skills" hint="versions · changelog · diff" />
          </div>
        </Card>
      </div>
    </PageContainer>
  );
}

function StatCell({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="border-l-2 border-[var(--line-strong)] pl-4">
      <div className="font-mono text-[9px] tracking-[0.18em] uppercase text-[var(--ink-faint)]">
        {label}
      </div>
      <div className="mt-1 numeric text-[34px] leading-none text-[var(--ink)]">{value}</div>
      <div className="mt-1 text-[11px] text-[var(--ink-muted)]">{hint}</div>
    </div>
  );
}

function FlowCard({
  n,
  title,
  body,
  href,
  icon: Icon,
  accent,
}: {
  n: string;
  title: string;
  body: string;
  href: string;
  icon: React.ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
  accent?: boolean;
}) {
  return (
    <Link
      href={href}
      className={`group relative block overflow-hidden rounded-[var(--r-lg)] border bg-[var(--surface-1)] p-5 transition-all duration-200 ${
        accent
          ? "border-[var(--accent-line)] hover:border-[var(--accent)]"
          : "border-[var(--line)] hover:border-[var(--line-strong)]"
      }`}
    >
      <div className="mb-3 flex items-center justify-between">
        <span className="font-mono text-[10px] tracking-[0.2em] text-[var(--ink-faint)]">
          {n}
        </span>
        <Icon
          size={18}
          strokeWidth={1.75}
          className={`transition-colors ${
            accent ? "text-[var(--accent)]" : "text-[var(--ink-muted)] group-hover:text-[var(--ink)]"
          }`}
        />
      </div>
      <div
        className={`font-display italic text-[20px] tracking-tight ${
          accent ? "text-[var(--ink)]" : "text-[var(--ink)]"
        }`}
      >
        {title}
      </div>
      <div className="mt-1.5 font-mono text-[10px] leading-relaxed tracking-[0.04em] text-[var(--ink-muted)]">
        {body}
      </div>
    </Link>
  );
}

function NavRow({
  href,
  icon: Icon,
  label,
  hint,
}: {
  href: string;
  icon: React.ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
  label: string;
  hint: string;
}) {
  return (
    <Link
      href={href}
      className="group flex items-center gap-3 rounded-md border border-transparent px-3 py-2.5 -mx-3 hover:border-[var(--line)] hover:bg-[var(--surface-hover)] transition-all"
    >
      <Icon size={16} strokeWidth={1.75} className="text-[var(--ink-muted)] group-hover:text-[var(--accent)] transition-colors" />
      <div className="flex-1">
        <div className="font-display italic text-[14px] text-[var(--ink)]">{label}</div>
        <div className="font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">{hint}</div>
      </div>
      <ArrowUpRight size={14} className="text-[var(--ink-faint)] group-hover:text-[var(--accent)] transition-colors" />
    </Link>
  );
}
