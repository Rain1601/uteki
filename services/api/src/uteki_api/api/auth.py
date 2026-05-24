"""Authentication endpoints — register / login / refresh / logout / me.

Token transport (M4 decision, see plan):
- **access**: returned in JSON body; frontend stores in memory + sends as
  ``Authorization: Bearer ...``
- **refresh**: Set-Cookie, httpOnly, Secure (off in dev), SameSite=Lax

OAuth endpoints live in ``api/auth_oauth.py``.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field
from sqlmodel import Session, select

from uteki_api.auth.deps import current_user
from uteki_api.auth.jwt import (
    InvalidRefresh,
    issue_access,
    issue_refresh,
    revoke_refresh,
    rotate_refresh,
)
from uteki_api.auth.oauth import (
    github as oauth_github,
)
from uteki_api.auth.oauth import (
    google as oauth_google,
)
from uteki_api.auth.oauth import (
    make_state,
    upsert_user_from_identity,
    verify_state,
)
from uteki_api.core.config import settings
from uteki_api.core.db import get_db
from uteki_api.users import (
    DEMO_USER_EMAIL,
    default_user_store,
    hash_password,
    verify_password,
)
from uteki_api.users.models import AuthIdentity, User

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE = "uteki_refresh"


# ─── pydantic IO ────────────────────────────────────────────────────────


class RegisterBody(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)


class LoginBody(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    display_name: str
    avatar_url: str | None
    created_at: datetime
    status: str


class AccessTokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


# ─── cookie helper ──────────────────────────────────────────────────────


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    # In dev (http://localhost) Secure must be False or browser drops it.
    is_https = settings.oauth_redirect_base.startswith("https://")
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=is_https,
        samesite="lax",
        max_age=settings.refresh_token_ttl_seconds,
        path="/",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(REFRESH_COOKIE, path="/")


def _user_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        email=u.email,
        display_name=u.display_name,
        avatar_url=u.avatar_url,
        created_at=u.created_at,
        status=u.status,
    )


def _new_identity_id() -> str:
    return uuid.uuid4().hex[:16]


# ─── register / login ───────────────────────────────────────────────────


@router.post("/register", response_model=AccessTokenOut)
async def register(
    body: RegisterBody,
    response: Response,
    db: Session = Depends(get_db),
) -> AccessTokenOut:
    email = body.email.lower().strip()
    if email == DEMO_USER_EMAIL:
        raise HTTPException(400, detail="that email is reserved")

    existing = default_user_store.get_by_email(db, email)
    if existing is not None:
        raise HTTPException(409, detail="email already registered")

    user = default_user_store.create(
        db,
        email=email,
        display_name=body.display_name or email.split("@")[0],
    )
    identity = AuthIdentity(
        id=_new_identity_id(),
        user_id=user.id,
        provider="password",
        provider_user_id=email,
        password_hash=hash_password(body.password),
        created_at=datetime.now(UTC),
    )
    db.add(identity)
    db.commit()

    access = issue_access(user.id)
    refresh = issue_refresh(db, user.id)
    _set_refresh_cookie(response, refresh)
    return AccessTokenOut(access_token=access, user=_user_out(user))


@router.post("/login", response_model=AccessTokenOut)
async def login(
    body: LoginBody,
    response: Response,
    db: Session = Depends(get_db),
) -> AccessTokenOut:
    email = body.email.lower().strip()
    user = default_user_store.get_by_email(db, email)
    if user is None:
        raise HTTPException(401, detail="invalid email or password")
    if user.status != "active":
        raise HTTPException(403, detail=f"account status: {user.status}")

    statement = select(AuthIdentity).where(
        AuthIdentity.user_id == user.id,
        AuthIdentity.provider == "password",
    )
    identity = db.exec(statement).first()
    if identity is None or not verify_password(body.password, identity.password_hash):
        raise HTTPException(401, detail="invalid email or password")

    access = issue_access(user.id)
    refresh = issue_refresh(db, user.id)
    _set_refresh_cookie(response, refresh)
    return AccessTokenOut(access_token=access, user=_user_out(user))


# ─── refresh / logout / me ──────────────────────────────────────────────


@router.post("/refresh")
async def refresh(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    cookie = request.cookies.get(REFRESH_COOKIE)
    if not cookie:
        raise HTTPException(401, detail="missing refresh cookie")
    try:
        new_access, new_refresh = rotate_refresh(db, cookie)
    except InvalidRefresh as e:
        _clear_refresh_cookie(response)
        raise HTTPException(401, detail=str(e)) from e
    _set_refresh_cookie(response, new_refresh)
    return {"access_token": new_access, "token_type": "bearer"}


@router.post("/logout")
async def logout(
    request: Request,
    db: Session = Depends(get_db),
) -> Response:
    cookie = request.cookies.get(REFRESH_COOKIE)
    if cookie:
        revoke_refresh(db, cookie)
    # Build the response ourselves so the cookie-clear header lands on the
    # actual response — returning a fresh Response() would have lost it.
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    _clear_refresh_cookie(response)
    return response


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(current_user)) -> UserOut:
    return _user_out(user)


# ─── OAuth (GitHub / Google) ────────────────────────────────────────────

_PROVIDERS = {"github": oauth_github, "google": oauth_google}


@router.get("/oauth/{provider}/start")
async def oauth_start(provider: str, next: str = "/") -> RedirectResponse:
    p = _PROVIDERS.get(provider)
    if p is None:
        raise HTTPException(404, detail=f"unknown provider: {provider}")
    if not p.configured():
        raise HTTPException(503, detail=f"{provider} oauth is not configured")
    state = make_state(next)
    return RedirectResponse(p.authorize_url(state), status_code=302)


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    p = _PROVIDERS.get(provider)
    if p is None:
        raise HTTPException(404, detail=f"unknown provider: {provider}")
    if error:
        raise HTTPException(400, detail=f"{provider} oauth error: {error}")
    if not code or not state:
        raise HTTPException(400, detail="missing code or state")

    try:
        next_url = verify_state(state)
    except ValueError as e:
        raise HTTPException(400, detail=f"invalid state: {e}") from e

    access_token = await p.exchange_code(code)
    provider_user = await p.fetch_user(access_token)
    user = upsert_user_from_identity(db, provider_user)

    # Issue our own tokens and 302 to the frontend callback page (NOT
    # directly to next_url) so the React handler can stash the access
    # token before navigating onward. Access token rides in the URL
    # fragment (never sent to a server in logs); refresh as Set-Cookie.
    refresh = issue_refresh(db, user.id)
    target = (
        f"{settings.frontend_base}/oauth/{provider}/callback"
        f"#access_token={issue_access(user.id)}"
        f"&next={quote(next_url, safe='/?&=')}"
    )
    response = RedirectResponse(target, status_code=302)
    _set_refresh_cookie(response, refresh)
    return response
