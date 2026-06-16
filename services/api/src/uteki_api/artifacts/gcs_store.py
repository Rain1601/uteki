"""GCS-backed ArtifactStore for Cloud Run / production deployments.

Path scheme mirrors :class:`LocalFileArtifactStore`, minus the ``data/runs/``
prefix (the bucket IS the root)::

    gs://<bucket>/users/<user_id>/runs/<sha2>/<run_id>/manifest.json
    gs://<bucket>/users/<user_id>/runs/<sha2>/<run_id>/artifacts/<name>

When ``user_id`` is omitted (internal callers, e.g. system eval), the layout
falls back to the unpartitioned shape::

    gs://<bucket>/<sha2>/<run_id>/manifest.json
    gs://<bucket>/<sha2>/<run_id>/artifacts/<name>

The ``google.cloud.storage`` client is **lazy-imported inside __init__** so
the module is cheap to import even when the ``[gcs]`` extra isn't installed.
A clear ``RuntimeError`` is raised if construction is attempted without the
extra — the factory in ``store.py`` only reaches this code when the operator
explicitly opted into ``UTEKI_STORAGE_BACKEND=gcs``.

Cross-user isolation matches the local backend: a read using a wrong
``user_id`` simply addresses a different blob path that doesn't exist →
``FileNotFoundError`` → the API maps to 404.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from typing import Any

from uteki_api.artifacts.models import Artifact, ArtifactKind, ArtifactRole, content_type_for
from uteki_api.artifacts.store import ArtifactStore, _strip_preamble, _validate_name

logger = logging.getLogger(__name__)

_USER_ID_RE = re.compile(r"^[A-Za-z0-9._@+-]+$")


class GCSArtifactStore(ArtifactStore):
    """Google Cloud Storage backend for :class:`ArtifactStore`.

    Args:
        bucket_name: GCS bucket the store operates on. Required.
        credentials_path: Optional path to a service-account JSON. When None,
            falls back to Application Default Credentials (Cloud Run, gcloud
            auth application-default login, GCE/GKE metadata server, etc.).
        client: Optional pre-built ``google.cloud.storage.Client`` — used by
            tests to inject a mock; production callers should not pass this.
    """

    def __init__(
        self,
        bucket_name: str,
        *,
        credentials_path: str | None = None,
        client: Any | None = None,
    ) -> None:
        if not bucket_name:
            raise ValueError("GCSArtifactStore requires a bucket_name")

        if client is None:
            try:
                from google.cloud import storage as gcs_storage  # noqa: PLC0415
            except ImportError as exc:  # pragma: no cover — depends on env
                raise RuntimeError(
                    "GCSArtifactStore requires the [gcs] extra. "
                    "Install with: `uv sync --extra gcs` "
                    "(or `pip install uteki-api[gcs]`)."
                ) from exc

            if credentials_path:
                self._client = gcs_storage.Client.from_service_account_json(credentials_path)
            else:
                # ADC: works in Cloud Run via the attached SA; works locally
                # via `gcloud auth application-default login`.
                self._client = gcs_storage.Client()
        else:
            self._client = client

        self._bucket_name = bucket_name
        self._bucket = self._client.bucket(bucket_name)

    # ── path helpers ────────────────────────────────────────────────────

    def _run_prefix(self, run_id: str, user_id: str | None = None) -> str:
        if not run_id or "/" in run_id or "\\" in run_id:
            raise ValueError(f"invalid run_id: {run_id!r}")
        if user_id is not None and (
            not user_id or user_id in (".", "..") or not _USER_ID_RE.fullmatch(user_id)
        ):
            raise ValueError(f"invalid user_id: {user_id!r}")
        shard = run_id[:2] if len(run_id) >= 2 else "_"
        if user_id:
            return f"users/{user_id}/runs/{shard}/{run_id}"
        return f"{shard}/{run_id}"

    def _artifact_key(self, run_id: str, name: str, user_id: str | None = None) -> str:
        _validate_name(name)
        return f"{self._run_prefix(run_id, user_id)}/artifacts/{name}"

    def _manifest_key(self, run_id: str, user_id: str | None = None) -> str:
        return f"{self._run_prefix(run_id, user_id)}/manifest.json"

    # ── manifest helpers ────────────────────────────────────────────────

    def _read_manifest(self, run_id: str, user_id: str | None = None) -> list[dict]:
        blob = self._bucket.blob(self._manifest_key(run_id, user_id))
        if not blob.exists():
            return []
        try:
            raw = blob.download_as_text()
            data = json.loads(raw)
        except (json.JSONDecodeError, Exception):  # noqa: BLE001 — defensive
            return []
        return data if isinstance(data, list) else []

    def _write_manifest(
        self, run_id: str, items: list[dict], user_id: str | None = None
    ) -> None:
        blob = self._bucket.blob(self._manifest_key(run_id, user_id))
        payload = json.dumps(items, ensure_ascii=False, indent=2)
        # GCS object writes are atomic per upload — no need for .tmp+rename
        # dance the local backend uses against a partial-write crash window.
        blob.upload_from_string(payload, content_type="application/json; charset=utf-8")

    def _upsert_manifest(
        self, run_id: str, artifact: Artifact, user_id: str | None = None
    ) -> None:
        items = self._read_manifest(run_id, user_id)
        items = [i for i in items if i.get("name") != artifact.name]
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
        # Same preamble strip as the local backend — see store.py for rationale.
        if kind == "markdown" and isinstance(content, str):
            stripped, dropped_lines, dropped_bytes = _strip_preamble(content)
            if dropped_bytes > 0:
                logger.info(
                    "stripped %d-line / %d-byte preamble from %s in run %s",
                    dropped_lines, dropped_bytes, name, run_id,
                )
                content = stripped

        body = content.encode("utf-8") if isinstance(content, str) else content
        key = self._artifact_key(run_id, name, user_id)
        blob = self._bucket.blob(key)
        # Single PUT — GCS guarantees the object becomes visible atomically
        # at the end of the upload, no temp+rename needed.
        blob.upload_from_string(body, content_type=content_type_for(kind))

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
        key = self._artifact_key(run_id, name, user_id)
        blob = self._bucket.blob(key)
        if not blob.exists():
            # Same shape (and same 404 mapping) as the local backend. A
            # cross-user read lands here too: it addresses a path under
            # the wrong user's prefix, which simply doesn't exist.
            raise FileNotFoundError(f"artifact not found: {run_id}/{name}")
        body = blob.download_as_bytes()
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
            key = self._artifact_key(run_id, name, user_id)
        except ValueError:
            return False
        return self._bucket.blob(key).exists()

    async def delete_run(self, run_id: str, user_id: str | None = None) -> None:
        prefix = f"{self._run_prefix(run_id, user_id)}/"
        for blob in self._bucket.list_blobs(prefix=prefix):
            blob.delete()
