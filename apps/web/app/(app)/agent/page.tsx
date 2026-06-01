"use client";

import { useEffect, useRef, useState } from "react";
import { Trace } from "@/components/agent/Trace";
import { Message } from "@/components/agent/Message";
import { SkillSelector } from "@/components/agent/SkillSelector";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { listAgents, streamChat, type AgentInfo } from "@/lib/api";
import { canOperate, fetchMe, type AuthUser } from "@/lib/auth";
import type { AgentEvent, ChatMessage } from "@/lib/types";
import { Send, Square, FlaskConical } from "lucide-react";

interface UIMessage {
  role: "user" | "assistant";
  content: string;
}

const HINTS = [
  "分析宁德时代的近期表现",
  "对比比亚迪和理想的基本面",
  "复盘今日 A 股大盘",
  "解读最新央行货币政策",
];

export default function AgentPage() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [agent, setAgent] = useState("");
  const [model, setModel] = useState("");
  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<UIMessage[]>([]);
  const [streamingText, setStreamingText] = useState("");
  const [events, setEvents] = useState<AgentEvent[]>([]);
  const [isStreaming, setIsStreaming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [user, setUser] = useState<AuthUser | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const isAdmin = canOperate(user);

  useEffect(() => {
    listAgents()
      .then((r) => {
        setAgents(r.items);
        if (r.items.length > 0) {
          // Phase B: uteki is the main router — prefer it as the default
          // selection so the single-chat-input UX hits the dispatcher
          // first; fall back to the first registered skill if missing.
          setAgent(
            (prev) =>
              prev ||
              r.items.find((a) => a.name === "uteki")?.name ||
              r.items[0].name,
          );
        }
      })
      .catch(() => {});
  }, []);

  useEffect(() => {
    fetchMe().then(setUser).catch(() => setUser(null));
  }, []);

  async function handleSend() {
    if (!input.trim() || isStreaming || !isAdmin) return;
    const userMsg: UIMessage = { role: "user", content: input.trim() };
    const next = [...messages, userMsg];
    setMessages(next);
    setInput("");
    setStreamingText("");
    setEvents([]);
    setError(null);
    setIsStreaming(true);

    const controller = new AbortController();
    abortRef.current = controller;

    const apiMessages: ChatMessage[] = next.map((m) => ({
      role: m.role,
      content: m.content,
    }));

    try {
      let buffered = "";
      for await (const ev of streamChat(
        { messages: apiMessages, agent: agent || undefined, model: model || undefined },
        controller.signal,
      )) {
        setEvents((p) => [...p, ev]);
        if (ev.type === "delta") {
          buffered += String(ev.data.text ?? "");
          setStreamingText(buffered);
        } else if (ev.type === "done") {
          setMessages((p) => [...p, { role: "assistant", content: buffered }]);
          setStreamingText("");
          buffered = "";
        } else if (ev.type === "error") {
          setError(String(ev.data.reason ?? "error"));
        }
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError((e as Error).message);
    } finally {
      setIsStreaming(false);
      abortRef.current = null;
    }
  }

  return (
    <PageContainer>
      <PageHeader
        eyebrow="CATALOG · 试运行"
        title="Ad-hoc Run"
        subtitle="不挂调度，直接喂一段 prompt 触发一次 harness 执行。用来调试 skill、试 prompt、看 trace。每次都会落一条 run 到 /runs。"
        actions={
          <span className="inline-flex items-center gap-1.5 font-mono text-[10px] tracking-[0.14em] uppercase text-[var(--ink-faint)]">
            <FlaskConical size={12} /> dev playground
          </span>
        }
      />

      {/* Controls */}
      <div className="mb-6 flex flex-wrap items-center gap-3 rounded-[var(--r-lg)] border border-[var(--line)] bg-[var(--surface-1)] p-3">
        <label className="flex items-center gap-2">
          <span className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
            SKILL
          </span>
          <SkillSelector value={agent} onChange={setAgent} agents={agents} />
        </label>
        <label className="flex items-center gap-2">
          <span className="font-mono text-[9px] tracking-[0.18em] text-[var(--ink-faint)]">
            MODEL
          </span>
          <input
            type="text"
            value={model}
            onChange={(e) => setModel(e.target.value)}
            placeholder="default"
            className="w-56 rounded-md border border-[var(--line-strong)] bg-[var(--surface)] px-2.5 py-1.5 font-mono text-[11px] text-[var(--ink-soft)] placeholder:text-[var(--ink-faint)] focus:border-[var(--accent)] transition-colors"
          />
        </label>
        <div className="ml-auto flex items-center gap-2">
          {isStreaming && (
            <Button variant="outline" onClick={() => abortRef.current?.abort()}>
              <Square size={12} /> Abort
            </Button>
          )}
          <Button variant="primary" onClick={handleSend} disabled={!isAdmin || isStreaming || !input.trim()}>
            <Send size={12} /> {isStreaming ? "Streaming…" : "Run"}
          </Button>
        </div>
      </div>

      {/* Trace + chat */}
      <div className="grid gap-6 md:grid-cols-[1.2fr_1fr]">
        <Card className="min-h-[460px]">
          <CardHeader>
            <div className="eyebrow">TRACE</div>
          </CardHeader>
          <CardBody>
            {events.length === 0 ? (
              <div className="flex h-[380px] flex-col items-center justify-center text-center">
                <FlaskConical size={28} className="text-[var(--ink-faint)] mb-3" />
                <div className="font-display italic text-[18px] text-[var(--ink-soft)]">
                  等待触发
                </div>
                <p className="mt-1 font-mono text-[10px] tracking-[0.04em] text-[var(--ink-faint)]">
                  按 Run 后这里实时显示事件流
                </p>
              </div>
            ) : (
              <Trace events={events} />
            )}
          </CardBody>
        </Card>

        <Card className="flex min-h-[460px] flex-col">
          <CardHeader>
            <div className="eyebrow">CONVERSATION</div>
          </CardHeader>
          <CardBody className="flex flex-1 flex-col gap-3">
            <div className="flex-1 space-y-3 overflow-y-auto">
              {messages.length === 0 && !streamingText ? (
                <div className="flex h-full flex-col items-center justify-center text-center">
                  <div className="eyebrow mb-2">SUGGESTIONS</div>
                  <ul className="space-y-1.5">
                    {HINTS.map((h) => (
                      <li
                        key={h}
                        className="cursor-pointer font-display italic text-[14px] text-[var(--ink-soft)] hover:text-[var(--accent)] transition-colors"
                        onClick={() => setInput(h)}
                      >
                        {h}
                      </li>
                    ))}
                  </ul>
                </div>
              ) : (
                <>
                  {messages.map((m, i) => (
                    <Message key={i} role={m.role} content={m.content} />
                  ))}
                  {streamingText && <Message role="assistant" content={streamingText} />}
                </>
              )}
            </div>
            {error && (
              <div className="rounded-[var(--r)] border border-[color-mix(in_srgb,var(--loss)_40%,transparent)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)] p-2.5 text-[12px] text-[var(--loss)]">
                ⚠ {error}
              </div>
            )}
            {!isAdmin && (
              <div className="rounded-[var(--r)] border border-[var(--line)] bg-[var(--surface)] p-2.5 font-mono text-[11px] text-[var(--ink-muted)]">
                reader 模式：可以查看已有 run 结果和 trace；临时运行仅限 admin。
              </div>
            )}
          </CardBody>
        </Card>
      </div>

      {/* Input */}
      <Card className="mt-6">
        <CardBody>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            placeholder="Enter prompt…  ⏎ Enter to run  ⇧ Shift+Enter for newline"
            rows={3}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                if (isAdmin) handleSend();
              }
            }}
            readOnly={!isAdmin}
            className="w-full resize-none bg-transparent font-body text-[14px] leading-relaxed text-[var(--ink)] placeholder:text-[var(--ink-faint)] focus:outline-none"
          />
        </CardBody>
      </Card>
    </PageContainer>
  );
}
