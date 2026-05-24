"""Memory interface.

Two layers, kept behind a single abstract surface so the harness doesn't care:

- **Short-term (session)**: per (user_id, session_id) message + event history.
  Used to give the agent its own conversation context across turns. M4: every
  read/write is scoped by ``user_id`` so two users can't ever read each
  other's session — pass-through ``session_id`` from a URL would otherwise
  let A read B's session by guessing.
- **Long-term (user/global)**: vector-backed facts ("user follows 半导体板块",
  "user 上次问过宁德时代"). Retrieved at the start of each run.

The default `InMemoryStore` is a non-persistent dict; production will swap in
Redis / Postgres + pgvector / Upstash, etc. behind this same interface.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent


class Memory(ABC):
    # --- short-term (user-scoped) ---
    @abstractmethod
    async def append_message(
        self, user_id: str, session_id: str, message: ChatMessage
    ) -> None: ...

    @abstractmethod
    async def get_messages(self, user_id: str, session_id: str) -> list[ChatMessage]: ...

    @abstractmethod
    async def append_event(
        self, user_id: str, session_id: str, event: AgentEvent
    ) -> None: ...

    @abstractmethod
    async def get_events(self, user_id: str, session_id: str) -> list[AgentEvent]: ...

    # --- long-term ---
    @abstractmethod
    async def remember_fact(self, user_id: str, fact: str, meta: dict[str, Any] | None = None) -> None: ...

    @abstractmethod
    async def recall_facts(self, user_id: str, query: str, limit: int = 5) -> list[str]: ...
