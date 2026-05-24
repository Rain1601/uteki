"""Google OAuth provider (OAuth 2.0 + OpenID Connect userinfo).

Docs: https://developers.google.com/identity/protocols/oauth2/web-server
Scopes: ``openid email profile``.
"""

from __future__ import annotations

import urllib.parse

import httpx

from uteki_api.auth.oauth.common import ProviderUser
from uteki_api.core.config import settings

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPE = "openid email profile"


def callback_url() -> str:
    return f"{settings.oauth_redirect_base}/api/auth/oauth/google/callback"


def configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def authorize_url(state: str) -> str:
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": callback_url(),
        "response_type": "code",
        "scope": SCOPE,
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


async def exchange_code(code: str) -> str:
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        resp = await client.post(
            TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": callback_url(),
            },
        )
        resp.raise_for_status()
        body = resp.json()
    access_token = body.get("access_token")
    if not access_token:
        raise RuntimeError(f"google exchange failed: {body}")
    return access_token


async def fetch_user(access_token: str) -> ProviderUser:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0)) as client:
        resp = await client.get(USERINFO_URL, headers=headers)
        resp.raise_for_status()
        u = resp.json()

    return ProviderUser(
        provider="google",
        provider_user_id=str(u.get("sub") or ""),
        email=u.get("email"),
        name=u.get("name") or "",
        avatar_url=u.get("picture"),
    )
