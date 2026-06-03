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
    assert items == []


def test_enumerate_unsupported_source_raises():
    with pytest.raises(ValueError):
        enumerate_seed({"source": "prompt"})
