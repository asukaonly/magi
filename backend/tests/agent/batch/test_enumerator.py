import collections.abc

import pytest

from magi.agent.batch.enumerator import enumerate_seed


def test_enumerate_fs_matches_patterns_recursive(tmp_path):
    (tmp_path / "a.mkv").write_text("")
    (tmp_path / "b.mp4").write_text("")
    (tmp_path / "c.txt").write_text("")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "d.mkv").write_text("")

    items = enumerate_seed(
        {"source": "fs", "root": str(tmp_path), "patterns": ["*.mkv", "*.mp4"], "recursive": True}
    )
    paths = sorted(i["path"] for i in items)
    assert paths == sorted(
        [str(tmp_path / "a.mkv"), str(tmp_path / "b.mp4"), str(sub / "d.mkv")]
    )


def test_enumerate_fs_non_recursive_skips_subdirs(tmp_path):
    (tmp_path / "a.mkv").write_text("")
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "d.mkv").write_text("")

    items = enumerate_seed(
        {"source": "fs", "root": str(tmp_path), "patterns": ["*.mkv"], "recursive": False}
    )
    assert [i["path"] for i in items] == [str(tmp_path / "a.mkv")]


def test_enumerate_fs_missing_root_returns_empty(tmp_path):
    items = enumerate_seed(
        {"source": "fs", "root": str(tmp_path / "nope"), "patterns": ["*"], "recursive": True}
    )
    assert list(items) == []


def test_enumerate_unsupported_source_raises():
    with pytest.raises(ValueError):
        enumerate_seed({"source": "prompt"})


def test_enumerate_seed_is_lazy_iterator(tmp_path):
    (tmp_path / "a.mkv").touch()
    (tmp_path / "b.txt").touch()
    result = enumerate_seed({"source": "fs", "root": str(tmp_path), "patterns": ["*.mkv"]})
    # Must be a lazy iterator, NOT a materialized list.
    assert isinstance(result, collections.abc.Iterator)
    assert not isinstance(result, list)
    assert list(result) == [{"path": str(tmp_path / "a.mkv")}]


def test_enumerate_seed_bad_source_raises_eagerly():
    # source validation must happen on call, not on first iteration.
    with pytest.raises(ValueError):
        enumerate_seed({"source": "ftp"})


def test_enumerate_seed_missing_root_is_empty():
    assert list(enumerate_seed({"source": "fs", "root": "/no/such/dir"})) == []
