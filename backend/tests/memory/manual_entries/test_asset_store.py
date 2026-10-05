"""ManualEntryAssetStore — content-addressed storage tests (no network)."""

from __future__ import annotations

import hashlib

import pytest

from magi.memory.manual_entries.asset_store import (
    ManualEntryAssetStore,
    ASSET_SCHEME,
)


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
