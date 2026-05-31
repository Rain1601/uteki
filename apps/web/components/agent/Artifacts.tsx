"use client";

import { useEffect, useState } from "react";
import { FileText, Code2, FileType, FileDown, X, ExternalLink } from "lucide-react";
import {
  type ArtifactRef,
  type ArtifactKind,
  artifactUrl,
  fetchArtifactText,
} from "@/lib/api";
import { cn } from "@/lib/cn";

/**
 * Artifacts — list + side-drawer viewer.
 *
 * Items come from the AgentEvent stream's `artifact_written` events (no
 * extra fetch). Click [view] to load + render content in a drawer:
 *   markdown  → <pre> whitespace-preserved (no markdown library yet)
 *   json      → prettified <pre>
 *   text      → <pre>
 *   binary    → download-only
 */
export function Artifacts({
  runId,
  items,
}: {
  runId: string;
  items: ArtifactRef[];
}) {
  const [active, setActive] = useState<ArtifactRef | null>(null);

  if (items.length === 0) return null;

  return (
    <>
      <ul className="divide-y divide-[var(--line)]">
        {items.map((a) => (
          <li
            key={a.name}
            className="flex items-center gap-3 py-2.5"
          >
            <KindIcon kind={a.kind} />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline gap-2">
                <span className="font-mono text-[12px] text-[var(--ink)]">
                  {a.display_name || a.name}
                </span>
                <span className="font-mono text-[10px] text-[var(--ink-faint)]">
                  · {a.role || "artifact"} · {a.written_by} · {formatBytes(a.size_bytes)}
                </span>
              </div>
              {a.display_name && a.display_name !== a.name ? (
                <div className="mt-0.5 font-mono text-[10px] text-[var(--ink-faint)]">
                  {a.name}
                </div>
              ) : null}
              {a.description ? (
                <div className="mt-0.5 text-[11px] text-[var(--ink-muted)]">
                  {a.description}
                </div>
              ) : null}
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                onClick={() => setActive(a)}
                className="rounded-md px-2 py-1 text-[11px] font-mono uppercase tracking-[0.08em] text-[var(--ink-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--ink)]"
              >
                View
              </button>
              <a
                href={artifactUrl(runId, a.name)}
                target="_blank"
                rel="noopener noreferrer"
                className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[11px] font-mono uppercase tracking-[0.08em] text-[var(--ink-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--ink)]"
              >
                <FileDown size={12} /> Download
              </a>
            </div>
          </li>
        ))}
      </ul>
      {active ? (
        <ViewerDrawer
          runId={runId}
          artifact={active}
          onClose={() => setActive(null)}
        />
      ) : null}
    </>
  );
}

function KindIcon({ kind }: { kind: ArtifactKind }) {
  const I =
    kind === "markdown"
      ? FileText
      : kind === "json"
        ? Code2
        : kind === "text"
          ? FileType
          : FileDown;
  return <I size={16} className="text-[var(--ink-muted)] shrink-0" />;
}

function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

function ViewerDrawer({
  runId,
  artifact,
  onClose,
}: {
  runId: string;
  artifact: ArtifactRef;
  onClose: () => void;
}) {
  const [content, setContent] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    if (artifact.kind === "binary") {
      setContent(null);
      return;
    }
    setLoading(true);
    setErr(null);
    fetchArtifactText(runId, artifact.name)
      .then((t) => {
        if (artifact.kind === "json") {
          try {
            setContent(JSON.stringify(JSON.parse(t), null, 2));
          } catch {
            setContent(t);
          }
        } else {
          setContent(t);
        }
      })
      .catch((e: Error) => setErr(e.message))
      .finally(() => setLoading(false));
  }, [runId, artifact.name, artifact.kind]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      className="fixed inset-0 z-50 flex"
      onClick={onClose}
    >
      <div className="flex-1 bg-black/40" />
      <div
        className={cn(
          "h-full w-full max-w-3xl bg-[var(--surface)] border-l border-[var(--line)]",
          "flex flex-col shadow-2xl",
        )}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between gap-3 border-b border-[var(--line)] px-5 py-3">
          <div className="min-w-0">
            <div className="font-mono text-[13px] text-[var(--ink)] truncate">
              {artifact.name}
            </div>
            <div className="font-mono text-[10px] text-[var(--ink-faint)]">
              {artifact.kind} · {artifact.written_by} ·{" "}
              {formatBytes(artifact.size_bytes)}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <a
              href={artifactUrl(runId, artifact.name)}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 font-mono text-[10px] uppercase tracking-[0.08em] text-[var(--ink-muted)] hover:text-[var(--ink)]"
            >
              <ExternalLink size={12} /> Raw
            </a>
            <button
              type="button"
              onClick={onClose}
              className="rounded-md p-1.5 text-[var(--ink-muted)] hover:bg-[var(--surface-hover)] hover:text-[var(--ink)]"
              aria-label="Close"
            >
              <X size={16} />
            </button>
          </div>
        </div>
        <div className="flex-1 overflow-auto">
          {loading ? (
            <div className="p-5 font-mono text-[11px] text-[var(--ink-muted)]">
              Loading…
            </div>
          ) : err ? (
            <div className="p-5 font-mono text-[11px] text-[color-mix(in_srgb,var(--loss)_80%,white)]">
              Error: {err}
            </div>
          ) : artifact.kind === "binary" ? (
            <div className="p-5 text-[12px] text-[var(--ink-muted)]">
              Binary file — use Download.
            </div>
          ) : (
            <pre className="m-0 whitespace-pre-wrap break-words px-5 py-4 font-mono text-[12px] leading-relaxed text-[var(--ink-soft)]">
              {content ?? ""}
            </pre>
          )}
        </div>
      </div>
    </div>
  );
}
