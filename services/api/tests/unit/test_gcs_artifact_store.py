"""Unit tests for GCSArtifactStore — exercised with a mocked GCS Client.

These tests don't hit real GCS. They verify:

1. Path scheme matches the local backend modulo the ``data/runs/`` prefix.
2. Cross-user reads raise ``FileNotFoundError`` (the ABC contract that
   ``api/artifacts.py`` maps to 404).
3. The manifest blob is upserted on every write (last-write-wins by name).
4. ``read()`` returns ``(Artifact, bytes)`` reassembled from the manifest entry.
5. ``exists()`` is False for unknown names and True after a write.
6. Constructing without the bucket name raises immediately.

If ``google-cloud-storage`` isn't installed (the [gcs] extra was skipped),
the whole module is skipped — no spurious red.
"""

from __future__ import annotations

import json

import pytest

try:
    from google.cloud import storage as _gcs_storage  # noqa: F401

    GCS_AVAILABLE = True
except ImportError:  # pragma: no cover — depends on whether [gcs] is installed
    GCS_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not GCS_AVAILABLE, reason="google-cloud-storage not installed (install [gcs] extra)"
)


class _FakeBucket:
    def __init__(self, name: str) -> None:
        self.name = name
        self._store: dict[str, bytes] = {}

    def blob(self, name: str):
        return _FakeBlob(self, name)


class _FakeBlob:
    """In-memory stand-in for ``google.cloud.storage.Blob``.

    Mirrors only the surface ``GCSArtifactStore`` actually calls:
    ``upload_from_string``, ``download_as_text``, ``download_as_bytes``,
    ``exists``.
    """

    def __init__(self, bucket: _FakeBucket, name: str) -> None:
        self._bucket = bucket
        self.name = name

    def upload_from_string(self, data, content_type: str | None = None) -> None:  # noqa: ARG002
        if isinstance(data, str):
            data = data.encode("utf-8")
        self._bucket._store[self.name] = data

    def download_as_text(self) -> str:
        return self._bucket._store[self.name].decode("utf-8")

    def download_as_bytes(self) -> bytes:
        return self._bucket._store[self.name]

    def exists(self) -> bool:
        return self.name in self._bucket._store


class _FakeClient:
    def __init__(self) -> None:
        self._buckets: dict[str, _FakeBucket] = {}

    def bucket(self, name: str) -> _FakeBucket:
        if name not in self._buckets:
            self._buckets[name] = _FakeBucket(name)
        return self._buckets[name]


@pytest.fixture
def store():
    from uteki_api.artifacts.gcs_store import GCSArtifactStore

    client = _FakeClient()
    return GCSArtifactStore(bucket_name="uteki-test", client=client)


def test_construct_without_bucket_raises():
    from uteki_api.artifacts.gcs_store import GCSArtifactStore

    with pytest.raises(ValueError, match="bucket_name"):
        GCSArtifactStore(bucket_name="", client=_FakeClient())


def test_path_scheme_matches_partition_layout(store):
    # With user_id: users/<uid>/runs/<sha2>/<run_id>/...
    assert store._artifact_key("abcdef123", "plan.md", user_id="alice") == (
        "users/alice/runs/ab/abcdef123/artifacts/plan.md"
    )
    assert store._manifest_key("abcdef123", user_id="alice") == (
        "users/alice/runs/ab/abcdef123/manifest.json"
    )
    # Without user_id (system / legacy): <sha2>/<run_id>/...
    assert store._artifact_key("abcdef123", "plan.md") == "ab/abcdef123/artifacts/plan.md"
    assert store._manifest_key("abcdef123") == "ab/abcdef123/manifest.json"


async def test_write_then_read_roundtrip(store):
    art = await store.write(
        "run-12345",
        "report.md",
        "# Title\nbody",
        kind="markdown",
        written_by="planner",
        user_id="alice",
        role="primary",
    )
    assert art.name == "report.md"
    assert art.size_bytes == len("# Title\nbody")
    assert art.kind == "markdown"

    meta, body = await store.read("run-12345", "report.md", user_id="alice")
    assert body == b"# Title\nbody"
    assert meta.name == "report.md"
    assert meta.role == "primary"
    assert meta.sha256 == art.sha256


async def test_cross_user_read_raises_file_not_found(store):
    await store.write(
        "run-aaa",
        "secret.md",
        "alice-only",
        kind="markdown",
        written_by="planner",
        user_id="alice",
    )

    # bob tries to read alice's run with bob's user_id → addresses a non-existent
    # blob path under users/bob/... → FileNotFoundError → API maps to 404.
    with pytest.raises(FileNotFoundError):
        await store.read("run-aaa", "secret.md", user_id="bob")


async def test_manifest_upsert_last_write_wins(store):
    await store.write(
        "run-xyz",
        "plan.md",
        "v1",
        kind="markdown",
        written_by="planner",
        user_id="u",
    )
    await store.write(
        "run-xyz",
        "plan.md",
        "v2 (updated)",
        kind="markdown",
        written_by="planner",
        user_id="u",
    )

    items = await store.list("run-xyz", user_id="u")
    # Only one manifest entry for plan.md — the second write replaces the first.
    plan_entries = [i for i in items if i.name == "plan.md"]
    assert len(plan_entries) == 1
    # And the bytes reflect the latest write.
    _, body = await store.read("run-xyz", "plan.md", user_id="u")
    assert body == b"v2 (updated)"

    # Manifest blob itself is JSON parseable, matching the local backend shape.
    bucket = store._bucket
    manifest_blob = bucket.blob("users/u/runs/ru/run-xyz/manifest.json")
    parsed = json.loads(manifest_blob.download_as_text())
    assert isinstance(parsed, list)
    assert any(i["name"] == "plan.md" for i in parsed)


async def test_exists_reflects_writes(store):
    assert await store.exists("run-1", "x.md", user_id="u") is False

    await store.write(
        "run-1",
        "x.md",
        "hi",
        kind="markdown",
        written_by="planner",
        user_id="u",
    )
    assert await store.exists("run-1", "x.md", user_id="u") is True
    # Other user's namespace: same name, different prefix → False.
    assert await store.exists("run-1", "x.md", user_id="other") is False
    # Invalid name: graceful False instead of raising (matches local backend).
    assert await store.exists("run-1", "../escape", user_id="u") is False


async def test_markdown_preamble_strip_applies(store):
    # Same _strip_preamble behavior the local backend has — see store.py.
    art = await store.write(
        "run-2",
        "out.md",
        "我来生成报告...\n\n# Real Title\nbody",
        kind="markdown",
        written_by="researcher",
        user_id="u",
    )
    _, body = await store.read("run-2", "out.md", user_id="u")
    assert body.decode("utf-8").startswith("# Real Title")
    assert art.size_bytes == len(body)
