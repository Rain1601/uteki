"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { setAccessToken, fetchMe } from "@/lib/auth";

/**
 * Receives the access token from the API OAuth callback.
 *
 * Flow:
 *   1. User clicks "Continue with GitHub" on /login
 *   2. Browser → API → GitHub → API callback
 *   3. API issues refresh httpOnly cookie + 302's to this page with
 *      `#access_token=...&next=/path` in the URL fragment
 *
 * The fragment never reaches the server (Next or origin), so the token
 * isn't logged in any access log. We:
 *   - parse it client-side
 *   - call setAccessToken (which mirrors to sessionStorage so the next
 *     page mount sees it)
 *   - replace the URL to strip the fragment before navigating onward
 */
export default function OAuthCallbackPage() {
  const router = useRouter();
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    const hash = window.location.hash.replace(/^#/, "");
    const params = new URLSearchParams(hash);
    const token = params.get("access_token");
    const next = params.get("next") || "/";
    const oauthErr = params.get("error");

    if (oauthErr) {
      setErr(oauthErr);
      return;
    }
    if (!token) {
      setErr("missing access_token");
      return;
    }

    setAccessToken(token);
    // Strip fragment from history so the token isn't visible in back-button.
    window.history.replaceState(null, "", window.location.pathname);

    // Verify the token actually works before navigating — surfaces clock
    // skew / wrong-secret problems immediately rather than as a redirect
    // loop later.
    fetchMe()
      .then((u) => {
        if (!u) {
          setErr("token rejected by /me");
          return;
        }
        router.replace(next);
      })
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)));
  }, [router]);

  return (
    <div className="flex min-h-screen items-center justify-center">
      <div className="text-center">
        <div className="font-mono text-[10px] tracking-[0.22em] uppercase text-[var(--ink-faint)]">
          oauth handshake
        </div>
        <div className="mt-2 font-display italic text-[18px] text-[var(--ink)]">
          {err ? (
            <span className="text-[var(--loss)]">登录失败：{err}</span>
          ) : (
            "Signing you in…"
          )}
        </div>
        {err && (
          <a
            href="/login"
            className="mt-4 inline-block font-mono text-[11px] text-[var(--ink-muted)] underline decoration-[var(--accent)] underline-offset-4 hover:text-[var(--ink)]"
          >
            回到登录
          </a>
        )}
      </div>
    </div>
  );
}
