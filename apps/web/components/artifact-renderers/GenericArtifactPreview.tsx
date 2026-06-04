"use client";

// GenericArtifactPreview — debug-grade artifact viewer for /runs/[id].
//
// This is intentionally lean. It does NOT know about specific artifacts like
// `final-verdict.json` or `decision.json` — that's the dossier's job (e.g.
// /company-agent/[id] for company_research_pipeline). Putting per-skill
// product views here just duplicates dossier work and dilutes both pages.
//
// What it renders:
//   • markdown (.md)                 → editorial RichMarkdown
//   • json (any name)                → collapsible JsonTree
//   • text / fallback                → width-constrained <pre>
//
// All containers are width-constrained (`overflow-hidden` on the outer card,
// `min-w-0` on flex/grid children, `break-all` on long tokens). Horizontal
// scrollbars only appear on inner code/JSON blocks, never on the page.

import { useEffect, useMemo, useState } from "react";
import { ChevronDown, ChevronRight, ExternalLink, FileText } from "lucide-react";
import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { cn } from "@/lib/cn";
import type { ArtifactRef } from "@/lib/api";
import { artifactUrl, fetchArtifactText } from "@/lib/api";

function safeParseJson<T>(text: string): T | null {
  try {
    return JSON.parse(text) as T;
  } catch {
    return null;
  }
}

export function GenericArtifactPreview({
  runId,
  artifact,
  fallbackText,
}: {
  runId: string;
  artifact: ArtifactRef;
  fallbackText: string;
}) {
  const [content, setContent] = useState<string>(fallbackText);
  const [loaded, setLoaded] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (artifact.kind === "binary") {
      setLoaded(true);
      return;
    }
    let cancelled = false;
    fetchArtifactText(runId, artifact.name)
      .then((text) => {
        if (cancelled) return;
        setContent(text);
        setLoaded(true);
      })
      .catch((e: Error) => {
        if (cancelled) return;
        setError(e.message);
        setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [runId, artifact.name, artifact.kind]);

  const rawUrl = artifactUrl(runId, artifact.name);

  return (
    <Card className="mb-6 overflow-hidden">
      <CardHeader>
        <div className="flex flex-wrap items-center gap-2">
          <FileText size={15} className="text-[var(--accent)]" />
          <div className="eyebrow min-w-0 truncate">
            PRIMARY ARTIFACT · {artifact.display_name || artifact.name}
          </div>
          <span className="ml-auto inline-flex items-center gap-2">
            <Badge tone="accent">{artifact.kind}</Badge>
            <a
              href={rawUrl}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 font-mono text-[10px] tracking-[0.08em] uppercase text-[var(--ink-muted)] hover:text-[var(--accent)]"
            >
              raw <ExternalLink size={11} />
            </a>
          </span>
        </div>
        {artifact.description ? (
          <div className="mt-2 text-[12px] leading-relaxed text-[var(--ink-muted)]">
            {artifact.description}
          </div>
        ) : null}
      </CardHeader>
      <CardBody className="min-w-0">
        {error ? (
          <div className="font-mono text-[11px] text-[var(--loss)]">Error: {error}</div>
        ) : !loaded ? (
          <div className="font-mono text-[11px] text-[var(--ink-muted)]">loading…</div>
        ) : (
          <ArtifactBody artifact={artifact} content={content} />
        )}
      </CardBody>
    </Card>
  );
}

function ArtifactBody({ artifact, content }: { artifact: ArtifactRef; content: string }) {
  if (artifact.kind === "markdown" || artifact.name.endsWith(".md")) {
    return <RichMarkdown text={content || "No content"} />;
  }

  if (artifact.kind === "json" || artifact.name.endsWith(".json")) {
    const parsed = safeParseJson<unknown>(content);
    if (parsed == null) {
      return <PlainText text={content} />;
    }
    return (
      <div className="min-w-0">
        <JsonTree value={parsed} root depth={0} />
      </div>
    );
  }

  return <PlainText text={content} />;
}

// ─── Plain text ──────────────────────────────────────────────────────────

function PlainText({ text }: { text: string }) {
  return (
    <pre className="max-h-[560px] min-w-0 overflow-auto whitespace-pre-wrap break-all rounded-md bg-[var(--surface)] p-4 font-mono text-[12px] leading-relaxed text-[var(--ink-soft)]">
      {text || "No content"}
    </pre>
  );
}

// ─── JsonTree (collapsible) ──────────────────────────────────────────────

function JsonTree({
  value,
  k,
  depth,
  root = false,
}: {
  value: unknown;
  k?: string;
  depth: number;
  root?: boolean;
}) {
  if (value === null) return <PrimitiveValue k={k}>null</PrimitiveValue>;
  if (typeof value === "string") {
    return (
      <PrimitiveValue k={k}>
        <span className="break-all text-[var(--gain)]">&quot;{value}&quot;</span>
      </PrimitiveValue>
    );
  }
  if (typeof value === "number" || typeof value === "boolean") {
    return (
      <PrimitiveValue k={k}>
        <span className="numeric text-[var(--accent)]">{String(value)}</span>
      </PrimitiveValue>
    );
  }
  if (Array.isArray(value)) {
    return <CollapsibleNode k={k} value={value} depth={depth} kind="array" root={root} />;
  }
  if (typeof value === "object") {
    return (
      <CollapsibleNode
        k={k}
        value={value as Record<string, unknown>}
        depth={depth}
        kind="object"
        root={root}
      />
    );
  }
  return <PrimitiveValue k={k}>{String(value)}</PrimitiveValue>;
}

function PrimitiveValue({ k, children }: { k?: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[minmax(0,auto)_minmax(0,1fr)] items-baseline gap-2 font-mono text-[12px] leading-6">
      {k != null ? (
        <span className="break-all text-[var(--ink-muted)]">{k}:</span>
      ) : (
        <span />
      )}
      <span className="min-w-0">{children}</span>
    </div>
  );
}

function CollapsibleNode({
  k,
  value,
  depth,
  kind,
  root,
}: {
  k?: string;
  value: Record<string, unknown> | unknown[];
  depth: number;
  kind: "object" | "array";
  root?: boolean;
}) {
  // Expand only the first level by default; everything deeper requires a click.
  // Debug view should default to compact, not exhaustive.
  const [open, setOpen] = useState<boolean>(root || depth < 1);
  const entries: Array<[string, unknown]> = Array.isArray(value)
    ? value.map((v, i) => [String(i), v] as [string, unknown])
    : Object.entries(value);
  const summary = kind === "array" ? `[ ${entries.length} ]` : `{ ${entries.length} }`;

  return (
    <div className="min-w-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="group inline-flex items-baseline gap-1.5 text-left font-mono text-[12px] leading-6"
      >
        <span className="inline-flex w-3 shrink-0 items-center justify-center text-[var(--ink-faint)] group-hover:text-[var(--ink-muted)]">
          {open ? <ChevronDown size={11} /> : <ChevronRight size={11} />}
        </span>
        {k != null ? (
          <span className="break-all text-[var(--ink-muted)]">{k}:</span>
        ) : null}
        <span className="text-[var(--ink-faint)]">{summary}</span>
      </button>
      {open ? (
        <div
          className={cn(
            "ml-2 mt-0.5 space-y-0.5 border-l border-[var(--line)] pl-3",
            depth === 0 && "ml-1",
          )}
        >
          {entries.length === 0 ? (
            <div className="font-mono text-[11px] text-[var(--ink-faint)]">empty</div>
          ) : (
            entries.map(([key, child]) => (
              <JsonTree key={key} k={key} value={child} depth={depth + 1} />
            ))
          )}
        </div>
      ) : null}
    </div>
  );
}

// ─── Markdown ────────────────────────────────────────────────────────────

function RichMarkdown({ text }: { text: string }) {
  const blocks = useMemo(() => parseMarkdownBlocks(text), [text]);
  return (
    <div className="min-w-0 max-w-[72ch]">
      {blocks.map((block, i) => renderBlock(block, i))}
    </div>
  );
}

type Block =
  | { type: "h1" | "h2" | "h3"; text: string }
  | { type: "ul" | "ol"; items: string[] }
  | { type: "code"; text: string }
  | { type: "quote"; text: string }
  | { type: "hr" }
  | { type: "p"; text: string };

function renderBlock(block: Block, i: number): React.ReactNode {
  switch (block.type) {
    case "h1":
      return (
        <h2
          key={i}
          className="mb-4 mt-2 font-display text-[28px] italic leading-tight text-[var(--ink)] first:mt-0"
        >
          {block.text}
        </h2>
      );
    case "h2":
      return (
        <h3
          key={i}
          className="mb-3 mt-7 border-b border-[var(--line)] pb-1.5 font-display text-[20px] italic leading-tight text-[var(--ink)] first:mt-0"
        >
          {block.text}
        </h3>
      );
    case "h3":
      return (
        <h4
          key={i}
          className="mb-2 mt-5 font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--ink-muted)]"
        >
          {block.text}
        </h4>
      );
    case "ul":
      return (
        <ul key={i} className="mb-4 space-y-1.5 border-l border-[var(--line)] pl-4">
          {block.items.map((item, j) => (
            <li key={j} className="break-words text-[14px] leading-7 text-[var(--ink-soft)]">
              <InlineMd text={item} />
            </li>
          ))}
        </ul>
      );
    case "ol":
      return (
        <ol key={i} className="mb-4 ml-5 list-decimal space-y-1.5">
          {block.items.map((item, j) => (
            <li key={j} className="break-words text-[14px] leading-7 text-[var(--ink-soft)]">
              <InlineMd text={item} />
            </li>
          ))}
        </ol>
      );
    case "code":
      return (
        <pre
          key={i}
          className="mb-4 max-h-[360px] overflow-auto rounded-md bg-[var(--surface)] p-3 font-mono text-[11px] leading-relaxed text-[var(--ink-soft)]"
        >
          <code className="whitespace-pre-wrap break-all">{block.text}</code>
        </pre>
      );
    case "quote":
      return (
        <blockquote
          key={i}
          className="mb-4 border-l-[3px] border-[var(--accent)] bg-[var(--surface)] px-4 py-2 text-[14px] italic leading-7 text-[var(--ink-soft)]"
        >
          <InlineMd text={block.text} />
        </blockquote>
      );
    case "hr":
      return <hr key={i} className="my-6 border-[var(--line)]" />;
    case "p":
    default:
      return (
        <p
          key={i}
          className="mb-4 break-words text-[14px] leading-7 text-[var(--ink-soft)] last:mb-0"
        >
          <InlineMd text={(block as { text: string }).text} />
        </p>
      );
  }
}

function parseMarkdownBlocks(text: string): Block[] {
  const lines = text.split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();

    if (trimmed.startsWith("```")) {
      const buf: string[] = [];
      i += 1;
      while (i < lines.length && !lines[i].trim().startsWith("```")) {
        buf.push(lines[i]);
        i += 1;
      }
      i += 1;
      blocks.push({ type: "code", text: buf.join("\n") });
      continue;
    }

    if (!trimmed) {
      i += 1;
      continue;
    }

    if (/^(---|___|\*\*\*)$/.test(trimmed)) {
      blocks.push({ type: "hr" });
      i += 1;
      continue;
    }

    const h1 = trimmed.match(/^#\s+(.+)$/);
    if (h1) {
      blocks.push({ type: "h1", text: h1[1] });
      i += 1;
      continue;
    }
    const h2 = trimmed.match(/^##\s+(.+)$/);
    if (h2) {
      blocks.push({ type: "h2", text: h2[1] });
      i += 1;
      continue;
    }
    const h3 = trimmed.match(/^#{3,6}\s+(.+)$/);
    if (h3) {
      blocks.push({ type: "h3", text: h3[1] });
      i += 1;
      continue;
    }

    if (trimmed.startsWith(">")) {
      const buf: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        buf.push(lines[i].trim().replace(/^>\s?/, ""));
        i += 1;
      }
      blocks.push({ type: "quote", text: buf.join(" ") });
      continue;
    }

    if (/^[-*+]\s+/.test(trimmed)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*+]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*+]\s+/, ""));
        i += 1;
      }
      blocks.push({ type: "ul", items });
      continue;
    }

    if (/^\d+\.\s+/.test(trimmed)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ""));
        i += 1;
      }
      blocks.push({ type: "ol", items });
      continue;
    }

    const buf: string[] = [trimmed];
    i += 1;
    while (i < lines.length) {
      const next = lines[i];
      const nextTrim = next.trim();
      if (!nextTrim) break;
      if (
        nextTrim.startsWith("#") ||
        nextTrim.startsWith(">") ||
        nextTrim.startsWith("```") ||
        /^[-*+]\s+/.test(nextTrim) ||
        /^\d+\.\s+/.test(nextTrim) ||
        /^(---|___|\*\*\*)$/.test(nextTrim)
      ) {
        break;
      }
      buf.push(nextTrim);
      i += 1;
    }
    blocks.push({ type: "p", text: buf.join(" ") });
  }

  return blocks;
}

function InlineMd({ text }: { text: string }) {
  const nodes: React.ReactNode[] = [];
  let cursor = 0;
  let key = 0;
  const re =
    /(`[^`\n]+`)|(\*\*[^*\n]+\*\*)|(\*[^*\n]+\*)|(_[^_\n]+_)|(\[([^\]\n]+)\]\((https?:\/\/[^\s)]+)\))|(\[(?:src:)?(\d{1,3}(?:,\s*\d{1,3})*)\])/g;

  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    if (match.index > cursor) {
      nodes.push(<span key={`t-${key++}`}>{text.slice(cursor, match.index)}</span>);
    }
    const [whole, code, bold, italStar, italUnder, _link, label, href, _cite, citeIds] = match;
    if (code) {
      nodes.push(
        <code
          key={`c-${key++}`}
          className="break-all rounded-sm bg-[var(--surface)] px-1 py-[1px] font-mono text-[12px] text-[var(--ink)]"
        >
          {code.slice(1, -1)}
        </code>,
      );
    } else if (bold) {
      nodes.push(
        <strong key={`b-${key++}`} className="font-semibold text-[var(--ink)]">
          {bold.slice(2, -2)}
        </strong>,
      );
    } else if (italStar || italUnder) {
      const raw = (italStar || italUnder)!;
      nodes.push(
        <em key={`i-${key++}`} className="italic text-[var(--ink)]">
          {raw.slice(1, -1)}
        </em>,
      );
    } else if (label && href) {
      nodes.push(
        <a
          key={`l-${key++}`}
          href={href}
          target="_blank"
          rel="noreferrer"
          className="break-all text-[var(--accent)] underline-offset-2 hover:underline"
        >
          {label}
        </a>,
      );
    } else if (citeIds) {
      nodes.push(
        <sup
          key={`s-${key++}`}
          className="ml-0.5 font-mono text-[9px] text-[var(--accent)]"
          title={`src ${citeIds}`}
        >
          [{citeIds}]
        </sup>,
      );
    } else {
      nodes.push(<span key={`x-${key++}`}>{whole}</span>);
    }
    cursor = match.index + match[0].length;
  }
  if (cursor < text.length) {
    nodes.push(<span key={`t-${key++}`}>{text.slice(cursor)}</span>);
  }
  return <>{nodes}</>;
}
