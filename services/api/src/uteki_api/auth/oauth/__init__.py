"""OAuth providers — GitHub, Google.

Each provider exposes the same 3 callables consumed by ``api/auth.py``:
  - ``authorize_url(state, next_url) -> str``
  - ``async exchange_code(code) -> str``  (access_token)
  - ``async fetch_user(access_token) -> ProviderUser``

``ProviderUser`` is the normalized shape used by ``upsert_user_from_identity``.
"""

from __future__ import annotations

from uteki_api.auth.oauth.common import (
    ProviderUser,
    make_state,
    upsert_user_from_identity,
    verify_state,
)

__all__ = ["ProviderUser", "make_state", "upsert_user_from_identity", "verify_state"]
