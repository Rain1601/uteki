/**
 * Single source of truth for the API base URL. Split out from ``api.ts`` so
 * ``lib/auth.ts`` can import it without pulling in the entire API surface
 * (which would create a circular import — api.ts depends on authedFetch).
 */
export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
