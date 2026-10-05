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


@pytest.mark.parametrize(
    "source_type",
    [
        pytest.param("prompt", id="enumerate_unsupported_source_raises"),
        pytest.param("ftp", id="enumerate_seed_bad_source_raises_eagerly"),
    ],
)
def test_enumerate_rejects_unsupported_source(source_type):
    with pytest.raises(ValueError):
        enumerate_seed({"source": source_type})


def test_enumeration_defers_filesystem_traversal_until_consumed(tmp_path, monkeypatch):
    from magi.agent.batch import enumerator

    walked = []

    def walk(root):
        walked.append(root)
        yield str(tmp_path), [], ["a.mkv", "b.txt"]

    monkeypatch.setattr(enumerator.os, "walk", walk)
    result = enumerate_seed({"source": "fs", "root": str(tmp_path), "patterns": ["*.mkv"]})
    assert walked == []
    assert next(result) == {"path": str(tmp_path / "a.mkv")}
    assert walked == [tmp_path]
    assert list(result) == []
