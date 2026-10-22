"""ManualEntryAssetStore — content-addressed storage tests (no network)."""

from __future__ import annotations

import hashlib

import pytest

from magi.memory.manual_entries.asset_store import (
    ManualEntryAssetStore,
)
from magi.memory.manual_entries.asset_types import ASSET_SCHEME


def test_store_bytes_dedupes_identical_content(tmp_path):
    store = ManualEntryAssetStore(media_root=tmp_path)
    data = b"identical bytes"
    ref_a = store.store_bytes(data, content_type="image/jpeg")
    ref_b = store.store_bytes(data, content_type="image/jpeg")
    assert ref_a == ref_b
    # And only a single file on disk
    files = [p for p in (tmp_path / "manual_entries").rglob("*") if p.is_file()]
    assert len(files) == 1


def test_store_bytes_rejects_unsupported_content_type(tmp_path):
    store = ManualEntryAssetStore(media_root=tmp_path)
    with pytest.raises(ValueError):
        store.store_bytes(b"x", content_type="application/octet-stream")


@pytest.mark.parametrize("mime,extension", [("image/jpeg", "jpg"), ("image/png", "png")])
def test_asset_reference_roundtrips_exact_bytes_mime_and_owned_path(tmp_path, mime, extension):
    store = ManualEntryAssetStore(media_root=tmp_path)
    data = b"stored image fixture bytes"
    digest = hashlib.sha256(data).hexdigest()
    reference = store.store_bytes(data, content_type=mime)
    assert reference == f"{ASSET_SCHEME}://{digest}.{extension}"
    assert store.resolve(reference) == (data, mime)
    assert store.has_asset(reference) is True
    path = tmp_path / "manual_entries" / digest[:2] / f"{digest}.{extension}"
    assert path.read_bytes() == data


def test_resolve_missing_file_returns_none(tmp_path):
    """A ref whose backing file got deleted should return None, not raise."""
    store = ManualEntryAssetStore(media_root=tmp_path)
    fake_ref = f"{ASSET_SCHEME}://" + "a" * 64 + ".png"
    assert store.resolve(fake_ref) is None


@pytest.mark.parametrize(
    "asset_ref",
    [
        "photo-library://x.jpg",
        "not-a-ref",
        "",
        f"{ASSET_SCHEME}://no-extension",
        f"{ASSET_SCHEME}://x.bmp",
        f"{ASSET_SCHEME}:///tmp/private.jpg",
        f"{ASSET_SCHEME}://../../private.png",
        f"{ASSET_SCHEME}://{'A'*64}.jpg",
        f"{ASSET_SCHEME}://{'a'*63}.jpg",
        f"{ASSET_SCHEME}://{'a'*64}.jpeg",
    ],
)
def test_invalid_asset_refs_are_rejected_before_filesystem_resolution(
    tmp_path, monkeypatch, asset_ref
):
    from unittest.mock import Mock

    store = ManualEntryAssetStore(media_root=tmp_path)
    data = b"CANARY-ASSET"
    valid = store.store_bytes(data, content_type="image/jpeg")
    digest = hashlib.sha256(data).hexdigest()
    path = tmp_path / "manual_entries" / digest[:2] / f"{digest}.jpg"
    resolve_path = Mock(return_value=path)
    monkeypatch.setattr(store, "_path_for", resolve_path)
    assert store.resolve(valid) == (data, "image/jpeg")
    resolve_path.assert_called_once_with(digest, "jpg")
    resolve_path.reset_mock()
    assert store.resolve(asset_ref) is None
    assert store.has_asset(asset_ref) is False
    resolve_path.assert_not_called()


def test_resolve_rejects_a_path_outside_the_owned_root(tmp_path, monkeypatch):
    store = ManualEntryAssetStore(media_root=tmp_path / "media")
    asset_ref = f"{ASSET_SCHEME}://{'a' * 64}.jpg"
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"private")
    monkeypatch.setattr(store, "_path_for", lambda _digest, _ext: outside)

    assert store.resolve(asset_ref) is None
    assert store.has_asset(asset_ref) is False


def test_has_asset_requires_a_canonical_stored_ref(tmp_path):
    store = ManualEntryAssetStore(media_root=tmp_path)
    stored_ref = store.store_bytes(b"stored", content_type="image/webp")

    assert store.has_asset(stored_ref) is True
    assert store.has_asset(f"{ASSET_SCHEME}://{'f' * 64}.webp") is False


def test_corrupt_and_hardlinked_asset_bytes_are_not_exposed(tmp_path):
    import os
    store = ManualEntryAssetStore(media_root=tmp_path)
    reference = store.store_bytes(b"original", content_type="image/png")
    digest = hashlib.sha256(b"original").hexdigest()
    path = tmp_path / "manual_entries" / digest[:2] / f"{digest}.png"
    path.write_bytes(b"tampered")
    assert not store.has_asset(reference)
    assert store.resolve(reference) is None
    assert store.store_bytes(b"original", content_type="image/png") == reference
    assert store.resolve(reference) == (b"original", "image/png")
    os.link(path, tmp_path / "link")
    assert store.resolve(reference) is None


def test_concurrent_identical_uploads_share_one_complete_object(tmp_path):
    from concurrent.futures import ThreadPoolExecutor
    store = ManualEntryAssetStore(media_root=tmp_path)
    content = b"concurrent" * 500
    with ThreadPoolExecutor(max_workers=6) as pool:
        references = list(pool.map(lambda _: store.store_bytes(content, content_type="image/png"), range(20)))
    assert len(set(references)) == 1
    assert store.resolve(references[0]) == (content, "image/png")
    assert len(list((tmp_path / "manual_entries").rglob("*.png"))) == 1
    assert not list((tmp_path / "manual_entries").rglob("*.tmp"))


@pytest.mark.asyncio
async def test_storage_cancellation_waits_for_mutation_completion():
    import asyncio
    import threading
    from magi.memory.manual_entries.asset_ports import asset_io
    entered, release, finished = threading.Event(), threading.Event(), threading.Event()
    def blocking_write():
        entered.set()
        assert release.wait(3)
        finished.set()
    task = asyncio.create_task(asset_io(blocking_write))
    assert await asyncio.to_thread(entered.wait, 2)
    task.cancel()
    await asyncio.sleep(0)
    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()


@pytest.mark.asyncio
async def test_timeline_consumes_pathless_asset_repository():
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from magi.timeline.service import TimelineService
    class MemoryImages:
        def resolve(self, reference):
            return (b"image", "image/png") if reference == "manual-entry-asset://image" else None
    references = SimpleNamespace(is_visible_reference=AsyncMock(return_value=True))
    timeline = TimelineService(SimpleNamespace(asset_references=references), manual_entry_asset_store=MemoryImages())
    assert await timeline.serve_asset(asset_ref="manual-entry-asset://image") == (b"image", "image/png")
    references.is_visible_reference.return_value = False
    assert await timeline.serve_asset(asset_ref="manual-entry-asset://image") is None
