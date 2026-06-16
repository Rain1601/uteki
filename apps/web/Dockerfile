# syntax=docker/dockerfile:1.7
#
# Production Dockerfile for apps/web (Next.js 16, pnpm workspace).
# Build context MUST be the monorepo root, not apps/web/. The Cloud Build
# step uses: docker build -f apps/web/Dockerfile -t ... .
#
# Three stages:
#   1. deps    — install pnpm workspace deps (cached when lockfile is stable)
#   2. build   — next build → emits apps/web/.next/standalone
#   3. runtime — minimal node image with the standalone bundle only
#
# Node 24 LTS matches the current Vercel default Node major. Cloud Run
# expects the container to bind to $PORT (defaults to 8080 here).

# ─── Stage 1: install pnpm deps for the @uteki/web filter ───────────────────
FROM node:24-alpine AS deps
RUN corepack enable pnpm
WORKDIR /repo

# Copy only the manifests + lockfile so this layer caches across source edits.
# The workspace topology must be complete (root package.json + workspace yaml +
# every workspace member's package.json) for pnpm to resolve `workspace:*` deps.
COPY pnpm-lock.yaml package.json pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/
COPY packages/shared-types/package.json ./packages/shared-types/
COPY packages/ui/package.json ./packages/ui/

# `...` (ellipsis) tells pnpm to also install transitive workspace deps.
RUN pnpm install --frozen-lockfile --filter @uteki/web...

# ─── Stage 2: next build ────────────────────────────────────────────────────
FROM node:24-alpine AS build
RUN corepack enable pnpm
WORKDIR /repo

# Bring in the resolved node_modules from the deps stage. We copy the whole
# workspace's node_modules (root + per-package) so symlinked workspace deps
# resolve correctly during `next build`.
COPY --from=deps /repo/node_modules ./node_modules
COPY --from=deps /repo/apps/web/node_modules ./apps/web/node_modules
COPY --from=deps /repo/packages/shared-types/node_modules ./packages/shared-types/node_modules
# packages/ui has no current runtime deps but copy the marker dir if pnpm made one
COPY . .

# Next.js bakes NEXT_PUBLIC_* into the client bundle at build time.
# Pass --build-arg NEXT_PUBLIC_API_BASE=https://<api-cloud-run-url> from
# cloudbuild.yaml. Without it the bundle falls back to localhost:8000.
ARG NEXT_PUBLIC_API_BASE
ENV NEXT_PUBLIC_API_BASE=${NEXT_PUBLIC_API_BASE}
ENV NEXT_TELEMETRY_DISABLED=1
RUN pnpm --filter @uteki/web build

# ─── Stage 3: runtime ───────────────────────────────────────────────────────
FROM node:24-alpine AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    PORT=8080 \
    HOSTNAME=0.0.0.0 \
    NEXT_TELEMETRY_DISABLED=1

# Standalone output is rooted at the monorepo root (because we set
# experimental.outputFileTracingRoot in next.config.ts). Layout inside
# .next/standalone after build:
#   .next/standalone/
#     ├── node_modules/          (only what's actually used)
#     ├── apps/web/server.js     (the entry the docs say to run)
#     ├── apps/web/.next/        (server chunks)
#     ├── packages/shared-types/ (hoisted workspace deps)
#     └── package.json
#
# Next does NOT copy .next/static or public into standalone — we do it.
COPY --from=build /repo/apps/web/.next/standalone ./
COPY --from=build /repo/apps/web/.next/static ./apps/web/.next/static
COPY --from=build /repo/apps/web/public ./apps/web/public

EXPOSE 8080
CMD ["node", "apps/web/server.js"]
