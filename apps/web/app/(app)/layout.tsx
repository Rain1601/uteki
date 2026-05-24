"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { Shell } from "@/components/shell/Shell";
import { fetchMe, type AuthUser } from "@/lib/auth";

/**
 * App-chrome layout — wraps every authenticated page with the sidebar Shell.
 *
 * Auth gate is client-side here because:
 *   - we want to consult both the in-memory access token and the httpOnly
 *     refresh cookie (the API's ``fetchMe`` knows how to do both via
 *     ``authedFetch`` + transparent refresh), and that requires JS
 *   - on dev (``UTEKI_AUTH_REQUIRED=false``) the API silently substitutes
 *     ``demo@local``, so ``fetchMe`` returns a user even without a token;
 *     we just render through
 *
 * On failure we push to ``/login?next=<current>`` so the user lands back
 * where they were after auth.
 */
export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<AuthUser | null | undefined>(undefined);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      const me = await fetchMe();
      if (cancelled) return;
      if (!me) {
        const next = encodeURIComponent(pathname || "/");
        router.replace(`/login?next=${next}`);
        return;
      }
      setUser(me);
    })();
    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  if (user === undefined) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-[var(--bg)] text-[var(--ink-faint)] font-mono text-[11px] tracking-[0.18em] uppercase">
        loading…
      </div>
    );
  }
  if (user === null) {
    // Redirect already issued; render nothing to avoid a flash of content.
    return null;
  }

  return <Shell user={user}>{children}</Shell>;
}
