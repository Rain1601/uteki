"""GitHub OAuth provider.

Docs: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps
Scopes: ``user:email`` (so we can resolve a real email even when private).
"""

from __future__ import annotations

import urllib.parse

import httpx

from uteki_api.auth.oauth.common import ProviderUser
from uteki_api.core.config import settings

AUTH_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
EMAILS_URL = "https://api.github.com/user/emails"
SCOPE = "read:user user:email"


def callback_url() -> str:
    return f"{settings.oauth_redirect_base}/api/auth/oauth/github/callback"


def configured() -> bool:
    return bool(settings.github_client_id and settings.github_client_secret)


def authorize_url(state: str) -> str:
    params = {
        "client_id": settings.github_client_id,
        "redirect_uri": callback_url(),
        "scope": SCOPE,
        "state": state,
        "allow_signup": "true",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code(code: str) -> str:
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.github_client_id,
                "client_secret": settings.github_client_secret,
                "code": code,
                "redirect_uri": callback_url(),
            },
            headers={"Accept": "application/json"},
        )
        resp.raise_for_status()
        body = resp.json()
    access_token = body.get("access_token")
    if not access_token:
        raise RuntimeError(f"github exchange failed: {body}")
    return access_token


async def fetch_user(access_token: str) -> ProviderUser:
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "uteki",
    }
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        u_resp = await client.get(USER_URL, headers=headers)
        u_resp.raise_for_status()
        u = u_resp.json()

        email = u.get("email")
        if not email:
            # /user/emails returns the verified+primary one
            e_resp = await client.get(EMAILS_URL, headers=headers)
            if e_resp.status_code == 200:
                for entry in e_resp.json():
                    if entry.get("primary") and entry.get("verified"):
                        email = entry.get("email")
                        break

    return ProviderUser(
        provider="github",
        provider_user_id=str(u.get("id") or ""),
        email=email,
        name=u.get("name") or u.get("login") or "",
        avatar_url=u.get("avatar_url"),
    )
