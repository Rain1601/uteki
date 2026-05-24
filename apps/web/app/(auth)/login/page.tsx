"use client";

import { useState, Suspense } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { API_BASE } from "@/lib/api-base";
import { login } from "@/lib/auth";

function LoginInner() {
  const router = useRouter();
  const search = useSearchParams();
  const next = search.get("next") || "/";

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setErr(null);
    try {
      await login(email, password);
      router.replace(next);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "登录失败");
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
      kicker="welcome back"
      title="Sign in"
      footer={
        <>
          没有账号？
          <Link
            className="ml-1 underline decoration-[var(--accent)] underline-offset-4 hover:text-[var(--ink)]"
            href={`/register?next=${encodeURIComponent(next)}`}
          >
            注册
          </Link>
        </>
      }
    >
      <form onSubmit={onSubmit} className="space-y-4">
        <Field
          label="Email"
          type="email"
          value={email}
          onChange={setEmail}
          autoComplete="email"
          required
        />
        <Field
          label="Password"
          type="password"
          value={password}
          onChange={setPassword}
          autoComplete="current-password"
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
          {submitting ? "登录中…" : "Continue"}
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

export default function LoginPage() {
  return (
    <Suspense fallback={null}>
      <LoginInner />
    </Suspense>
  );
}

// ─── shared bits used by login + register ─────────────────────────────────

export function AuthCard({
  kicker,
  title,
  children,
  footer,
}: {
  kicker: string;
  title: string;
  children: React.ReactNode;
  footer?: React.ReactNode;
}) {
  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-[380px]">
        <Link href="/" className="mb-8 flex items-center gap-3">
          <div className="relative flex h-8 w-8 items-center justify-center">
            <div className="absolute inset-0 rounded-md bg-[var(--accent)] opacity-90" />
            <div className="relative font-display text-[17px] italic font-medium text-[#1a1410]">
              u
            </div>
          </div>
          <div>
            <div className="font-display italic text-[20px] leading-none text-[var(--ink)]">
              uteki
            </div>
            <div className="mt-0.5 font-mono text-[9px] tracking-[0.18em] uppercase text-[var(--ink-faint)]">
              research agent
            </div>
          </div>
        </Link>

        <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-[var(--ink-faint)]">
          {kicker}
        </div>
        <h1 className="mt-1 font-display italic text-[28px] tracking-tight text-[var(--ink)]">
          {title}
        </h1>

        <div className="mt-7">{children}</div>

        {footer && (
          <div className="mt-7 font-mono text-[11px] text-[var(--ink-muted)]">
            {footer}
          </div>
        )}
      </div>
    </div>
  );
}

export function Field({
  label,
  value,
  onChange,
  type = "text",
  autoComplete,
  required,
  minLength,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  type?: string;
  autoComplete?: string;
  required?: boolean;
  minLength?: number;
}) {
  return (
    <label className="block">
      <span className="font-mono text-[10px] tracking-[0.18em] uppercase text-[var(--ink-faint)]">
        {label}
      </span>
      <input
        type={type}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={autoComplete}
        required={required}
        minLength={minLength}
        className="mt-1 block w-full rounded-md border border-[var(--line)] bg-transparent px-3 py-2 font-mono text-[13px] text-[var(--ink)] outline-none transition-colors placeholder:text-[var(--ink-faint)] focus:border-[var(--accent)]"
      />
    </label>
  );
}

export function OAuthDivider() {
  return (
    <div className="my-5 flex items-center gap-3">
      <div className="h-px flex-1 bg-[var(--line)]" />
      <span className="font-mono text-[9px] tracking-[0.18em] uppercase text-[var(--ink-faint)]">
        or
      </span>
      <div className="h-px flex-1 bg-[var(--line)]" />
    </div>
  );
}

export function OAuthButton({ href, label }: { href: string; label: string }) {
  return (
    <a
      href={href}
      className="flex w-full items-center justify-center rounded-md border border-[var(--line)] py-2.5 font-mono text-[12px] tracking-[0.05em] text-[var(--ink-soft)] transition-colors hover:border-[var(--line-strong)] hover:bg-[var(--surface-hover)] hover:text-[var(--ink)]"
    >
      {label}
    </a>
  );
}
