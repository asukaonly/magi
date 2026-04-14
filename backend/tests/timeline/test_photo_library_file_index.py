"""Tests for the file index cache module."""
from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

# Load file_index module from plugin directory
_module_path = Path(__file__).resolve().parents[3] / "plugins" / "photo-library" / "file_index.py"
_spec = importlib.util.spec_from_file_location(
    "photo_library_file_index",
    _module_path,
    submodule_search_locations=[str(_module_path.parent)],
)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)

FileIndexCache = _mod.FileIndexCache


class TestFileIndexCache:
    """Tests for SQLite-backed file metadata cache."""

    def test_get_returns_none_for_missing_entry(self, tmp_path: Path):
        cache = FileIndexCache(tmp_path)
        assert cache.get("/nonexistent.jpg", 1000.0, 500) is None
        cache.close()

    def test_put_and_get_roundtrip(self, tmp_path: Path):
        cache = FileIndexCache(tmp_path)
        exif = {"camera_make": "Canon", "iso": "100"}
        cache.put("/photos/a.jpg", 1000.0, 500, "abc123", exif, time.time())
        result = cache.get("/photos/a.jpg", 1000.0, 500)
        assert result == exif
        cache.close()

    def test_get_returns_none_when_mtime_differs(self, tmp_path: Path):
        cache = FileIndexCache(tmp_path)
        exif = {"camera_make": "Canon"}
        cache.put("/photos/a.jpg", 1000.0, 500, "abc123", exif, time.time())
        # Same path, different mtime
        assert cache.get("/photos/a.jpg", 2000.0, 500) is None
        cache.close()

    def test_get_returns_none_when_size_differs(self, tmp_path: Path):
        cache = FileIndexCache(tmp_path)
        exif = {"camera_make": "Canon"}
        cache.put("/photos/a.jpg", 1000.0, 500, "abc123", exif, time.time())
        # Same path and mtime, different size
        assert cache.get("/photos/a.jpg", 1000.0, 600) is None
        cache.close()

    def test_put_updates_existing_entry(self, tmp_path: Path):
        cache = FileIndexCache(tmp_path)
        cache.put("/photos/a.jpg", 1000.0, 500, "abc123", {"iso": "100"}, time.time())
        cache.put("/photos/a.jpg", 2000.0, 510, "def456", {"iso": "200"}, time.time())
        # Old entry no longer matches
        assert cache.get("/photos/a.jpg", 1000.0, 500) is None
        # New entry matches
        assert cache.get("/photos/a.jpg", 2000.0, 510) == {"iso": "200"}
        cache.close()

    def test_put_batch(self, tmp_path: Path):
        cache = FileIndexCache(tmp_path)
        now = time.time()
        entries = [
            ("/a.jpg", 1000.0, 100, "h1", {"make": "Canon"}, now),
            ("/b.jpg", 2000.0, 200, "h2", {"make": "Nikon"}, now),
            ("/c.jpg", 3000.0, 300, "h3", {"make": "Sony"}, now),
        ]
        cache.put_batch(entries)
        assert cache.get("/a.jpg", 1000.0, 100) == {"make": "Canon"}
        assert cache.get("/b.jpg", 2000.0, 200) == {"make": "Nikon"}
        assert cache.get("/c.jpg", 3000.0, 300) == {"make": "Sony"}
        cache.close()

    def test_put_batch_empty(self, tmp_path: Path):
        cache = FileIndexCache(tmp_path)
        cache.put_batch([])  # should not error
        cache.close()

    def test_prune_removes_old_entries(self, tmp_path: Path):
        cache = FileIndexCache(tmp_path)
        old_time = 1000.0
        new_time = 9000.0
        cache.put("/old.jpg", 100.0, 50, "h1", {}, old_time)
        cache.put("/new.jpg", 200.0, 60, "h2", {}, new_time)
        removed = cache.prune(older_than=5000.0)
        assert removed == 1
        assert cache.get("/old.jpg", 100.0, 50) is None
        assert cache.get("/new.jpg", 200.0, 60) == {}
        cache.close()

    def test_graceful_degradation_on_bad_path(self):
        import sys
        if sys.platform == "win32":
            # Windows reserved device names can't be used as directories
            bad = Path("NUL") / "subdir" / "cache"
        else:
            bad = Path("/nonexistent/deep/path/cache")
        cache = FileIndexCache(bad)
        # get should return None, not raise
        assert cache.get("/x.jpg", 1.0, 1) is None
        # put should not raise
        cache.put("/x.jpg", 1.0, 1, "h", {}, 1.0)
        # put_batch should not raise
        cache.put_batch([("/y.jpg", 1.0, 1, "h", {}, 1.0)])
        cache.close()

    def test_close_and_reconnect(self, tmp_path: Path):
        cache = FileIndexCache(tmp_path)
        cache.put("/a.jpg", 1.0, 10, "h", {"k": "v"}, time.time())
        cache.close()
        # After close, a new connection is established automatically
        assert cache.get("/a.jpg", 1.0, 10) == {"k": "v"}
        cache.close()
