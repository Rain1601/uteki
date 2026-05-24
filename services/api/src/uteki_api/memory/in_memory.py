"""Non-persistent dict-backed memory.

For dev only. Swap with Redis/Postgres in prod by implementing `Memory`.

M4: short-term keys are (user_id, session_id) tuples so cross-user session
collisions can't happen — two users picking the same session_id stay
isolated.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from uteki_api.memory.base import Memory
from uteki_api.schemas.chat import ChatMessage
from uteki_api.schemas.events import AgentEvent


class InMemoryStore(Memory):
    def __init__(self) -> None:
        self._messages: dict[tuple[str, str], list[ChatMessage]] = defaultdict(list)
        self._events: dict[tuple[str, str], list[AgentEvent]] = defaultdict(list)
        self._facts: dict[str, list[tuple[str, dict[str, Any]]]] = defaultdict(list)

    async def append_message(
        self, user_id: str, session_id: str, message: ChatMessage
    ) -> None:
        self._messages[(user_id, session_id)].append(message)

    async def get_messages(self, user_id: str, session_id: str) -> list[ChatMessage]:
        return list(self._messages[(user_id, session_id)])

    async def append_event(
        self, user_id: str, session_id: str, event: AgentEvent
    ) -> None:
        self._events[(user_id, session_id)].append(event)

    async def get_events(self, user_id: str, session_id: str) -> list[AgentEvent]:
        return list(self._events[(user_id, session_id)])

    async def remember_fact(
        self, user_id: str, fact: str, meta: dict[str, Any] | None = None
    ) -> None:
        self._facts[user_id].append((fact, meta or {}))

    async def recall_facts(self, user_id: str, query: str, limit: int = 5) -> list[str]:
        q = query.lower()
        scored = [
            (fact, sum(1 for word in q.split() if word in fact.lower()))
            for fact, _meta in self._facts[user_id]
        ]
        scored.sort(key=lambda t: t[1], reverse=True)
        return [fact for fact, score in scored[:limit] if score > 0]
