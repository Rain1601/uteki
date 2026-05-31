import Link from "next/link";
import { PageHeader } from "@/components/ui/PageHeader";
import { Card } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { SectionTitle } from "@/components/ui/SectionTitle";
import {
  Activity,
  ArrowRight,
  ClipboardCheck,
  Database,
  FileJson,
  GitBranch,
  Radio,
  Route,
  Shield,
  Sparkles,
  Workflow,
  Wrench,
} from "lucide-react";

const runStages = [
  {
    n: "01",
    title: "用户发起",
    actor: "Frontend",
    body: "页面提交 symbol、分析目标和运行参数。前端只关心 run_id、状态和事件流，不直接理解 skill 内部逻辑。",
    event: "POST /api/company-agent/runs",
  },
  {
    n: "02",
    title: "API 创建 run",
    actor: "API",
    body: "鉴权、参数校验、创建 run 记录，然后把请求交给 harness。API 是边界层，不做研究判断。",
    event: "run.status=queued",
  },
  {
    n: "03",
    title: "Harness 接管",
    actor: "Harness",
    body: "分配 run_id、绑定 skill 版本、建立预算、注入 RunContext，并开始消费 skill 产出的 AgentEvent。",
    event: "run_start",
    accent: true,
  },
  {
    n: "04",
    title: "Skill 规划",
    actor: "Skill",
    body: "按业务解析、费雪 15 问、护城河、管理层、逆向检验、估值、最终裁决推进。Skill 表达研究意图。",
    event: "plan / step_start",
  },
  {
    n: "05",
    title: "工具取证",
    actor: "Tools",
    body: "行情、财务、搜索、同行对比等工具由 harness 统一调度。工具结果进入 source ledger，后续引用必须回到目录。",
    event: "tool_call / tool_result",
  },
  {
    n: "06",
    title: "生成结构化产物",
    actor: "Artifacts",
    body: "每个 gate 写出 parsed/raw/citations，并额外生成 claim audit、source quality、run diagnosis 等可检查产物。",
    event: "artifact_written",
  },
  {
    n: "07",
    title: "落库与推流",
    actor: "RunStore",
    body: "事件、步骤、工具调用、最终报告双写到 RunStore，同时通过 SSE 推给前端做实时状态和回放。",
    event: "delta / usage / done",
  },
  {
    n: "08",
    title: "复盘与评测",
    actor: "Evals",
    body: "报告页读取 artifact 展示诊断。评测集可以重放同类 case，对 prompt、工具和模型变更做回归比较。",
    event: "score / compare",
  },
];

const harnessContracts = [
  {
    icon: Workflow,
    title: "运行上下文",
    body: "RunContext 保存 user、run_id、skill、预算、版本和 stores。它让 skill 不需要自己拼全局状态。",
  },
  {
    icon: Radio,
    title: "事件协议",
    body: "AgentEvent 是前后端共同语言。计划、步骤、工具、增量文本、错误和完成态都用同一套 typed event 表达。",
  },
  {
    icon: Wrench,
    title: "工具网关",
    body: "工具不由 skill 直接随意调用。harness 统一记录 tool_call、tool_result、耗时、错误和输出摘要。",
  },
  {
    icon: Shield,
    title: "预算与护栏",
    body: "max_steps、max_tool_calls、wall_time、异常恢复、引用清洗和过程日志过滤都收敛在编排层。",
  },
  {
    icon: Database,
    title: "持久化",
    body: "RunStore 负责长期回放，memory 负责短时上下文，artifact store 负责结构化报告和诊断文件。",
  },
  {
    icon: GitBranch,
    title: "版本绑定",
    body: "每次运行绑定 skill signature。后续 prompt、工具或模型升级后，旧 run 仍能解释自己当时怎么得出结论。",
  },
];

const agentLayers = [
  {
    layer: "Interface",
    title: "页面与入口",
    body: "公司分析页、调度任务、评测和对比入口都可以触发 run。它们共享同一个 harness，不各自造执行链路。",
  },
  {
    layer: "API",
    title: "权限、参数、状态",
    body: "FastAPI 负责 auth、schema、run CRUD、SSE 和 artifact 读取。它把业务请求转换成标准运行请求。",
  },
  {
    layer: "Harness",
    title: "执行内核",
    body: "编排异步事件流，调度工具，控制预算，落库，绑定版本，捕获错误。它是 agent 系统真正可运营的地方。",
    accent: true,
  },
  {
    layer: "Skill",
    title: "研究策略",
    body: "CompanyResearchPipeline 决定先查什么、怎么组织 7 gates、哪些结论需要 source、最终如何形成可解释裁决。",
  },
  {
    layer: "Tools",
    title: "外部世界",
    body: "行情、财务、搜索、同行、新闻和内部数据源只提供证据。工具输出要进入 source ledger，不能直接变成结论。",
  },
  {
    layer: "Quality",
    title: "诊断与评测",
    body: "claim audit 检查关键断言是否有来源，source quality 检查来源质量，evals 检查系统升级是否回退。",
  },
];

const companyGates = [
  "业务解析",
  "费雪 15 问",
  "护城河",
  "管理层",
  "逆向检验",
  "估值与时机",
  "综合裁决",
];

const eventRows = [
  ["run_start", "harness", "run_id, skill, version", "时间线起点"],
  ["plan", "skill", "steps[]", "研究计划"],
  ["step_start", "skill", "title, gate?", "当前步骤"],
  ["tool_call", "skill -> harness", "name, args", "工具等待态"],
  ["tool_result", "harness", "ok, summary, source_ids", "工具完成态"],
  ["delta", "skill", "text", "流式正文"],
  ["citation", "skill", "source_id, url, title", "来源引用"],
  ["artifact", "harness", "name, path, schema", "结构化产物"],
  ["usage", "harness", "tokens, latency", "成本统计"],
  ["error", "harness", "reason, recoverable", "错误条"],
  ["done", "harness", "status, counts", "收口状态"],
];

export default function HarnessPage() {
  return (
    <div className="harness-page mx-auto w-full max-w-6xl px-8 py-12">
      <style>{`
        @media (max-width: 767px) {
          .harness-page {
            box-sizing: border-box;
            width: calc(100vw - var(--sidebar-w-collapsed) - 64px);
            max-width: calc(100vw - var(--sidebar-w-collapsed) - 64px);
            margin-left: 0;
            margin-right: 0;
            padding-left: 12px;
            padding-right: 72px;
            overflow-x: hidden;
          }
        }
      `}</style>
      <PageHeader
        className="flex-col items-start md:flex-row md:items-end"
        eyebrow="ENGINE · HARNESS"
        title="Harness"
        subtitle="这页不是实时控制台，而是一张静态架构导览。目标是让第一次接触 uteki 的人看懂：一次 agent run 从哪里开始，harness 负责什么，company-agent 为什么拆成 7 个 gate，以及报告页里的诊断数据从哪里来。"
        actions={
          <Link
            href="/runs"
            className="inline-flex items-center gap-2 rounded-md border border-[var(--accent-line)] bg-[var(--accent-soft)] px-4 py-2 font-mono text-[11px] tracking-[0.08em] uppercase text-[var(--accent)] transition hover:brightness-110"
          >
            View Runs <ArrowRight size={14} />
          </Link>
        }
      />

      <div className="mb-12 grid gap-4 md:grid-cols-3">
        <IntroMetric label="PAGE TYPE" value="static" hint="解释架构，不消费 live event stream" />
        <IntroMetric label="CORE UNIT" value="run" hint="一次触发到报告完成的完整执行" />
        <IntroMetric label="CONTRACT" value="AgentEvent" hint="前端、harness、skill 共用的事件语言" />
      </div>

      <SectionTitle eyebrow="FULL RUN" title="一次完整运行如何展开" />
      <div className="mb-14 grid gap-3 md:grid-cols-2">
        {runStages.map((stage) => (
          <RunStageCard key={stage.n} {...stage} />
        ))}
      </div>

      <SectionTitle eyebrow="HARNESS DESIGN" title="Harness 到底设计来解决什么问题" />
      <div className="mb-14 grid gap-3 md:grid-cols-3">
        {harnessContracts.map((item) => (
          <ContractCard key={item.title} {...item} />
        ))}
      </div>

      <SectionTitle eyebrow="AGENT STRUCTURE" title="从页面到裁决的系统分层" />
      <div className="mb-14 overflow-hidden rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface-1)]">
        {agentLayers.map((item, index) => (
          <AgentLayerRow key={item.layer} index={index} {...item} />
        ))}
      </div>

      <div className="mb-14 grid gap-6 lg:grid-cols-[1.05fr_0.95fr]">
        <section>
          <SectionTitle eyebrow="COMPANY AGENT" title="7 gate 研究结构" />
          <Card className="p-5">
            <div className="grid gap-2 sm:grid-cols-2">
              {companyGates.map((gate, index) => (
                <div
                  key={gate}
                  className="flex items-center gap-3 rounded-md border border-[var(--line)] bg-[var(--surface)] px-3 py-2.5"
                >
                  <span className="w-7 shrink-0 font-mono text-[10px] tracking-[0.12em] text-[var(--accent)]">
                    G{index + 1}
                  </span>
                  <span className="text-[13px] text-[var(--ink)]">{gate}</span>
                </div>
              ))}
            </div>
            <p className="mt-5 text-[13px] leading-relaxed text-[var(--ink-soft)]">
              每个 gate 都应该产出结构化 JSON、原始 memo、引用列表和质量信号。最终裁决不应只相信大模型自由文本，
              而应回读各 gate 的结构化结果、source ledger、claim audit 和 valuation policy。
            </p>
          </Card>
        </section>

        <section>
          <SectionTitle eyebrow="QUALITY LOOP" title="报告为什么可复查" />
          <div className="space-y-3">
            <QualityItem
              icon={FileJson}
              title="company-claims.json"
              body="抽取关键断言，检查是否能回到 source ledger。没有来源的核心断言会被标成 gap。"
            />
            <QualityItem
              icon={ClipboardCheck}
              title="company-source-quality.json"
              body="按来源层级、可信度、覆盖面和新鲜度打分。低质量来源过多时，报告应显示告警。"
            />
            <QualityItem
              icon={Activity}
              title="company-run-diagnosis.json"
              body="汇总 gate 覆盖、引用缺口、工具错误、决策来源和过程日志泄漏，用于报告页诊断面板。"
            />
          </div>
        </section>
      </div>

      <SectionTitle eyebrow="EVENT VOCABULARY" title="前端看到的不是魔法，是事件流" />
      <Card className="mb-14 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px]">
            <thead>
              <tr className="border-b border-[var(--line)] bg-[var(--surface)]">
                <Th>EVENT</Th>
                <Th>EMITTED BY</Th>
                <Th>DATA</Th>
                <Th>UI MEANING</Th>
              </tr>
            </thead>
            <tbody>
              {eventRows.map(([type, emitter, data, render]) => (
                <EventRow key={type} type={type} emitter={emitter} data={data} render={render} />
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <SectionTitle eyebrow="WHERE TO LOOK NEXT" title="这张静态图和真实系统怎么对应" />
      <div className="grid gap-4 md:grid-cols-3">
        <DeepLink href="/company-agent" label="Company Agent" hint="发起一次真实公司研究" icon={Sparkles} />
        <DeepLink href="/runs" label="Runs" hint="看一次运行的事件回放" icon={Activity} />
        <DeepLink href="/evals" label="Evals" hint="看升级是否造成回归" icon={ClipboardCheck} />
      </div>
    </div>
  );
}

function IntroMetric({ label, value, hint }: { label: string; value: string; hint: string }) {
  return (
    <div className="border-l-2 border-[var(--line-strong)] pl-4">
      <div className="font-mono text-[9px] tracking-[0.18em] uppercase text-[var(--ink-faint)]">
        {label}
      </div>
      <div className="mt-1 font-display italic text-[30px] leading-none text-[var(--ink)]">
        {value}
      </div>
      <div className="mt-1 text-[11px] text-[var(--ink-muted)]">{hint}</div>
    </div>
  );
}

function RunStageCard({
  n,
  title,
  actor,
  body,
  event,
  accent,
}: {
  n: string;
  title: string;
  actor: string;
  body: string;
  event: string;
  accent?: boolean;
}) {
  return (
    <Card
      className={`min-w-0 p-5 ${
        accent ? "border-[var(--accent-line)] bg-[var(--accent-soft)]" : ""
      }`}
    >
      <div className="mb-3 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-mono text-[10px] tracking-[0.18em] text-[var(--ink-faint)]">{n}</div>
          <h3 className="mt-1 font-display italic text-[22px] text-[var(--ink)]">{title}</h3>
        </div>
        <Badge tone={accent ? "accent" : "neutral"} className="max-w-[150px] shrink-0 truncate">
          {actor}
        </Badge>
      </div>
      <p className="min-h-[58px] break-words text-[13px] leading-relaxed text-[var(--ink-soft)]">
        {body}
      </p>
      <div className="mt-4 flex items-center gap-2 border-t border-[var(--line)] pt-3 font-mono text-[10px] tracking-[0.06em] text-[var(--ink-muted)]">
        <Route size={14} className={accent ? "text-[var(--accent)]" : "text-[var(--ink-faint)]"} />
        {event}
      </div>
    </Card>
  );
}

function ContractCard({
  icon: Icon,
  title,
  body,
}: {
  icon: React.ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
  title: string;
  body: string;
}) {
  return (
    <Card className="p-5">
      <Icon size={18} strokeWidth={1.6} className="mb-3 text-[var(--accent)]" />
      <h3 className="font-display italic text-[19px] text-[var(--ink)]">{title}</h3>
      <p className="mt-2 text-[12px] leading-relaxed text-[var(--ink-muted)]">{body}</p>
    </Card>
  );
}

function AgentLayerRow({
  index,
  layer,
  title,
  body,
  accent,
}: {
  index: number;
  layer: string;
  title: string;
  body: string;
  accent?: boolean;
}) {
  return (
    <div
      className={`grid gap-4 border-b border-[var(--line)] px-5 py-4 last:border-0 md:grid-cols-[130px_220px_1fr] ${
        accent ? "bg-[var(--accent-soft)]" : ""
      }`}
    >
      <div className="flex items-center gap-3">
        <span className="font-mono text-[10px] tracking-[0.18em] text-[var(--ink-faint)]">
          {String(index + 1).padStart(2, "0")}
        </span>
        <span className={`font-mono text-[10px] tracking-[0.14em] uppercase ${accent ? "text-[var(--accent)]" : "text-[var(--ink-muted)]"}`}>
          {layer}
        </span>
      </div>
      <div className="font-display italic text-[18px] text-[var(--ink)]">{title}</div>
      <p className="text-[12px] leading-relaxed text-[var(--ink-soft)]">{body}</p>
    </div>
  );
}

function QualityItem({
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
      <div className="flex gap-3">
        <Icon size={18} strokeWidth={1.6} className="mt-0.5 shrink-0 text-[var(--accent)]" />
        <div>
          <h3 className="font-mono text-[11px] tracking-[0.08em] text-[var(--ink)]">{title}</h3>
          <p className="mt-1.5 text-[12px] leading-relaxed text-[var(--ink-muted)]">{body}</p>
        </div>
      </div>
    </Card>
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
  return (
    <tr className="border-b border-[var(--line)] text-[12px] last:border-0">
      <td className="px-5 py-2.5 font-mono text-[11px] text-[var(--accent)]">{type}</td>
      <td className="px-5 py-2.5 text-[11px] text-[var(--ink-muted)]">{emitter}</td>
      <td className="px-5 py-2.5 font-mono text-[10px] text-[var(--ink-soft)]">{data}</td>
      <td className="px-5 py-2.5 text-[11px] text-[var(--ink-soft)]">{render}</td>
    </tr>
  );
}

function DeepLink({
  href,
  label,
  hint,
  icon: Icon,
}: {
  href: string;
  label: string;
  hint: string;
  icon: React.ComponentType<{ size?: number; strokeWidth?: number; className?: string }>;
}) {
  return (
    <Link
      href={href}
      className="group flex items-center justify-between rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface-1)] px-5 py-4 transition-colors hover:border-[var(--accent-line)]"
    >
      <div className="flex min-w-0 items-center gap-3">
        <Icon size={17} strokeWidth={1.7} className="shrink-0 text-[var(--ink-muted)] group-hover:text-[var(--accent)]" />
        <div className="min-w-0">
          <div className="font-display italic text-[16px] text-[var(--ink)]">{label}</div>
          <div className="mt-0.5 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
            {hint}
          </div>
        </div>
      </div>
      <ArrowRight size={16} className="shrink-0 text-[var(--ink-faint)] transition-colors group-hover:text-[var(--accent)]" />
    </Link>
  );
}
