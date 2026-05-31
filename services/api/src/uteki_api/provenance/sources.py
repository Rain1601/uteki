"""RunSources facade injected into skills by the harness."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from uteki_api.artifacts import Artifact, RunArtifacts
from uteki_api.provenance.catalog import SourceCatalog
from uteki_api.provenance.citation_parser import CitationExtraction, extract_citations
from uteki_api.provenance.datapoint import DataPoint

SOURCE_CATALOG_ARTIFACT = "source-catalog.json"


def utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()


class RunSources:
    """Run-scoped source catalog facade.

    Skills and harness code use this facade instead of writing catalog
    artifacts directly.
    """

    def __init__(
        self,
        catalog: SourceCatalog,
        run_id: str,
        user_id: str | None = None,
    ) -> None:
        self.catalog = catalog
        self.run_id = run_id
        self.user_id = user_id

    def __len__(self) -> int:
        return len(self.catalog)

    async def add(self, partial: dict[str, Any]) -> int:
        if partial.get("fetched_at") is None:
            partial = {**partial, "fetched_at": utc_now_iso()}
        return self.catalog.add(partial)

    async def add_many(self, partials: list[dict[str, Any]]) -> list[int]:
        ids: list[int] = []
        for partial in partials:
            dp_id = await self.add(partial)
            if dp_id:
                ids.append(dp_id)
        return ids

    async def list(self) -> list[DataPoint]:
        return list(self.catalog)

    def valid_ids(self) -> set[int]:
        return self.catalog.valid_ids()

    def parse_citations(self, text: str) -> CitationExtraction:
        return extract_citations(text, valid_ids=self.valid_ids())

    async def write_artifact(self, artifacts: RunArtifacts) -> Artifact:
        payload = json.dumps(self.catalog.to_dict(), ensure_ascii=False, indent=2, default=str)
        return await artifacts.write(
            SOURCE_CATALOG_ARTIFACT,
            payload,
            kind="json",
            description="Run source catalog",
            role="source_catalog",
            display_name="Source catalog",
        )
