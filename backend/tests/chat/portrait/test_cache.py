import os
import stat
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from magi_plugin_sdk.fs import UnsafeManagedPathError

from magi.chat.portrait.cache import PortraitCache, clear_persisted_portrait_cache
from magi.chat.portrait.contracts import ChatPortraitPayload


def _payload(session: str, persona: str) -> ChatPortraitPayload:
    return ChatPortraitPayload(
        session_id=session,
        persona_id=persona,
        topic="t",
        generated_at=int(time.time()),
    )


def test_set_then_get_returns_payload():
    cache = PortraitCache(ttl_seconds=300, max_entries=100)
    key = ("s1", "topic_hash", "p1")
    payload = _payload("s1", "p1")
    cache.set(key, payload)
    assert cache.get(key) is payload


def test_get_expired_entry_returns_none(monkeypatch):
    now = [1_000_000.0]
    monkeypatch.setattr("magi.chat.portrait.cache.time.monotonic", lambda: now[0])
    cache = PortraitCache(ttl_seconds=300, max_entries=100)
    key = ("s1", "h", "p1")
    cache.set(key, _payload("s1", "p1"))
    now[0] += 301
    assert cache.get(key) is None


def test_invalidate_by_persona():
    cache = PortraitCache(ttl_seconds=300, max_entries=100)
    cache.set(("s1", "h", "p1"), _payload("s1", "p1"))
    cache.set(("s1", "h", "p2"), _payload("s1", "p2"))
    cache.invalidate_persona("p1")
    assert cache.get(("s1", "h", "p1")) is None
    assert cache.get(("s1", "h", "p2")) is not None


def test_lru_eviction_when_over_capacity():
    cache = PortraitCache(ttl_seconds=300, max_entries=2)
    cache.set(("s1", "h", "p1"), _payload("s1", "p1"))
    cache.set(("s2", "h", "p1"), _payload("s2", "p1"))
    # Access s1 → makes s2 the LRU
    cache.get(("s1", "h", "p1"))
    cache.set(("s3", "h", "p1"), _payload("s3", "p1"))
    assert cache.get(("s2", "h", "p1")) is None
    assert cache.get(("s1", "h", "p1")) is not None
    assert cache.get(("s3", "h", "p1")) is not None


def test_disk_persistence_roundtrip(tmp_path):
    """Entries written through one cache instance must be visible through
    a fresh instance pointed at the same file."""
    path = tmp_path / "cache.json"
    writer = PortraitCache(ttl_seconds=300, max_entries=10, persistence_path=path)
    writer.set(("s1", "h", "p1"), _payload("s1", "p1"))

    reader = PortraitCache(ttl_seconds=300, max_entries=10, persistence_path=path)
    restored = reader.get_stale(("s1", "h", "p1"))
    assert restored is not None
    assert restored.session_id == "s1"
    assert restored.persona_id == "p1"


def test_clear_removes_persisted_payload_and_crash_temp_file(tmp_path):
    path = tmp_path / "cache.json"
    cache = PortraitCache(ttl_seconds=300, max_entries=10, persistence_path=path)
    key = ("private-session", "private-hash", "p1")
    cache.set(key, _payload("private-session", "p1"))
    crash_temp = tmp_path / ".portrait-cache-orphan.json"
    crash_temp.write_text("private portrait", encoding="utf-8")

    cache.clear()

    assert cache.get_stale(key) is None
    assert not path.exists()
    assert not crash_temp.exists()


def test_clear_removes_linked_parent_without_following_it(tmp_path: Path) -> None:
    parent = tmp_path / "portrait"
    path = parent / "cache.json"
    cache = PortraitCache(ttl_seconds=300, max_entries=10, persistence_path=path)
    external = tmp_path / "external"
    external.mkdir()
    external_cache = external / "cache.json"
    external_cache.write_text("private", encoding="utf-8")
    external_temp = external / ".portrait-cache-private.json"
    external_temp.write_text("private temp", encoding="utf-8")
    try:
        parent.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("directory links are unavailable on this platform")

    cache.clear()

    assert parent.is_symlink() is False
    assert parent.exists() is False
    assert external_cache.read_text(encoding="utf-8") == "private"
    assert external_temp.read_text(encoding="utf-8") == "private temp"


def test_clear_persisted_portrait_cache_detects_reparse_parent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    parent = tmp_path / "portrait"
    path = parent / "cache.json"
    external = tmp_path / "external"
    external.mkdir()
    external_cache = external / "cache.json"
    external_cache.write_text("private", encoding="utf-8")
    try:
        parent.symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip("directory links are unavailable on this platform")

    original_lstat = os.lstat

    def reparse_lstat(candidate, *args, **kwargs):
        result = original_lstat(candidate, *args, **kwargs)
        if Path(candidate) == parent and stat.S_ISLNK(result.st_mode):
            return SimpleNamespace(
                st_mode=stat.S_IFDIR | 0o700,
                st_file_attributes=0x0400,
            )
        return result

    monkeypatch.setattr(os, "lstat", reparse_lstat)

    assert clear_persisted_portrait_cache(path) == 1
    assert parent.is_symlink() is False
    assert parent.exists() is False
    assert external_cache.read_text(encoding="utf-8") == "private"


def test_clear_rejects_linked_parent_chain_without_touching_external_files(
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    path = cache_root / "portrait" / "cache.json"
    cache = PortraitCache(ttl_seconds=300, max_entries=10, persistence_path=path)
    external_root = tmp_path / "external"
    external_parent = external_root / "portrait"
    external_parent.mkdir(parents=True)
    external_cache = external_parent / "cache.json"
    external_cache.write_text("private", encoding="utf-8")
    external_temp = external_parent / ".portrait-cache-private.json"
    external_temp.write_text("private temp", encoding="utf-8")
    try:
        cache_root.symlink_to(external_root, target_is_directory=True)
    except OSError:
        pytest.skip("directory links are unavailable on this platform")

    with pytest.raises(UnsafeManagedPathError):
        cache.clear()

    assert external_cache.read_text(encoding="utf-8") == "private"
    assert external_temp.read_text(encoding="utf-8") == "private temp"


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO unsupported")
def test_clear_persisted_portrait_cache_unlinks_special_targets_only(
    tmp_path: Path,
) -> None:
    parent = tmp_path / "portrait"
    parent.mkdir()
    external = tmp_path / "external.json"
    external.write_text("must survive", encoding="utf-8")
    path = parent / "cache.json"
    path.symlink_to(external)
    hard_link = parent / ".portrait-cache-hardlink.json"
    os.link(external, hard_link)
    fifo = parent / ".portrait-cache-fifo.json"
    os.mkfifo(fifo)

    assert clear_persisted_portrait_cache(path) == 3
    assert path.is_symlink() is False
    assert not hard_link.exists()
    assert not fifo.exists()
    assert external.read_text(encoding="utf-8") == "must survive"
