import Link from "next/link";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { SectionTitle } from "@/components/ui/SectionTitle";
import {
  Workflow,
  ArrowRight,
  ArrowDown,
  Shield,
  Database,
  GitBranch,
} from "lucide-react";

export default function HarnessPage() {
  return (
    <PageContainer>
      <PageHeader
        eyebrow="ENGINE · HARNESS"
        title="The Harness"
        subtitle="Harness 是 uteki 的编排核心。Skill 只表达意图（yield AgentEvent），harness 负责真正的执行：分配 run_id、调度工具、限流、落库、绑定版本、捕获异常。前端、评测、对比、调度任务最终都收敛到这一层。"
      />

      {/* The 5 columns */}
      <SectionTitle eyebrow="RESPONSIBILITIES" title="Five jobs the harness owns" />
      <div className="mb-14 grid gap-3 md:grid-cols-5">
        <ResponsibilityCard
          icon={Workflow}
          title="Orchestrate"
          body="读取 skill 的事件流，分配 run_id / step_id，注入运行上下文，把每一条事件流回前端。"
        />
        <ResponsibilityCard
          icon={Shield}
          title="Guard"
          body="max_steps · max_tool_calls · wall_time_seconds。超阈值即终止并发 error。"
        />
        <ResponsibilityCard
          icon={Database}
          title="Persist"
          body="每一条事件双写：memory（短时上下文）+ RunStore（长期回放）。"
        />
        <ResponsibilityCard
          icon={GitBranch}
          title="Bind version"
          body="启动期对比 skill.current_signature() 与 EvolutionStore 最新版本，run 与 vN 绑定。"
        />
        <ResponsibilityCard
          icon={Workflow}
          title="Recover"
          body="单步异常不污染整次 run。捕获 exception → emit error event → 决定继续或终止。"
        />
      </div>

      {/* Lifecycle diagram */}
      <SectionTitle eyebrow="LIFECYCLE" title="One run, end-to-end" />
      <div className="mb-14 overflow-hidden rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface)] p-8">
        <div className="grid grid-cols-1 gap-8 md:grid-cols-[200px_1fr]">
          {/* Triggers column */}
          <div>
            <div className="eyebrow mb-3">TRIGGERS</div>
            <div className="space-y-2">
              {[
                { k: "user", l: "用户对话 / 试运行" },
                { k: "cron", l: "调度任务到点" },
                { k: "event", l: "外部 webhook" },
                { k: "eval", l: "评测回归" },
                { k: "compare", l: "横向对比" },
              ].map((t) => (
                <div
                  key={t.k}
                  className="flex items-center gap-3 rounded-md border border-[var(--line)] bg-[var(--surface-1)] px-3 py-2"
                >
                  <span className="font-mono text-[10px] tracking-[0.14em] uppercase text-[var(--accent)]">
                    {t.k}
                  </span>
                  <span className="text-[11px] text-[var(--ink-soft)]">{t.l}</span>
                </div>
              ))}
            </div>
            <div className="my-4 hidden md:flex justify-end pr-2">
              <ArrowRight size={20} className="text-[var(--accent)]" />
            </div>
            <div className="md:hidden my-4 flex justify-center">
              <ArrowDown size={20} className="text-[var(--accent)]" />
            </div>
          </div>

          {/* Harness core + stream */}
          <div>
            {/* Header */}
            <div className="flex items-center justify-between rounded-t-md border border-[var(--accent-line)] bg-[var(--accent-soft)] px-4 py-2.5">
              <div className="flex items-center gap-2">
                <Workflow size={16} className="text-[var(--accent)]" />
                <span className="font-display italic text-[16px] text-[var(--ink)]">
                  AgentHarness.run( messages )
                </span>
              </div>
              <Badge tone="accent">async generator</Badge>
            </div>

            {/* Event stream visualization */}
            <div className="border-x border-b border-[var(--accent-line)] rounded-b-md bg-[var(--surface-1)] p-5">
              <div className="mb-3 font-mono text-[10px] tracking-[0.14em] uppercase text-[var(--ink-faint)]">
                event stream →
              </div>
              <div className="space-y-1.5">
                <EventStreamLine type="run_start" detail="id=ea88…1d72b5 · skill=research · v1" />
                <EventStreamLine type="plan"      detail='{"steps":["解析意图","拉行情","检索新闻","综合"]}' />
                <EventStreamLine type="step_start" detail='title="拉取行情快照"' />
                <EventStreamLine type="tool_call" detail='market_quote({symbol:"300750.SZ"})' />
                <EventStreamLine type="tool_result" detail='ok=true · 300750.SZ: 268.40 (+1.65%)' />
                <EventStreamLine type="step_end" detail="status=ok" />
                <EventStreamLine type="delta" detail='"针对你的问题…"' />
                <EventStreamLine type="delta" detail='"结合最新行情…"' faded />
                <EventStreamLine type="usage" detail="in=120 out=480" faded />
                <EventStreamLine type="done"  detail="steps=4 · tools=2 · status=ok" />
              </div>
            </div>

            <div className="mt-4 grid grid-cols-3 gap-2 text-center">
              <Sink label="memory" hint="session events" />
              <Sink label="RunStore" hint="run + events + summary" accent />
              <Sink label="SSE → frontend" hint="13 typed events" />
            </div>
          </div>
        </div>
      </div>

      {/* Event vocabulary */}
      <SectionTitle eyebrow="VOCABULARY" title="AgentEvent — 13 typed events" />
      <Card className="mb-14 overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-[var(--line)] bg-[var(--surface-1)]">
              <Th>TYPE</Th>
              <Th>EMITTED BY</Th>
              <Th>DATA SHAPE</Th>
              <Th>RENDERED AS</Th>
            </tr>
          </thead>
          <tbody className="text-[12px]">
            <EventRow type="run_start" emitter="harness" data="agent, session_id" render="时间线起点" />
            <EventRow type="plan" emitter="skill" data="steps: string[]" render="Plan Card" />
            <EventRow type="step_start" emitter="skill" data="title" render="进行中的步骤" />
            <EventRow type="step_end" emitter="skill" data="status" render="步骤完成标记" />
            <EventRow type="thinking" emitter="skill" data="text" render="灰色斜体引文" />
            <EventRow type="tool_call" emitter="skill" data="name, args" render="工具卡片 · 等待态" />
            <EventRow type="tool_result" emitter="harness" data="ok, summary, preview, error?" render="工具卡片 · 完成态" />
            <EventRow type="delta" emitter="skill" data="text" render="助手消息流式增量" />
            <EventRow type="citation" emitter="skill" data="title, source, url?" render="来源引用" />
            <EventRow type="usage" emitter="skill" data="input_tokens, output_tokens" render="顶部 token 统计" />
            <EventRow type="log" emitter="skill / harness" data="level, message, extra?" render="按级别着色日志行" />
            <EventRow type="error" emitter="harness" data="reason" render="红色错误条" />
            <EventRow type="done" emitter="harness" data="steps, tools" render="时间线收口" />
          </tbody>
        </table>
      </Card>

      {/* Cross links */}
      <div className="grid gap-4 md:grid-cols-3">
        <DeepLink href="/runs"   label="去看真实事件流" hint="实际跑过的 run，按时间线回放" />
        <DeepLink href="/evals"  label="评测打分" hint="case-based scoring · 回归告警" />
        <DeepLink href="/agents" label="Skill 演化" hint="prompt / tools / model 变更历史" />
      </div>
    </PageContainer>
  );
}

function ResponsibilityCard({
  icon: Icon,
  title,
  body,
}: {
  icon: React.ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
  title: string;
  body: string;
}) {
  return (
    <Card className="p-4">
      <Icon size={18} strokeWidth={1.5} className="mb-3 text-[var(--accent)]" />
      <div className="font-display italic text-[18px] text-[var(--ink)]">{title}</div>
      <p className="mt-1.5 text-[11px] leading-relaxed text-[var(--ink-muted)]">{body}</p>
    </Card>
  );
}

const eventColors: Record<string, string> = {
  run_start: "var(--ink-muted)",
  plan: "var(--accent)",
  step_start: "var(--info)",
  step_end: "var(--ink-muted)",
  thinking: "var(--ink-faint)",
  tool_call: "var(--warn)",
  tool_result: "var(--gain)",
  delta: "var(--ink)",
  citation: "var(--ink-muted)",
  usage: "var(--ink-faint)",
  log: "var(--ink-faint)",
  error: "var(--loss)",
  done: "var(--gain)",
};

function EventStreamLine({
  type,
  detail,
  faded,
}: {
  type: string;
  detail: string;
  faded?: boolean;
}) {
  const color = eventColors[type] ?? "var(--ink-muted)";
  return (
    <div
      className={`flex items-baseline gap-3 font-mono text-[11px] tracking-[0.02em] ${
        faded ? "opacity-50" : ""
      }`}
    >
      <span className="w-[80px] shrink-0 text-right" style={{ color }}>
        {type}
      </span>
      <span className="text-[var(--ink-faint)]">·</span>
      <span className="truncate text-[var(--ink-soft)]">{detail}</span>
    </div>
  );
}

function Sink({ label, hint, accent }: { label: string; hint: string; accent?: boolean }) {
  return (
    <div
      className={`rounded-md border px-3 py-2 ${
        accent
          ? "border-[var(--accent-line)] bg-[var(--accent-soft)]"
          : "border-[var(--line)] bg-[var(--surface)]"
      }`}
    >
      <div className={`font-mono text-[10px] tracking-[0.12em] uppercase ${accent ? "text-[var(--accent)]" : "text-[var(--ink-soft)]"}`}>
        {label}
      </div>
      <div className="mt-0.5 text-[10px] text-[var(--ink-faint)]">{hint}</div>
    </div>
  );
}

function Th({ children }: { children: React.ReactNode }) {
  return (
    <th className="px-5 py-3 text-left font-mono text-[9px] font-semibold tracking-[0.18em] uppercase text-[var(--ink-faint)]">
      {children}
    </th>
  );
}

function EventRow({
  type,
  emitter,
  data,
  render,
}: {
  type: string;
  emitter: string;
  data: string;
  render: string;
}) {
  const color = eventColors[type] ?? "var(--ink-muted)";
  return (
    <tr className="border-b border-[var(--line)] last:border-0">
      <td className="px-5 py-2.5 font-mono text-[11px]" style={{ color }}>
        {type}
      </td>
      <td className="px-5 py-2.5 text-[11px] text-[var(--ink-muted)]">{emitter}</td>
      <td className="px-5 py-2.5 font-mono text-[10px] text-[var(--ink-soft)]">{data}</td>
      <td className="px-5 py-2.5 text-[11px] text-[var(--ink-soft)]">{render}</td>
    </tr>
  );
}

function DeepLink({ href, label, hint }: { href: string; label: string; hint: string }) {
  return (
    <Link
      href={href}
      className="group flex items-center justify-between rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface-1)] px-5 py-4 hover:border-[var(--accent-line)] transition-colors"
    >
      <div>
        <div className="font-display italic text-[16px] text-[var(--ink)]">{label}</div>
        <div className="mt-0.5 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
          {hint}
        </div>
      </div>
      <ArrowRight size={16} className="text-[var(--ink-faint)] group-hover:text-[var(--accent)] transition-colors" />
    </Link>
  );
}
