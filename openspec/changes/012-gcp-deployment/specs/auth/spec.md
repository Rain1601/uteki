## MODIFIED Requirements

### Requirement: OAuth callback URL base is env-driven

The OAuth callback URL **base** SHALL be configurable per environment via `UTEKI_OAUTH_CALLBACK_BASE`. The full callback URL each provider sees SHALL be:

```
{UTEKI_OAUTH_CALLBACK_BASE}/api/auth/oauth/{github|google}/callback
```

`UTEKI_OAUTH_CALLBACK_BASE` SHALL default to the value of the existing `UTEKI_OAUTH_REDIRECT_BASE` setting for backward compatibility. When both are set, `UTEKI_OAUTH_CALLBACK_BASE` SHALL take precedence (it is the more specific name). Existing `oauth_redirect_base` continues to drive any other "where to send the browser after exchange" decisions.

#### Scenario: Dev env uses localhost callback

- **GIVEN** `UTEKI_OAUTH_CALLBACK_BASE` is unset and `UTEKI_OAUTH_REDIRECT_BASE` is unset
- **WHEN** the api process boots
- **THEN** `oauth_callback_base` SHALL be `http://localhost:8000`
- **AND** GitHub callback URL SHALL be `http://localhost:8000/api/auth/oauth/github/callback`

#### Scenario: Prod env uses public domain callback

- **GIVEN** `UTEKI_OAUTH_CALLBACK_BASE=https://your.domain.com` is set on Cloud Run
- **WHEN** the api process boots
- **THEN** GitHub callback URL SHALL be `https://your.domain.com/api/auth/oauth/github/callback`
- **AND** Google callback URL SHALL be `https://your.domain.com/api/auth/oauth/google/callback`

#### Scenario: Both env vars set — callback wins

- **GIVEN** `UTEKI_OAUTH_CALLBACK_BASE=https://your.domain.com` and `UTEKI_OAUTH_REDIRECT_BASE=https://other.domain.com` both set
- **WHEN** the api process boots
- **THEN** OAuth callback URLs SHALL use `https://your.domain.com`
- **AND** non-callback redirect (e.g. post-token-issue frontend hop) MAY use `https://other.domain.com` if the code path consults `oauth_redirect_base` for that purpose

#### Scenario: Provider must accept multiple callback URLs

- **GIVEN** owner runs dev (`http://localhost:8000`) and prod (`https://your.domain.com`) concurrently
- **WHEN** OAuth App settings at GitHub / Google are configured
- **THEN** both providers SHALL accept multiple authorized callback URLs simultaneously
- **AND** owner SHALL register both `http://localhost:8000/api/auth/oauth/<p>/callback` and `https://your.domain.com/api/auth/oauth/<p>/callback`
- **AND** the api process for each environment SHALL pick its own via env

## ADDED Requirements

### Requirement: JWT secret + OAuth client secrets sourced from Secret Manager in prod

In production (Cloud Run), the following SHALL NOT come from a `.env` file or container image:

- `UTEKI_JWT_SECRET`
- `GITHUB_CLIENT_SECRET`
- `GOOGLE_CLIENT_SECRET`
- `ANTHROPIC_API_KEY`
- `OPENAI_API_KEY`
- `DEEPSEEK_API_KEY` (optional)
- `AIHUBMIX_API_KEY` (optional)
- `UTEKI_DB_URL` (contains Postgres password)

They SHALL be injected into the container at startup via `gcloud run deploy --set-secrets=<ENV>=<secret>:latest`. The container SHALL read them as plain environment variables — no application-level code change versus dev.

#### Scenario: Secret rotation requires new revision

- **GIVEN** owner adds a new version to `uteki-jwt-secret` in Secret Manager
- **WHEN** owner runs `gcloud run services update uteki-api --update-secrets=UTEKI_JWT_SECRET=uteki-jwt-secret:latest`
- **THEN** a new Cloud Run revision SHALL spawn
- **AND** the new revision's containers SHALL read the new secret value at startup
- **AND** old revisions SHALL keep the old value (until traffic drains and they scale to zero)

#### Scenario: Cloud Run env does NOT auto-refresh

- **GIVEN** a Cloud Run revision running with `UTEKI_JWT_SECRET=uteki-jwt-secret:latest`
- **WHEN** a new secret version is added without a `gcloud run services update`
- **THEN** the running revision SHALL CONTINUE to use the old secret value
- **AND** this is documented as a known limitation; rotation procedure SHALL always pair `versions add` with `services update`

#### Scenario: dev env unchanged

- **GIVEN** local dev (`make dev`)
- **WHEN** the api process boots
- **THEN** it SHALL read secrets from `services/api/.env` via existing `pydantic-settings` flow
- **AND** no Secret Manager integration SHALL be required for dev

### Requirement: Owner allowlist is plain env (not Secret Manager)

`OWNER_EMAILS` and `OWNER_GITHUB_LOGINS` SHALL be passed to Cloud Run as plain environment variables, not via Secret Manager.

#### Scenario: Allowlist values are not secrets

- **GIVEN** owner identity is `<owner email>` / `<owner github>`
- **THEN** these values are PII but not secrets — leaking them grants no capability
- **AND** they SHALL be set via `gcloud run services update --set-env-vars=OWNER_EMAILS=...,OWNER_GITHUB_LOGINS=...`
- **AND** they MAY change without secret rotation overhead

### Requirement: Same-origin cookie configuration in prod

The httpOnly refresh cookie issued by `/api/auth/oauth/{provider}/callback` and `/api/auth/refresh` SHALL be set with:

| Attribute | Dev | Prod |
|---|---|---|
| `Domain` | omitted (host-only) | omitted (host-only — `your.domain.com` only, not `.your.domain.com`) |
| `Path` | `/` | `/` |
| `SameSite` | `Lax` | `Lax` |
| `Secure` | `false` | `true` (HTTPS required) |
| `HttpOnly` | `true` | `true` |

The `Domain` attribute SHALL stay omitted (host-only) because web and api are served from the **same origin** via GCLB URL routing — there is no cross-subdomain cookie sharing required.

#### Scenario: Same-origin cookie just works

- **GIVEN** browser is at `https://your.domain.com/console`
- **WHEN** owner's session refreshes via `POST /api/auth/refresh`
- **THEN** the request SHALL include `Cookie: uteki_refresh=...` (host-only, same origin)
- **AND** no preflight OPTIONS request SHALL be triggered
- **AND** no `Access-Control-Allow-Credentials` response header SHALL be required

#### Scenario: No cross-origin cookie at any layer

- **WHEN** auditing prod cookie config
- **THEN** no cookie SHALL be set with `Domain=.your.domain.com` (leading dot)
- **AND** no cookie SHALL be set with `SameSite=None`
- **AND** if a future change introduces a subdomain (e.g. `docs.your.domain.com`), it SHALL NOT inherit the auth cookie

### Requirement: Cloud Run `ingress=internal-and-cloud-load-balancing`

Both `uteki-api` and `uteki-web` Cloud Run services SHALL set ingress to `internal-and-cloud-load-balancing`, blocking direct access to their `*.run.app` URLs.

#### Scenario: Direct Cloud Run URL is blocked

- **GIVEN** `uteki-api` is deployed with `--ingress=internal-and-cloud-load-balancing`
- **WHEN** an external client requests `https://uteki-api-<hash>.run.app/api/health`
- **THEN** Cloud Run SHALL return 403 (or 404, implementation-defined)
- **AND** the application SHALL NOT be invoked

#### Scenario: GCLB access still works

- **GIVEN** same ingress setting
- **WHEN** the same request comes through GCLB → backend service NEG
- **THEN** Cloud Run SHALL accept it
- **AND** the application SHALL be invoked normally

## NOT-MODIFIED (carry-over for clarity)

The following auth behaviors from change 010 SHALL be preserved unchanged:

- OWNER allowlist check inside OAuth callback (`is_owner` helper)
- `optional_user` for public-readable GET routes
- `require_owner` for mutation routes
- Prompt redaction at serialization layer (`SkillVersion.prompt` empty string for non-owners)
- httpOnly refresh cookie + access token in `Authorization: Bearer ...` header
- Refresh token family rotation + replay detection

This change ONLY introduces the env-driven callback base + prod secret sourcing + same-origin cookie config. Token lifecycles, error shapes, OAuth state CSRF, identity upsert, and owner-vs-reader role assignment all remain governed by `openspec/specs/auth/spec.md`.
