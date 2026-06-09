/**
 * Token storage + authed fetch wrapper.
 *
 * - Access token (15 min, HS256 JWT) is held in a module-level variable.
 *   That's deliberate: it dies with the tab, can't be read from JS in
 *   another origin, and is mirrored to sessionStorage purely so an
 *   in-tab navigation (Next.js client routing) keeps the user logged in.
 *   We never write it to localStorage — that'd survive cross-tab and
 *   linger longer than the token's actual TTL.
 *
 * - Refresh token is in an httpOnly cookie set by the API; JS never sees
 *   it. `authedFetch` always includes `credentials: "include"` so the
 *   cookie rides along on refresh + logout calls.
 *
 * - On 401 we transparently try one refresh + retry. If refresh also
 *   401s (token reuse, family burned, expired), we clear the in-memory
 *   token and surface the 401 to the caller — pages handle navigation.
 */

import { API_BASE } from "./api-base";

const STORAGE_KEY = "uteki.access_token";

let accessToken: string | null = null;
let hydrated = false;

function hydrateOnce(): void {
  if (hydrated) return;
  hydrated = true;
  if (typeof window === "undefined") return;
  try {
    const v = window.sessionStorage.getItem(STORAGE_KEY);
    if (v) accessToken = v;
  } catch {
    // sessionStorage can throw in private-browsing edge cases.
  }
}

export function setAccessToken(token: string | null): void {
  accessToken = token;
  if (typeof window === "undefined") return;
  try {
    if (token) window.sessionStorage.setItem(STORAGE_KEY, token);
    else window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // ignore
  }
}

export function getAccessToken(): string | null {
  hydrateOnce();
  return accessToken;
}

export function clearAccessToken(): void {
  setAccessToken(null);
}

let refreshInFlight: Promise<string | null> | null = null;

async function refreshAccessToken(): Promise<string | null> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async () => {
    try {
      const r = await fetch(`${API_BASE}/api/auth/refresh`, {
        method: "POST",
        credentials: "include",
      });
      if (!r.ok) return null;
      const body = (await r.json()) as { access_token?: string };
      const t = body.access_token ?? null;
      if (t) setAccessToken(t);
      return t;
    } catch {
      return null;
    } finally {
      refreshInFlight = null;
    }
  })();
  return refreshInFlight;
}

export async function authedFetch(
  input: RequestInfo | URL,
  init: RequestInit = {},
): Promise<Response> {
  hydrateOnce();
  const headers = new Headers(init.headers);
  if (accessToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${accessToken}`);
  }
  let resp = await fetch(input, {
    ...init,
    headers,
    credentials: "include",
  });
  if (resp.status !== 401) return resp;

  // Don't try to refresh on the refresh endpoint itself — that would
  // recurse forever when the refresh cookie is dead.
  const url = typeof input === "string" || input instanceof URL ? String(input) : input.url;
  if (url.endsWith("/api/auth/refresh")) return resp;

  const fresh = await refreshAccessToken();
  if (!fresh) {
    clearAccessToken();
    return resp;
  }
  headers.set("Authorization", `Bearer ${fresh}`);
  resp = await fetch(input, {
    ...init,
    headers,
    credentials: "include",
  });
  return resp;
}

// ─── Auth API helpers ───────────────────────────────────────────────────

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  avatar_url: string | null;
  created_at: string;
  status: string;
  role: "reader" | "admin" | string;
  permissions?: string[];
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: AuthUser;
}

export async function login(
  email: string,
  password: string,
): Promise<LoginResponse> {
  const r = await fetch(`${API_BASE}/api/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
    credentials: "include",
  });
  if (!r.ok) throw new Error((await r.text()) || `login failed: ${r.status}`);
  const body = (await r.json()) as LoginResponse;
  setAccessToken(body.access_token);
  return body;
}

export async function register(
  email: string,
  password: string,
  display_name?: string,
): Promise<LoginResponse> {
  const r = await fetch(`${API_BASE}/api/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password, display_name }),
    credentials: "include",
  });
  if (!r.ok) throw new Error((await r.text()) || `register failed: ${r.status}`);
  const body = (await r.json()) as LoginResponse;
  setAccessToken(body.access_token);
  return body;
}

export async function logout(): Promise<void> {
  try {
    await fetch(`${API_BASE}/api/auth/logout`, {
      method: "POST",
      credentials: "include",
    });
  } catch {
    // network errors shouldn't block local logout
  }
  clearAccessToken();
}

export async function fetchMe(): Promise<AuthUser | null> {
  const r = await authedFetch(`${API_BASE}/api/auth/me`);
  if (!r.ok) return null;
  return (await r.json()) as AuthUser;
}

export function canOperate(user: AuthUser | null | undefined, agent?: string): boolean {
  if (!user) return false;
  if (user.role === "admin" || user.permissions?.includes("agent:operate") === true) return true;
  if (agent === "company_research_pipeline") {
    return user.permissions?.includes("agent:company_research") === true;
  }
  return false;
}

/** True iff the user has admin tools (user management, system settings).
 *  Stricter than `canOperate` — dev demo with local_all_permissions still
 *  passes, but a vanilla reader does not. */
export function canAdmin(user: AuthUser | null | undefined): boolean {
  if (!user) return false;
  return user.role === "admin" || user.permissions?.includes("admin:*") === true;
}
