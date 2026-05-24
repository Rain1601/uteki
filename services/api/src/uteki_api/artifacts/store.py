"""Artifact store — abstract + LocalFile implementation + RunArtifacts facade.

LocalFileArtifactStore layout::

    <root>/<sha2>/<run_id>/
    ├── manifest.json
    └── artifacts/
        └── <name>

``<sha2>`` is the first two characters of ``run_id`` — cheap sharding to keep
single directories from accumulating thousands of subdirs.

``manifest.json`` is the authoritative metadata index for the run. It's
rewritten atomically (write to ``.tmp`` then ``os.replace``) on every
artifact write so a crash can't leave a partial JSON file.

Name validation rejects anything outside ``[A-Za-z0-9._-]+`` and explicitly
rejects ``..``. Combined with an absolute-path check that the resolved
target sits inside ``<root>/<sha2>/<run_id>/artifacts/``, this defeats path
traversal attacks coming in through the public REST endpoint.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path

from uteki_api.artifacts.models import Artifact, ArtifactKind, content_type_for

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _validate_name(name: str) -> None:
    """Reject any name that could escape its artifact directory.

    Rules:
    - Must be non-empty
    - Must match ``[A-Za-z0-9._-]+`` (no slashes, no spaces, no shell metachars)
    - Must not be exactly ``.`` or ``..``
    """
    if not name:
        raise ValueError("artifact name must be non-empty")
    if name in (".", ".."):
        raise ValueError("artifact name must not be . or ..")
    if not _NAME_RE.fullmatch(name):
        raise ValueError(
            f"artifact name {name!r} contains disallowed characters; "
            "allowed: letters, digits, dot, underscore, hyphen"
        )


class ArtifactStore(ABC):
    """Each method takes an optional ``user_id`` (M4).

    When set, the storage backend partitions by user. When None, the
    backend uses an unpartitioned layout — useful for internal callers
    that don't have user context (e.g. eval runs running as ``system``).
    """

    @abstractmethod
    async def write(
        self,
        run_id: str,
        name: str,
        content: bytes | str,
        *,
        kind: ArtifactKind,
        written_by: str,
        description: str = "",
        user_id: str | None = None,
    ) -> Artifact: ...

    @abstractmethod
    async def read(
        self, run_id: str, name: str, user_id: str | None = None
    ) -> tuple[Artifact, bytes]: ...

    @abstractmethod
    async def list(self, run_id: str, user_id: str | None = None) -> list[Artifact]: ...

    @abstractmethod
    async def exists(
        self, run_id: str, name: str, user_id: str | None = None
    ) -> bool: ...


class LocalFileArtifactStore(ArtifactStore):
    """File-backed artifact store with optional per-user partitioning.

    M4: paths look like ``<root>/users/<user_id>/runs/<sha2>/<run_id>/...``.
    When ``user_id`` isn't supplied (legacy / internal call), we fall back to
    the unpartitioned ``<root>/<sha2>/<run_id>/...`` layout from M5. The
    artifact REST endpoint always resolves user_id from the run record so a
    URL like ``/api/runs/{id}/artifacts/{name}`` works without the user
    needing to know which partition holds the file.
    """

    def __init__(self, root: Path | str = Path("data/runs")) -> None:
        self.root = Path(root).resolve()

    # ── directory helpers ───────────────────────────────────────────────

    def _run_dir(self, run_id: str, user_id: str | None = None) -> Path:
        if not run_id or "/" in run_id or "\\" in run_id:
            raise ValueError(f"invalid run_id: {run_id!r}")
        if user_id and ("/" in user_id or "\\" in user_id or user_id in (".", "..")):
            raise ValueError(f"invalid user_id: {user_id!r}")
        shard = run_id[:2] if len(run_id) >= 2 else "_"
        if user_id:
            return self.root / "users" / user_id / "runs" / shard / run_id
        return self.root / shard / run_id

    def _artifact_path(
        self, run_id: str, name: str, user_id: str | None = None
    ) -> Path:
        _validate_name(name)
        run_dir = self._run_dir(run_id, user_id)
        candidate = (run_dir / "artifacts" / name).resolve()
        allowed_root = (run_dir / "artifacts").resolve()
        # Defence-in-depth: even after regex, ensure the final path stays inside.
        if not str(candidate).startswith(str(allowed_root) + os.sep) and candidate != allowed_root:
            raise ValueError(f"artifact path escaped sandbox: {candidate}")
        return candidate

    def _manifest_path(self, run_id: str, user_id: str | None = None) -> Path:
        return self._run_dir(run_id, user_id) / "manifest.json"

    # ── manifest read/write ─────────────────────────────────────────────

    def _read_manifest(self, run_id: str, user_id: str | None = None) -> list[dict]:
        path = self._manifest_path(run_id, user_id)
        if not path.exists():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
        return data if isinstance(data, list) else []

    def _write_manifest(
        self, run_id: str, items: list[dict], user_id: str | None = None
    ) -> None:
        path = self._manifest_path(run_id, user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _upsert_manifest(
        self, run_id: str, artifact: Artifact, user_id: str | None = None
    ) -> None:
        items = self._read_manifest(run_id, user_id)
        items = [i for i in items if i.get("name") != artifact.name]  # last-write-wins
        items.append(artifact.model_dump())
        self._write_manifest(run_id, items, user_id)

    # ── ABC implementation ─────────────────────────────────────────────

    async def write(
        self,
        run_id: str,
        name: str,
        content: bytes | str,
        *,
        kind: ArtifactKind,
        written_by: str,
        description: str = "",
        user_id: str | None = None,
    ) -> Artifact:
        path = self._artifact_path(run_id, name, user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        body = content.encode("utf-8") if isinstance(content, str) else content

        # Atomic write: .tmp then replace.
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(body)
        os.replace(tmp, path)

        artifact = Artifact(
            run_id=run_id,
            name=name,
            kind=kind,
            size_bytes=len(body),
            sha256=hashlib.sha256(body).hexdigest(),
            created_at=time.time(),
            written_by=written_by,
            description=description,
            content_type=content_type_for(kind),
        )
        self._upsert_manifest(run_id, artifact, user_id)
        return artifact

    async def read(
        self, run_id: str, name: str, user_id: str | None = None
    ) -> tuple[Artifact, bytes]:
        path = self._artifact_path(run_id, name, user_id)
        if not path.exists():
            raise FileNotFoundError(f"artifact not found: {run_id}/{name}")
        body = path.read_bytes()
        meta_entries = [
            i for i in self._read_manifest(run_id, user_id) if i.get("name") == name
        ]
        if not meta_entries:
            raise FileNotFoundError(f"manifest entry missing: {run_id}/{name}")
        meta = Artifact.model_validate(meta_entries[0])
        return meta, body

    async def list(self, run_id: str, user_id: str | None = None) -> list[Artifact]:
        return [Artifact.model_validate(i) for i in self._read_manifest(run_id, user_id)]

    async def exists(
        self, run_id: str, name: str, user_id: str | None = None
    ) -> bool:
        try:
            return self._artifact_path(run_id, name, user_id).exists()
        except ValueError:
            return False


class RunArtifacts:
    """Run-scoped facade. Injected onto ``BaseAgent.artifacts`` by the harness.

    Skills get a tiny surface that already knows the run_id, writer name,
    and (M4) owning user, so they can ``await self.artifacts.write("plan.md",
    body)`` without having to plumb context.
    """

    def __init__(
        self,
        store: ArtifactStore,
        run_id: str,
        written_by: str,
        user_id: str | None = None,
    ) -> None:
        self._store = store
        self._run_id = run_id
        self._written_by = written_by
        self._user_id = user_id

    @property
    def run_id(self) -> str:
        return self._run_id

    @property
    def user_id(self) -> str | None:
        return self._user_id

    async def write(
        self,
        name: str,
        content: bytes | str,
        *,
        kind: ArtifactKind = "markdown",
        description: str = "",
    ) -> Artifact:
        return await self._store.write(
            self._run_id,
            name,
            content,
            kind=kind,
            written_by=self._written_by,
            description=description,
            user_id=self._user_id,
        )

    async def read(self, name: str) -> bytes:
        _meta, body = await self._store.read(self._run_id, name, self._user_id)
        return body

    async def read_text(self, name: str) -> str:
        body = await self.read(name)
        return body.decode("utf-8")

    async def list(self) -> list[Artifact]:
        return await self._store.list(self._run_id, self._user_id)

    async def exists(self, name: str) -> bool:
        return await self._store.exists(self._run_id, name, self._user_id)


default_artifact_store: ArtifactStore = LocalFileArtifactStore()
