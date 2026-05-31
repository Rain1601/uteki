"""Artifact layer — file-typed outputs produced by a skill during a run.

Anthropic harness design principle: "Communication was handled via files: one
agent would write a file, another agent would read it and respond either
within that file or with a new file." This package implements that channel.

Each artifact belongs to exactly one run. Skills receive a ``RunArtifacts``
facade (injected by the harness) bound to the current run + skill identity,
so they only see what's relevant to the work in front of them.

Storage is pluggable. The default is ``LocalFileArtifactStore`` rooted at
``data/runs/``; M5.4 will swap in S3 / Vercel Blob behind the same ABC.
"""

from __future__ import annotations

from uteki_api.artifacts.models import Artifact, ArtifactKind, ArtifactRole, content_type_for
from uteki_api.artifacts.store import (
    ArtifactStore,
    LocalFileArtifactStore,
    RunArtifacts,
    default_artifact_store,
)

__all__ = [
    "Artifact",
    "ArtifactKind",
    "ArtifactRole",
    "content_type_for",
    "ArtifactStore",
    "LocalFileArtifactStore",
    "RunArtifacts",
    "default_artifact_store",
]
