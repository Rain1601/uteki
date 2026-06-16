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
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path

from uteki_api.artifacts.models import Artifact, ArtifactKind, ArtifactRole, content_type_for

logger = logging.getLogger(__name__)

_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+$")


def _strip_preamble(content: str) -> tuple[str, int, int]:
    """Strip everything before the first top-level ``# `` heading.

    Returns ``(new_content, dropped_lines, dropped_bytes)``. If the content
    contains no top-level ``#`` heading at all, returns the input untouched
    (no slicing; that's a different failure to surface).

    Why this exists: see guardrails §5a + design/02 — DeepSeek and others
    sometimes prepend 2-5 lines of meta-narration ("先拉取数据..." / "现在
    直接写出最终交付物...") before the actual deliverable, despite explicit
    prompt instructions not to. Pure-prompt mitigation hit diminishing
    returns across 3 iterations on 2026-05-26; this deterministic strip is
    the right fix at the seam.

    Subtlety from run 4 (2026-05-26): the model sometimes **squashes**
    preamble and title onto a single line with no newline between them
    ("我来拉取数据...# 中国半导体设备板块"). Line-anchored matching misses
    this. The regex below matches any ``# `` (space required to exclude
    ``##`` subheaders) **not preceded by another ``#``**, regardless of
    whether a newline precedes it.

    Behavior:
    - Content already starting with ``# ``: returned as-is (untouched).
    - Top-level ``# `` found later (newline-anchored OR inline): strip
      everything before it.
    - Subheaders only (``## `` etc.) but no top-level ``# ``: untouched.
    - No ``#`` at all: untouched (raw failure surfaces to reviewer).
    """
    if content.startswith("# "):
        return content, 0, 0
    # `[^#]# ` finds the first top-level "# " preceded by a non-# char.
    # This excludes `##`+ subheaders (preceded by `#`) and matches whether
    # the predecessor is a newline (line-anchored) or any other char
    # (inline-squashed preamble).
    match = re.search(r"[^#]# ", content)
    if match is None:
        return content, 0, 0
    # match.start() is the non-# char; the `#` starts at +1.
    hash_pos = match.start() + 1
    dropped = content[:hash_pos]
    kept = content[hash_pos:]
    return kept, dropped.count("\n"), len(dropped.encode("utf-8"))


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
        role: ArtifactRole = "auxiliary",
        display_name: str = "",
        source_refs: list[int] | None = None,
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

    async def delete_run(self, run_id: str, user_id: str | None = None) -> None:
        """Drop every artifact + manifest for a run. Default impl is a no-op
        so backends that haven't implemented physical cleanup (e.g. some
        ephemeral test stubs) don't break callers — but the API DELETE
        endpoint relies on the concrete LocalFile / GCS impls below."""
        return


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
        role: ArtifactRole = "auxiliary",
        display_name: str = "",
        source_refs: list[int] | None = None,
    ) -> Artifact:
        path = self._artifact_path(run_id, name, user_id)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Post-process markdown deliverables: strip any preamble before the
        # first top-level `# ` heading. Empirically (DeepSeek-chat across
        # 3 runs, 2026-05-26) the model writes ~3 lines of meta-narration
        # before the actual deliverable even when guardrails §5a explicitly
        # forbids it. Pure-prompt mitigation hit diminishing returns; a
        # deterministic strip-at-the-seam is the correct fix.
        # Skipped for non-markdown (JSON outputs are not header-anchored)
        # and for markdown content that has no top-level # header at all
        # (don't randomly slice; that's a different failure to surface).
        if kind == "markdown" and isinstance(content, str):
            stripped, dropped_lines, dropped_bytes = _strip_preamble(content)
            if dropped_bytes > 0:
                logger.info(
                    "stripped %d-line / %d-byte preamble from %s in run %s",
                    dropped_lines, dropped_bytes, name, run_id,
                )
                content = stripped
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
            role=role,
            display_name=display_name,
            source_refs=source_refs or [],
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

    async def delete_run(self, run_id: str, user_id: str | None = None) -> None:
        import shutil
        run_dir = self._run_dir(run_id, user_id)
        if run_dir.exists():
            shutil.rmtree(run_dir, ignore_errors=True)


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
        role: ArtifactRole = "auxiliary",
        display_name: str = "",
        source_refs: list[int] | None = None,
    ) -> Artifact:
        return await self._store.write(
            self._run_id,
            name,
            content,
            kind=kind,
            written_by=self._written_by,
            description=description,
            user_id=self._user_id,
            role=role,
            display_name=display_name,
            source_refs=source_refs,
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


def make_default_artifact_store() -> ArtifactStore:
    """Construct the configured ArtifactStore from settings.

    Selects between the local filesystem backend (default — used in dev, tests,
    and any deployment not on GCS) and the GCS backend (production Cloud Run).

    The GCS import is lazy: callers running the default "fs" backend never
    pay the ``google.cloud.storage`` import cost and don't need the [gcs] extra
    installed.
    """
    # Imported lazily to avoid a config<->settings import cycle at module load
    # time (this module is imported from `__init__` during package init).
    from uteki_api.core.config import settings  # noqa: PLC0415

    if settings.storage_backend == "gcs":
        from uteki_api.artifacts.gcs_store import GCSArtifactStore  # noqa: PLC0415

        if not settings.gcs_bucket:
            raise RuntimeError(
                "UTEKI_STORAGE_BACKEND=gcs requires UTEKI_GCS_BUCKET to be set"
            )
        return GCSArtifactStore(
            bucket_name=settings.gcs_bucket,
            credentials_path=settings.gcs_credentials_path,
        )
    return LocalFileArtifactStore()


default_artifact_store: ArtifactStore = make_default_artifact_store()
