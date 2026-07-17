"""ManualEntryAssetStore — content-addressed storage tests (no network)."""

from __future__ import annotations

import hashlib

import pytest

from magi.memory.manual_entries.asset_store import (
    ManualEntryAssetStore,
    ASSET_SCHEME,
)


def test_store_bytes_returns_sha_keyed_ref(tmp_path):
    store = ManualEntryAssetStore(media_root=tmp_path)
    data = b"\x89PNG\r\n\x1a\n" + b"x" * 256  # any bytes — sha just needs to be deterministic
    ref = store.store_bytes(data, content_type="image/png")
    digest = hashlib.sha256(data).hexdigest()
    assert ref == f"{ASSET_SCHEME}://{digest}.png"


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


def test_resolve_roundtrip(tmp_path):
    store = ManualEntryAssetStore(media_root=tmp_path)
    data = b"hello jpg"
    ref = store.store_bytes(data, content_type="image/jpeg")
    resolved = store.resolve(ref)
    assert resolved is not None
    bytes_out, content_type = resolved
    assert bytes_out == data
    assert content_type == "image/jpeg"


def test_resolve_unknown_scheme_returns_none(tmp_path):
    store = ManualEntryAssetStore(media_root=tmp_path)
    assert store.resolve("photo-library://x.jpg") is None
    assert store.resolve("not-a-ref") is None
    assert store.resolve("") is None


def test_resolve_missing_file_returns_none(tmp_path):
    """A ref whose backing file got deleted should return None, not raise."""
    store = ManualEntryAssetStore(media_root=tmp_path)
    fake_ref = f"{ASSET_SCHEME}://" + "a" * 64 + ".png"
    assert store.resolve(fake_ref) is None


def test_resolve_malformed_ref(tmp_path):
    store = ManualEntryAssetStore(media_root=tmp_path)
    # Missing extension
    assert store.resolve(f"{ASSET_SCHEME}://no-extension") is None
    # Extension not in accepted set
    assert store.resolve(f"{ASSET_SCHEME}://x.bmp") is None


@pytest.mark.parametrize(
    "asset_ref",
    [
        f"{ASSET_SCHEME}:///tmp/private.jpg",
        f"{ASSET_SCHEME}://../../private.png",
        f"{ASSET_SCHEME}://{'A' * 64}.jpg",
        f"{ASSET_SCHEME}://{'a' * 63}.jpg",
        f"{ASSET_SCHEME}://{'a' * 64}.jpeg",
    ],
)
def test_resolve_rejects_noncanonical_or_traversing_refs(tmp_path, asset_ref):
    store = ManualEntryAssetStore(media_root=tmp_path)

    assert store.resolve(asset_ref) is None
    assert store.has_asset(asset_ref) is False


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
