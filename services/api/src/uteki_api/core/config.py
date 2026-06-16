import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Load `services/api/.env` into os.environ before the Settings instance is
# constructed below. We can't rely on pydantic-settings' built-in env_file
# loader here because we hand-build the Settings(...) instance with os.getenv()
# calls (to support provider-conventional names like DEEPSEEK_API_KEY without
# a UTEKI_ prefix). Resolve the path relative to this file so `uv run` from
# any cwd still finds it.
_ENV_PATH = Path(__file__).resolve().parents[3] / ".env"
load_dotenv(_ENV_PATH, override=False)


class Settings(BaseSettings):
    """uteki backend settings.

    Convention:
      - Cross-cutting platform settings (CORS, mock toggle, default model) use
        the `UTEKI_` prefix.
      - Provider API keys keep their **conventional** name (`ANTHROPIC_API_KEY`,
        `OPENROUTER_API_KEY`, `AIHUBMIX_API_KEY`) so existing tools / scripts /
        local `.env` files just work.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
    )

    # ── Platform (UTEKI_ prefix) ─────────────────────────────────────────
    cors_origins: str = "http://localhost:3000"
    use_mock_llm: bool = True
    default_model: str = "anthropic/claude-sonnet-4-6"
    # Data tools default to fixtures when the app runs in mock-LLM mode, so
    # tests stay hermetic. Local real-LLM runs default to live market data.
    use_mock_data: bool = True
    # Self-evolution loop: when True, cc_runner synthesizes a canned critique
    # + patch instead of spawning the `claude` CLI. Follows use_mock_llm by
    # default so the E2E suite stays hermetic without a CC install.
    use_mock_cc: bool = True
    # Path to the Claude Code CLI binary (only used when use_mock_cc=False).
    cc_cli_path: str = "claude"
    # Model the CC subprocess uses for review.  Sonnet is the default since
    # critique quality + cost balance; drift_monitor can override to opus for
    # severe regressions.
    cc_model: str = "claude-sonnet-4-6"
    # Max wall-time for a single CC review (seconds). Keep generous because
    # CC will Read several artifacts + reason through a critique.
    cc_timeout_seconds: float = 600.0

    # Legacy OpenAI-compat fallback for bare model ids
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = "gpt-4o-mini"

    # ── Provider keys (conventional names, no prefix) ────────────────────
    anthropic_api_key: str = ""
    anthropic_base_url: str = ""
    openrouter_api_key: str = ""
    openrouter_base_url: str = ""
    aihubmix_api_key: str = ""
    aihubmix_base_url: str = ""
    deepseek_api_key: str = ""
    deepseek_base_url: str = ""
    fmp_api_key: str = ""
    google_search_api_key: str = ""
    google_search_engine_id: str = ""

    # SEC EDGAR requires a User-Agent with contact email (Fair Access).
    # Format: "<app name> <admin email>" (e.g. "uteki research a@b.com").
    sec_user_agent: str = ""

    # ── M4: auth + storage ───────────────────────────────────────────────
    # SQLite by default; flip to postgresql://... for prod.
    db_url: str = "sqlite:///data/uteki.db"
    # RunStore backend: "memory" (process-local, faster, dies on restart) vs
    # "sqlite" (durable, visible across processes — required for MCP server
    # to read runs created by the HTTP server). Tests use "memory" via the
    # conftest singleton-rebind pattern regardless of this setting.
    run_store: str = "sqlite"
    # HS256 signing key for JWTs. Generate a 32+ char random in prod.
    jwt_secret: str = "dev-secret-change-me"
    # Lifetimes
    access_token_ttl_seconds: int = 15 * 60
    refresh_token_ttl_seconds: int = 30 * 24 * 60 * 60
    # When false: requests without a valid token are served as `demo@local`
    # (a stable dev user the app ensures exists at startup).
    auth_required: bool = True
    # Local-only override: grant the current caller every operation permission
    # without changing their persisted role. This keeps dev/debug friction low
    # while leaving production RBAC explicit.
    local_all_permissions: bool = False
    admin_emails: str = ""
    admin_github_logins: str = ""
    admin_github_ids: str = ""
    # 010 — owner allowlist for the single-owner public-readonly model.
    # In practice owner == admin for this deployment shape; these names
    # exist so route signatures and env config read with the right product
    # vocabulary. Values are unioned with admin_emails / admin_github_logins
    # at role-resolution time, so legacy ADMIN_* env vars keep working.
    owner_emails: str = ""
    owner_github_logins: str = ""
    # Shared secret for HMAC-SHA256 signature on POST /api/triggers/event.
    # Required in production (auth_required=True). In dev (auth_required=False)
    # an unset secret still allows anonymous webhook firing so a local curl
    # smoke-test stays one-liner; ops MUST set this before exposing the API
    # to the public internet.
    webhook_secret: str = ""
    # 013 — async post-run LLM judge. Disabled by default so e2e + first
    # local boot don't fire LLM calls; flip to True in prod once a judge
    # model is configured. mock-LLM mode short-circuits even when True.
    run_eval_enabled: bool = False
    # OAuth: blank = button disabled in UI.
    github_client_id: str = ""
    github_client_secret: str = ""
    google_client_id: str = ""
    google_client_secret: str = ""
    # Where the OAuth callback URLs should send the browser after exchange.
    # Both providers' callback URL must be registered as
    # `{oauth_redirect_base}/api/auth/oauth/<provider>/callback`.
    oauth_redirect_base: str = "http://localhost:8000"
    # Where the frontend lives (used by callback redirects after token issuance).
    frontend_base: str = "http://localhost:3000"

    # ── Artifact storage backend ─────────────────────────────────────────
    # "fs" (default) → LocalFileArtifactStore under data/runs/.
    # "gcs"          → GCSArtifactStore (requires `uteki-api[gcs]` extra).
    storage_backend: str = "fs"
    # GCS bucket name (without gs:// prefix). Required when storage_backend=gcs.
    gcs_bucket: str | None = None
    # Optional: path to a service-account JSON for local dev against GCS.
    # In Cloud Run, leave blank → Application Default Credentials (ADC) take over.
    gcs_credentials_path: str | None = None

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


def _envflag(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


settings = Settings(
    cors_origins=os.getenv("UTEKI_CORS_ORIGINS") or "http://localhost:3000",
    use_mock_llm=_envflag("UTEKI_USE_MOCK_LLM", True),
    use_mock_data=_envflag("UTEKI_USE_MOCK_DATA", _envflag("UTEKI_USE_MOCK_LLM", True)),
    use_mock_cc=_envflag("UTEKI_USE_MOCK_CC", _envflag("UTEKI_USE_MOCK_LLM", True)),
    cc_cli_path=os.getenv("UTEKI_CC_CLI_PATH") or "claude",
    cc_model=os.getenv("UTEKI_CC_MODEL") or "claude-sonnet-4-6",
    cc_timeout_seconds=float(os.getenv("UTEKI_CC_TIMEOUT_SECONDS") or "600"),
    default_model=os.getenv("UTEKI_DEFAULT_MODEL") or "anthropic/claude-sonnet-4-6",
    llm_base_url=os.getenv("UTEKI_LLM_BASE_URL") or "",
    llm_api_key=os.getenv("UTEKI_LLM_API_KEY") or "",
    llm_model=os.getenv("UTEKI_LLM_MODEL") or "gpt-4o-mini",
    anthropic_api_key=os.getenv("ANTHROPIC_API_KEY") or "",
    anthropic_base_url=os.getenv("ANTHROPIC_BASE_URL") or "",
    openrouter_api_key=os.getenv("OPENROUTER_API_KEY") or "",
    openrouter_base_url=os.getenv("OPENROUTER_BASE_URL") or "",
    aihubmix_api_key=os.getenv("AIHUBMIX_API_KEY") or "",
    aihubmix_base_url=os.getenv("AIHUBMIX_BASE_URL") or "",
    deepseek_api_key=os.getenv("DEEPSEEK_API_KEY") or "",
    deepseek_base_url=os.getenv("DEEPSEEK_BASE_URL") or "",
    fmp_api_key=os.getenv("FMP_API_KEY") or "",
    sec_user_agent=os.getenv("UTEKI_SEC_USER_AGENT") or "",
    google_search_api_key=(
        os.getenv("GOOGLE_SEARCH_API_KEY") or os.getenv("GOOGLE_CUSTOM_SEARCH_API_KEY") or ""
    ),
    google_search_engine_id=(
        os.getenv("GOOGLE_SEARCH_ENGINE_ID") or os.getenv("GOOGLE_CUSTOM_SEARCH_ENGINE_ID") or ""
    ),
    db_url=os.getenv("UTEKI_DB_URL") or "sqlite:///data/uteki.db",
    run_store=(os.getenv("UTEKI_RUN_STORE") or "sqlite").lower(),
    jwt_secret=os.getenv("UTEKI_JWT_SECRET") or "dev-secret-change-me",
    auth_required=_envflag("UTEKI_AUTH_REQUIRED", True),
    # Default OFF — previously this defaulted to true whenever auth was
    # disabled, which produced a confusing "reader role with admin:*
    # permissions" cached on demo@local. The honest equivalent is now baked
    # into ensure_demo_user (it promotes the dev demo user to role=admin
    # when auth_required=false), so role-based gating works the same way
    # locally and in prod. The flag is still respected if explicitly set —
    # the e2e suite uses it to verify reader-with-elevated-perms behaviour.
    local_all_permissions=_envflag("UTEKI_LOCAL_ALL_PERMISSIONS", False),
    admin_emails=(
        os.getenv("UTEKI_ADMIN_EMAILS")
        or os.getenv("UTEKI_ADMIN_EMAIL")
        or os.getenv("UTEKI_OWNER_EMAIL")
        or ""
    ),
    admin_github_logins=(
        os.getenv("UTEKI_ADMIN_GITHUB_LOGINS")
        or os.getenv("UTEKI_ADMIN_GITHUB_LOGIN")
        or ""
    ),
    admin_github_ids=(
        os.getenv("UTEKI_ADMIN_GITHUB_IDS")
        or os.getenv("UTEKI_ADMIN_GITHUB_ID")
        or ""
    ),
    webhook_secret=os.getenv("UTEKI_WEBHOOK_SECRET") or "",
    run_eval_enabled=_envflag("UTEKI_RUN_EVAL_ENABLED", False),
    owner_emails=(
        os.getenv("UTEKI_OWNER_EMAILS")
        or os.getenv("UTEKI_OWNER_EMAIL")
        or ""
    ),
    owner_github_logins=(
        os.getenv("UTEKI_OWNER_GITHUB_LOGINS")
        or os.getenv("UTEKI_OWNER_GITHUB_LOGIN")
        or ""
    ),
    github_client_id=os.getenv("GITHUB_CLIENT_ID") or "",
    github_client_secret=os.getenv("GITHUB_CLIENT_SECRET") or "",
    google_client_id=os.getenv("GOOGLE_CLIENT_ID") or "",
    google_client_secret=os.getenv("GOOGLE_CLIENT_SECRET") or "",
    oauth_redirect_base=os.getenv("UTEKI_OAUTH_REDIRECT_BASE") or "http://localhost:8000",
    frontend_base=os.getenv("UTEKI_FRONTEND_BASE") or "http://localhost:3000",
    storage_backend=(os.getenv("UTEKI_STORAGE_BACKEND") or "fs").lower(),
    gcs_bucket=os.getenv("UTEKI_GCS_BUCKET") or None,
    gcs_credentials_path=os.getenv("UTEKI_GCS_CREDENTIALS_PATH") or None,
)
