"""T1 — Auth chain.

Walks the full ladder: register → /me → login → refresh rotation
→ family-burn on replay → logout cookie clear → post-logout refresh
fails.

Plus four contract-quality assertions that no earlier conversation in
the codebase had reified into tests:
    a) bad-password and unknown-email return the exact same body
       (no email enumeration)
    b) garbage Bearer returns a generic "invalid token" (no PyJWT
       library internals leaking out)
    c) JWT kind protection: a refresh token sent as Bearer is rejected
    d) duplicate email → 409 Conflict (REST-correct; matches spec)
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from .conftest import AuthedUser, Reporter


def test_auth_full_ladder(client: TestClient, alice: AuthedUser, reporter: Reporter) -> None:
    reporter.section("register Alice")
    reporter.kv("user.id", alice.id)
    reporter.kv("access token len", len(alice.access_token))
    reporter.kv("refresh cookie present", bool(alice.refresh_cookie))
    assert alice.id and alice.access_token and alice.refresh_cookie

    reporter.section("GET /me with the issued access token")
    me = client.get("/api/auth/me", headers=alice.auth_header())
    reporter.checked("/me → 200", me.status_code == 200)
    reporter.checked("/me echoes alice's email", me.json()["email"] == alice.email)
    assert me.status_code == 200
    assert me.json()["email"] == alice.email

    reporter.section("refresh rotation")
    refresh1 = client.cookies.get("uteki_refresh")
    rot = client.post("/api/auth/refresh")
    refresh2 = client.cookies.get("uteki_refresh")
    reporter.checked("rotate → 200", rot.status_code == 200)
    reporter.checked("cookie value changed", refresh1 != refresh2)
    reporter.kv("new access token starts", rot.json()["access_token"][:24] + "...")
    assert rot.status_code == 200
    assert refresh1 != refresh2

    reporter.section("replay the OLD refresh → 401 family burn")
    spoof = TestClient(client.app)
    spoof.cookies.set("uteki_refresh", refresh1)
    replay = spoof.post("/api/auth/refresh")
    reporter.checked("replay → 401", replay.status_code == 401)
    reporter.kv("replay body", replay.json())
    assert replay.status_code == 401

    reporter.section("rotated child of burned family is also dead")
    dead = client.post("/api/auth/refresh")
    reporter.checked("refresh2 → 401 (family burned)", dead.status_code == 401)
    assert dead.status_code == 401

    reporter.section("re-login then logout → cookie cleared + revoked")
    relog = client.post(
        "/api/auth/login",
        json={"email": alice.email, "password": alice.password},
    )
    assert relog.status_code == 200
    pre = client.cookies.get("uteki_refresh")
    lo = client.post("/api/auth/logout")
    reporter.checked("logout → 204", lo.status_code == 204)
    reporter.checked(
        "logout response carries Set-Cookie clear",
        "set-cookie" in {h.lower() for h in lo.headers},
    )
    post = client.cookies.get("uteki_refresh")
    reporter.checked("client cookie jar dropped the cookie", post is None)
    assert lo.status_code == 204
    assert post is None

    reporter.section("post-logout refresh with the just-revoked token")
    zombie = TestClient(client.app)
    zombie.cookies.set("uteki_refresh", pre)
    zr = zombie.post("/api/auth/refresh")
    reporter.checked("revoked → 401", zr.status_code == 401)
    assert zr.status_code == 401

    reporter.end()


def test_auth_no_email_enumeration(client: TestClient, alice: AuthedUser, reporter: Reporter) -> None:
    reporter.section("a) bad-password and unknown-email must be indistinguishable")
    bad = client.post("/api/auth/login", json={"email": alice.email, "password": "WRONG"})
    # Use a non-reserved TLD — EmailStr would 422 on .test, masking the real check.
    unk = client.post("/api/auth/login", json={"email": "nobody@uteki-e2e.dev", "password": "pw12345678"})
    reporter.kv("bad-pw body", bad.json())
    reporter.kv("unknown body", unk.json())
    reporter.checked("both 401", bad.status_code == 401 and unk.status_code == 401)
    reporter.checked("identical detail (no enumeration)", bad.json() == unk.json())
    assert bad.status_code == 401 and unk.status_code == 401
    assert bad.json() == unk.json()
    reporter.end()


def test_auth_garbage_bearer_generic_error(client: TestClient, reporter: Reporter) -> None:
    reporter.section("b) garbage Bearer must NOT leak PyJWT internals")
    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not.a.jwt"})
    reporter.kv("body", r.json())
    reporter.checked("status 401", r.status_code == 401)
    reporter.checked(
        "detail is exactly 'invalid token' (no codec/structure leak)",
        r.json() == {"detail": "invalid token"},
    )
    assert r.status_code == 401
    assert r.json() == {"detail": "invalid token"}
    reporter.end()


def test_auth_refresh_cannot_be_used_as_access(client: TestClient, alice: AuthedUser, reporter: Reporter) -> None:
    reporter.section("c) JWT kind protection: refresh as Bearer → 401")
    refresh = client.cookies.get("uteki_refresh")
    assert refresh
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {refresh}"})
    reporter.kv("body", r.json())
    reporter.checked("401", r.status_code == 401)
    reporter.checked("body mentions 'access'", "access" in r.text.lower())
    assert r.status_code == 401
    reporter.end()


def test_auth_dup_email_is_conflict(client: TestClient, alice: AuthedUser, reporter: Reporter) -> None:
    reporter.section("d) duplicate email → 409 Conflict")
    r = client.post(
        "/api/auth/register",
        json={"email": alice.email, "password": "pw12345678"},
    )
    reporter.kv("status", r.status_code)
    reporter.kv("body", r.json())
    reporter.checked("409 not 400 (matches REST convention + spec)", r.status_code == 409)
    assert r.status_code == 409
    reporter.end()
