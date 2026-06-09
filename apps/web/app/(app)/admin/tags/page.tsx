"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  Check,
  Loader2,
  Plus,
  RefreshCw,
  Trash2,
  X,
} from "lucide-react";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { API_BASE } from "@/lib/api-base";
import { authedFetch, canAdmin, fetchMe, type AuthUser } from "@/lib/auth";

interface Tag {
  id: string;
  group_id: string;
  name: string;
  description: string;
  sort_order: number;
  color: string | null;
}

interface TagGroup {
  id: string;
  name: string;
  description: string;
  mode: "single" | "multi" | string;
  sort_order: number;
  created_at: string;
  tags: Tag[];
}

export default function AdminTagsPage() {
  const router = useRouter();
  const [me, setMe] = useState<AuthUser | null>(null);
  const [checkedAuth, setCheckedAuth] = useState(false);
  const [groups, setGroups] = useState<TagGroup[]>([]);
  const [loading, setLoading] = useState(false);
  const [creatingGroup, setCreatingGroup] = useState(false);
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
      const r = await authedFetch(`${API_BASE}/api/admin/tag-groups`, {
        cache: "no-store",
      });
      if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
      setGroups((await r.json()) as TagGroup[]);
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (canAdmin(me)) void refresh();
  }, [me, refresh]);

  async function createGroup(name: string, mode: "single" | "multi") {
    setError(null);
    try {
      const r = await authedFetch(`${API_BASE}/api/admin/tag-groups`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, mode, sort_order: groups.length }),
      });
      if (!r.ok) throw new Error(await r.text());
      setCreatingGroup(false);
      void refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "create failed");
    }
  }

  async function updateGroup(group: TagGroup, patch: Partial<TagGroup>) {
    setError(null);
    try {
      const r = await authedFetch(
        `${API_BASE}/api/admin/tag-groups/${group.id}`,
        {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch),
        },
      );
      if (!r.ok) throw new Error(await r.text());
      const updated = (await r.json()) as TagGroup;
      setGroups((prev) => prev.map((g) => (g.id === updated.id ? updated : g)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "update failed");
    }
  }

  async function deleteGroup(group: TagGroup) {
    if (
      !window.confirm(
        `删除标签组 "${group.name}"？组里所有 tag 以及挂在 article 上的 tag 链接都会一并删除。`,
      )
    )
      return;
    setError(null);
    try {
      const r = await authedFetch(
        `${API_BASE}/api/admin/tag-groups/${group.id}`,
        { method: "DELETE" },
      );
      if (!r.ok) throw new Error(await r.text());
      setGroups((prev) => prev.filter((g) => g.id !== group.id));
    } catch (e) {
      setError(e instanceof Error ? e.message : "delete failed");
    }
  }

  async function createTag(group: TagGroup, name: string, description: string) {
    setError(null);
    try {
      const r = await authedFetch(
        `${API_BASE}/api/admin/tag-groups/${group.id}/tags`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            name,
            description,
            sort_order: group.tags.length,
          }),
        },
      );
      if (!r.ok) throw new Error(await r.text());
      void refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "create tag failed");
    }
  }

  async function updateTag(tag: Tag, patch: Partial<Tag>) {
    setError(null);
    try {
      const r = await authedFetch(`${API_BASE}/api/admin/tags/${tag.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(patch),
      });
      if (!r.ok) throw new Error(await r.text());
      const updated = (await r.json()) as Tag;
      setGroups((prev) =>
        prev.map((g) =>
          g.id !== tag.group_id
            ? g
            : { ...g, tags: g.tags.map((t) => (t.id === updated.id ? updated : t)) },
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "update tag failed");
    }
  }

  async function deleteTag(tag: Tag) {
    if (!window.confirm(`删除 tag "${tag.name}"？`)) return;
    setError(null);
    try {
      const r = await authedFetch(`${API_BASE}/api/admin/tags/${tag.id}`, {
        method: "DELETE",
      });
      if (!r.ok) throw new Error(await r.text());
      setGroups((prev) =>
        prev.map((g) =>
          g.id !== tag.group_id
            ? g
            : { ...g, tags: g.tags.filter((t) => t.id !== tag.id) },
        ),
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "delete tag failed");
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
        eyebrow="ADMIN · TAG TAXONOMY"
        title="标签管理"
        subtitle="自定义标签组：每个组定义 single / multi 选择模式，组里的 tag 用来筛选新闻、运行结果以及其他 trigger 触发的内容。改完即时生效。"
        actions={
          <>
            <Badge tone="accent">{groups.length} groups</Badge>
            <Button variant="ghost" onClick={refresh} disabled={loading}>
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
              刷新
            </Button>
            <Button
              variant="primary"
              onClick={() => setCreatingGroup(true)}
              disabled={creatingGroup}
            >
              <Plus size={13} /> 新建标签组
            </Button>
          </>
        }
      />

      {error && (
        <div className="mb-4 border border-[color-mix(in_srgb,var(--loss)_40%,transparent)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)] px-4 py-3 font-mono text-[11px] text-[var(--loss)]">
          {error}
        </div>
      )}

      {creatingGroup && (
        <Card className="mb-5">
          <CardBody>
            <NewGroupForm
              onSubmit={createGroup}
              onCancel={() => setCreatingGroup(false)}
            />
          </CardBody>
        </Card>
      )}

      <div className="space-y-5">
        {groups.map((group) => (
          <Card key={group.id}>
            <CardHeader>
              <div className="flex flex-wrap items-start gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <InlineText
                      value={group.name}
                      onSave={(v) => updateGroup(group, { name: v })}
                      className="font-display text-[20px] italic text-[var(--ink)]"
                    />
                    <Badge tone={group.mode === "single" ? "accent" : "neutral"}>
                      {group.mode === "single" ? "单选" : "多选"}
                    </Badge>
                  </div>
                  <InlineText
                    value={group.description}
                    placeholder="（无描述，点击添加）"
                    onSave={(v) => updateGroup(group, { description: v })}
                    className="mt-1 text-[12px] text-[var(--ink-muted)]"
                  />
                </div>
                <div className="flex items-center gap-2">
                  <SelectMode
                    value={group.mode}
                    onChange={(v) => updateGroup(group, { mode: v })}
                  />
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => deleteGroup(group)}
                  >
                    <Trash2 size={12} />
                    删除组
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardBody>
              <div className="space-y-2">
                {group.tags.length === 0 && (
                  <div className="font-mono text-[10px] text-[var(--ink-faint)]">
                    这个组还没有任何标签。
                  </div>
                )}
                {group.tags.map((tag) => (
                  <TagRow
                    key={tag.id}
                    tag={tag}
                    onUpdate={(patch) => updateTag(tag, patch)}
                    onDelete={() => deleteTag(tag)}
                  />
                ))}
                <NewTagInput
                  onCreate={(name, description) => createTag(group, name, description)}
                />
              </div>
            </CardBody>
          </Card>
        ))}
        {groups.length === 0 && !loading && (
          <Card>
            <CardBody className="py-10 text-center text-[12px] text-[var(--ink-muted)]">
              还没有任何标签组。点右上"新建标签组"开始；或者运行 `uv run python services/api/scripts/seed_news_demo.py` 一键灌入默认 taxonomy。
            </CardBody>
          </Card>
        )}
      </div>
    </PageContainer>
  );
}

// ─── Inline edit primitives ─────────────────────────────────────────

function InlineText({
  value,
  onSave,
  placeholder,
  className,
}: {
  value: string;
  onSave: (v: string) => void;
  placeholder?: string;
  className?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);

  useEffect(() => setDraft(value), [value]);

  if (!editing) {
    return (
      <button
        type="button"
        onClick={() => setEditing(true)}
        className={`block w-full text-left transition-colors hover:bg-[var(--surface-hover)] ${className ?? ""}`}
      >
        {value || (
          <span className="italic text-[var(--ink-faint)]">{placeholder ?? "—"}</span>
        )}
      </button>
    );
  }
  return (
    <div className="flex items-center gap-1">
      <input
        autoFocus
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onBlur={() => {
          if (draft !== value) onSave(draft);
          setEditing(false);
        }}
        onKeyDown={(e) => {
          if (e.key === "Enter") {
            if (draft !== value) onSave(draft);
            setEditing(false);
          }
          if (e.key === "Escape") {
            setDraft(value);
            setEditing(false);
          }
        }}
        className={`block w-full bg-transparent outline-none ${className ?? ""}`}
      />
    </div>
  );
}

function SelectMode({
  value,
  onChange,
}: {
  value: string;
  onChange: (v: "single" | "multi") => void;
}) {
  return (
    <div className="flex rounded-md border border-[var(--line)] bg-[var(--surface)] p-[2px]">
      {(["single", "multi"] as const).map((opt) => (
        <button
          key={opt}
          type="button"
          onClick={() => onChange(opt)}
          className={`rounded-[3px] px-2.5 py-1 font-mono text-[10px] tracking-[0.06em] transition-colors ${
            value === opt
              ? "bg-[var(--surface-2)] text-[var(--ink)]"
              : "text-[var(--ink-muted)] hover:text-[var(--ink-soft)]"
          }`}
        >
          {opt === "single" ? "单选" : "多选"}
        </button>
      ))}
    </div>
  );
}

function TagRow({
  tag,
  onUpdate,
  onDelete,
}: {
  tag: Tag;
  onUpdate: (patch: Partial<Tag>) => void;
  onDelete: () => void;
}) {
  return (
    <div className="grid grid-cols-[140px_minmax(0,1fr)_100px_60px] items-center gap-3 border-b border-[var(--line)] py-2 last:border-b-0">
      <InlineText
        value={tag.name}
        onSave={(v) => onUpdate({ name: v })}
        className="font-mono text-[12px] tracking-[0.04em] text-[var(--ink)]"
      />
      <InlineText
        value={tag.description}
        placeholder="（添加描述）"
        onSave={(v) => onUpdate({ description: v })}
        className="text-[12px] text-[var(--ink-soft)]"
      />
      <InlineText
        value={tag.color ?? ""}
        placeholder="color"
        onSave={(v) => onUpdate({ color: v || null })}
        className="font-mono text-[11px] text-[var(--ink-muted)]"
      />
      <button
        type="button"
        onClick={onDelete}
        className="inline-flex h-7 w-7 items-center justify-center rounded border border-[var(--line)] text-[var(--ink-faint)] transition-colors hover:border-[color-mix(in_srgb,var(--loss)_40%,transparent)] hover:text-[var(--loss)]"
        aria-label={`删除 ${tag.name}`}
      >
        <Trash2 size={12} />
      </button>
    </div>
  );
}

function NewTagInput({
  onCreate,
}: {
  onCreate: (name: string, description: string) => void;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  function submit() {
    if (!name.trim()) return;
    onCreate(name.trim(), description.trim());
    setName("");
    setDescription("");
  }

  return (
    <div className="grid grid-cols-[140px_minmax(0,1fr)_100px_60px] items-center gap-3 pt-2">
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        placeholder="+ 新 tag name"
        className="bg-transparent font-mono text-[12px] tracking-[0.04em] text-[var(--ink)] outline-none placeholder:text-[var(--ink-faint)]"
      />
      <input
        value={description}
        onChange={(e) => setDescription(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
        placeholder="描述（可选）"
        className="bg-transparent text-[12px] text-[var(--ink-soft)] outline-none placeholder:text-[var(--ink-faint)]"
      />
      <span />
      <button
        type="button"
        onClick={submit}
        disabled={!name.trim()}
        className="inline-flex h-7 w-7 items-center justify-center rounded border border-[var(--line-strong)] text-[var(--ink-muted)] transition-colors hover:border-[var(--accent-line)] hover:text-[var(--accent)] disabled:opacity-30"
        aria-label="添加 tag"
      >
        <Plus size={12} />
      </button>
    </div>
  );
}

function NewGroupForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (name: string, mode: "single" | "multi") => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [mode, setMode] = useState<"single" | "multi">("multi");

  return (
    <div className="flex flex-wrap items-end gap-3">
      <label className="flex-1">
        <div className="mb-1 font-mono text-[9px] uppercase tracking-[0.18em] text-[var(--ink-faint)]">
          GROUP NAME
        </div>
        <input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="例如：重要度 / 类别 / 事件"
          className="h-10 w-full border border-[var(--line-strong)] bg-[var(--surface)] px-3 font-display text-[16px] italic text-[var(--ink)] outline-none focus:border-[var(--accent)]"
        />
      </label>
      <div>
        <div className="mb-1 font-mono text-[9px] uppercase tracking-[0.18em] text-[var(--ink-faint)]">
          MODE
        </div>
        <SelectMode value={mode} onChange={setMode} />
      </div>
      <div className="flex gap-2">
        <Button variant="ghost" onClick={onCancel}>
          <X size={12} />
          取消
        </Button>
        <Button
          variant="primary"
          onClick={() => name.trim() && onSubmit(name.trim(), mode)}
          disabled={!name.trim()}
        >
          <Check size={12} />
          创建
        </Button>
      </div>
    </div>
  );
}
