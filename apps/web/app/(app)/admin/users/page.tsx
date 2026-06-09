"use client";

import { useCallback, useEffect, useState } from "react";
import { Loader2, RefreshCw, ShieldCheck, ShieldOff } from "lucide-react";
import { PageContainer, PageHeader } from "@/components/ui/PageHeader";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { API_BASE } from "@/lib/api-base";
import { authedFetch, fetchMe, type AuthUser } from "@/lib/auth";

interface UserRow {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
  role: "admin" | "reader" | string;
  status: string;
  created_at: string;
  providers: string[];
}

interface UsersResponse {
  items: UserRow[];
  total: number;
  limit: number;
  offset: number;
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleString("zh-CN", {
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function AdminUsersPage() {
  // Auth + redirect handled by /admin layout — we just need `me` for
  // self-row disable logic.
  const [me, setMe] = useState<AuthUser | null>(null);
  const [rows, setRows] = useState<UserRow[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(false);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchMe().then(setMe);
  }, []);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await authedFetch(`${API_BASE}/api/admin/users?limit=200`, {
        cache: "no-store",
      });
      if (!r.ok) throw new Error((await r.text()) || `HTTP ${r.status}`);
      const body = (await r.json()) as UsersResponse;
      setRows(body.items);
      setTotal(body.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "load failed");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  async function toggleRole(row: UserRow) {
    const nextRole = row.role === "admin" ? "reader" : "admin";
    setPendingId(row.id);
    setError(null);
    try {
      const r = await authedFetch(`${API_BASE}/api/admin/users/${row.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ role: nextRole }),
      });
      if (!r.ok) {
        const text = await r.text();
        // Surface the API's specific 409 messages (last admin / self-demote).
        let detail = text;
        try {
          detail = (JSON.parse(text) as { detail?: string }).detail ?? text;
        } catch {
          // ignore
        }
        throw new Error(detail || `HTTP ${r.status}`);
      }
      const updated = (await r.json()) as UserRow;
      setRows((prev) => prev.map((u) => (u.id === updated.id ? updated : u)));
    } catch (e) {
      setError(e instanceof Error ? e.message : "update failed");
    } finally {
      setPendingId(null);
    }
  }

  return (
    <PageContainer>
      <PageHeader
        eyebrow="ADMIN · USER MANAGEMENT"
        title="用户管理"
        subtitle="查看所有注册账户、绑定的登录方式，以及在 admin / reader 之间切换权限。最后一名 admin 不能被降权。"
        actions={
          <>
            <Badge tone="accent">{total} users</Badge>
            <Button variant="ghost" onClick={refresh} disabled={loading}>
              <RefreshCw size={13} className={loading ? "animate-spin" : ""} />
              刷新
            </Button>
          </>
        }
      />

      {error && (
        <div className="mb-4 border border-[color-mix(in_srgb,var(--loss)_40%,transparent)] bg-[color-mix(in_srgb,var(--loss)_8%,transparent)] px-4 py-3 font-mono text-[11px] text-[var(--loss)]">
          {error}
        </div>
      )}

      <Card>
        <div className="overflow-x-auto">
          <table className="min-w-full text-left">
            <thead className="border-b border-[var(--line)] font-mono text-[9px] uppercase tracking-[0.18em] text-[var(--ink-faint)]">
              <tr>
                <th className="px-5 py-3">User</th>
                <th className="px-5 py-3">登录方式</th>
                <th className="px-5 py-3">注册于</th>
                <th className="px-5 py-3">Role</th>
                <th className="px-5 py-3 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--line)]">
              {rows.map((row) => {
                const isMe = me?.id === row.id;
                const isAdmin = row.role === "admin";
                const busy = pendingId === row.id;
                return (
                  <tr key={row.id} className="hover:bg-[var(--surface-hover)]">
                    <td className="px-5 py-3.5">
                      <div className="flex items-center gap-3">
                        <Avatar url={row.avatar_url} name={row.display_name || row.email} />
                        <div className="min-w-0">
                          <div className="font-display text-[15px] italic text-[var(--ink)]">
                            {row.display_name || row.email.split("@")[0]}
                            {isMe && (
                              <span className="ml-2 font-mono text-[9px] tracking-[0.12em] text-[var(--ink-faint)]">
                                · YOU
                              </span>
                            )}
                          </div>
                          <div className="font-mono text-[11px] text-[var(--ink-muted)]">
                            {row.email}
                          </div>
                        </div>
                      </div>
                    </td>
                    <td className="px-5 py-3.5">
                      <div className="flex flex-wrap gap-1.5">
                        {row.providers.length === 0 ? (
                          <span className="font-mono text-[10px] text-[var(--ink-faint)]">—</span>
                        ) : (
                          row.providers.map((p) => (
                            <Badge key={p} tone="neutral">
                              {p}
                            </Badge>
                          ))
                        )}
                      </div>
                    </td>
                    <td className="px-5 py-3.5 font-mono text-[11px] text-[var(--ink-muted)]">
                      {formatDate(row.created_at)}
                    </td>
                    <td className="px-5 py-3.5">
                      <Badge tone={isAdmin ? "gain" : "neutral"}>
                        {isAdmin ? "admin" : "reader"}
                      </Badge>
                    </td>
                    <td className="px-5 py-3.5 text-right">
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={() => toggleRole(row)}
                        disabled={busy || isMe}
                        title={isMe ? "不能修改自己的权限" : undefined}
                      >
                        {busy ? (
                          <Loader2 size={12} className="animate-spin" />
                        ) : isAdmin ? (
                          <ShieldOff size={12} />
                        ) : (
                          <ShieldCheck size={12} />
                        )}
                        {isAdmin ? "降为 reader" : "升为 admin"}
                      </Button>
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 && !loading && (
                <tr>
                  <td colSpan={5} className="px-5 py-12 text-center text-[12px] text-[var(--ink-muted)]">
                    还没有真实账户。让用户在 /login 注册或用 Google / GitHub 登录后会出现在这里。
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <p className="mt-6 text-[11px] leading-relaxed text-[var(--ink-faint)]">
        admin 拥有所有操作权限（运行 agent / hot-reload skill / 触发 evolution）；reader 只能查看历史 run 和 artifact。
        改 role 立即生效，下次该用户刷新页面时按新权限渲染。
      </p>
    </PageContainer>
  );
}

function Avatar({ url, name }: { url: string | null; name: string }) {
  if (url) {
    // eslint-disable-next-line @next/next/no-img-element
    return (
      <img
        src={url}
        alt={name}
        className="h-8 w-8 rounded-full border border-[var(--line)] object-cover"
      />
    );
  }
  const initial = name.charAt(0).toUpperCase() || "?";
  return (
    <div className="flex h-8 w-8 items-center justify-center rounded-full border border-[var(--line-strong)] bg-[var(--surface-2)] font-display text-[14px] italic text-[var(--ink-muted)]">
      {initial}
    </div>
  );
}
