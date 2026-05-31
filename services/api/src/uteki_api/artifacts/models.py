"""Artifact metadata model + kind/MIME helpers.

Content is stored on whatever ``ArtifactStore`` backs the run (filesystem by
default); only the metadata roundtrips through APIs.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

ArtifactKind = Literal["markdown", "json", "text", "binary"]
ArtifactRole = Literal[
    "primary",
    "draft",
    "plan",
    "contract",
    "evaluation",
    "trace",
    "source_catalog",
    "diagnosis",
    "auxiliary",
]


_CONTENT_TYPES: dict[ArtifactKind, str] = {
    "markdown": "text/markdown; charset=utf-8",
    "json": "application/json; charset=utf-8",
    "text": "text/plain; charset=utf-8",
    "binary": "application/octet-stream",
}


def content_type_for(kind: ArtifactKind) -> str:
    """Stable MIME for the given kind. Unknown kind → octet-stream."""
    return _CONTENT_TYPES.get(kind, "application/octet-stream")


class Artifact(BaseModel):
    """Metadata for one file-typed output of a skill.

    `name` is a flat filename within the run (e.g. ``"plan.md"``). The
    physical location is decided by the store; readers should always go
    through the store + RunArtifacts facade rather than guessing paths.
    """

    run_id: str
    name: str
    kind: ArtifactKind
    size_bytes: int
    sha256: str
    created_at: float
    written_by: str
    description: str = ""
    content_type: str = ""
    role: ArtifactRole = "auxiliary"
    display_name: str = ""
    source_refs: list[int] = Field(default_factory=list)
