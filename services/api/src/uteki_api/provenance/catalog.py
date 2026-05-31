"""SourceCatalog — per-run registry of citable DataPoints."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from typing import Any

from uteki_api.provenance.datapoint import DataPoint, SourceType

logger = logging.getLogger(__name__)


class SourceCatalog:
    """Assigns stable run-local ids to source-backed facts."""

    def __init__(self, *, run_id: str | None = None, as_of: str | None = None) -> None:
        self.run_id = run_id
        self.as_of = as_of
        self._items: dict[int, DataPoint] = {}
        self._next_id = 1
        self._url_index: dict[tuple[str, str], int] = {}
        self._computed_index: dict[tuple[str, str, str], int] = {}

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[DataPoint]:
        for key in sorted(self._items):
            yield self._items[key]

    def add(self, partial: dict[str, Any]) -> int:
        """Register a DataPoint partial and return its assigned id.

        ``partial`` must contain all required DataPoint fields except ``id``.
        ``as_of`` is inherited from the catalog when omitted.
        """
        source_url = partial.get("source_url")
        key = str(partial.get("key") or "")
        source_type = partial.get("source_type")

        if source_url:
            cached = self._url_index.get((str(source_url), key))
            if cached is not None:
                return cached
        elif source_type == "computed":
            cached = self._computed_index.get((str(source_type), key, str(partial.get("value"))))
            if cached is not None:
                return cached

        if self.as_of is not None and partial.get("as_of") is None:
            partial = {**partial, "as_of": self.as_of}

        if self.as_of and partial.get("published_at"):
            try:
                if str(partial["published_at"])[:10] > self.as_of[:10]:
                    logger.warning(
                        "rejecting future source %r published_at=%s as_of=%s",
                        key,
                        partial["published_at"],
                        self.as_of,
                    )
                    return 0
            except (TypeError, IndexError):
                pass

        new_id = self._next_id
        self._next_id += 1
        point = DataPoint.model_validate({**partial, "id": new_id})
        self._items[new_id] = point

        if source_url:
            self._url_index[(str(source_url), key)] = new_id
        elif source_type == "computed":
            self._computed_index[(str(source_type), key, str(partial.get("value")))] = new_id

        return new_id

    def get(self, dp_id: int) -> DataPoint | None:
        return self._items.get(dp_id)

    def has(self, dp_id: int) -> bool:
        return dp_id in self._items

    def valid_ids(self) -> set[int]:
        return set(self._items)

    def by_source_type(self, source_type: SourceType) -> list[DataPoint]:
        return [point for point in self if point.source_type == source_type]

    def grounded(self) -> list[DataPoint]:
        return [point for point in self if point.is_grounded()]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "items": {str(point.id): point.model_dump() for point in self},
        }

    def to_llm_block(self, ids: list[int] | None = None, max_excerpt: int = 200) -> str:
        """Render compact `[src:N]` lines for model-visible context."""
        lines: list[str] = []
        target_ids = ids if ids is not None else sorted(self._items)
        for dp_id in target_ids:
            point = self._items.get(dp_id)
            if point is None:
                continue
            pub = f" ({point.published_at[:10]})" if point.published_at else ""
            publisher = point.publisher or point.source_type
            value_repr = ""
            if point.excerpt:
                excerpt = point.excerpt[:max_excerpt].replace("\n", " ")
                value_repr = f': "{excerpt}"'
            elif isinstance(point.value, (int, float, str, bool)):
                value_repr = f": {point.value}"
            lines.append(f"[src:{dp_id}] {publisher}{pub} - {point.key}{value_repr}")
        return "\n".join(lines)
