"use client";

import { useState, Suspense } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { API_BASE } from "@/lib/api-base";
import { register } from "@/lib/auth";
import { AuthCard, Field, OAuthDivider, OAuthButton } from "../login/page";

function RegisterInner() {
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") || "/";

  const [email, setEmail] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setErr(null);
    try {
      await register(email, password, displayName || undefined);
      router.replace(next);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "注册失败");
    } finally {
      setSubmitting(false);
    }
  }

  function oauthHref(provider: "github" | "google"): string {
    const q = new URLSearchParams({ next }).toString();
    return `${API_BASE}/api/auth/oauth/${provider}/start?${q}`;
  }

  return (
    <AuthCard
      kicker="get started"
      title="Create account"
      footer={
        <>
          已经有账号？
          <Link
            className="ml-1 underline decoration-[var(--accent)] underline-offset-4 hover:text-[var(--ink)]"
            href={`/login?next=${encodeURIComponent(next)}`}
          >
            登录
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <Field
          label="Display name (optional)"
          value={displayName}
          onChange={setDisplayName}
          autoComplete="name"
        />
        <Field
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
          required
        />
        <Field
          label="Password (≥ 8)"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="new-password"
          required
          minLength={8}
        />
        {err && (
          <div className="font-mono text-[11px] text-[var(--loss)]">
            {err}
          </div>
        )}
        <button
          type="submit"
          disabled={submitting}
          className="block w-full rounded-md bg-[var(--ink)] py-2.5 font-display italic text-[15px] text-[var(--bg)] transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {submitting ? "注册中…" : "Create account"}
        </button>
      </form>

      <OAuthDivider />

      <div className="space-y-2">
        <OAuthButton href={oauthHref("github")} label="Continue with GitHub" />
        <OAuthButton href={oauthHref("google")} label="Continue with Google" />
      </div>
    </AuthCard>
  );
}

export default function RegisterPage() {
  return (
    <Suspense fallback={null}>
      <RegisterInner />
    </Suspense>
  );
}
