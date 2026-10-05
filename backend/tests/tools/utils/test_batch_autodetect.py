from magi.tools.utils.batch_autodetect import suggest_batch


def test_hint_above_threshold_homogeneous():
    hint = suggest_batch([f"/m/{i}.mkv" for i in range(50)], threshold=30)
    assert hint is not None
    assert "batch_create" in hint
    assert "50" in hint
    assert ".mkv" in hint


def test_batch_hint_requires_threshold_in_one_nonempty_extension_group():
    groups = [
        [f"/m/{i}.mkv" for i in range(29)],
        [f"/m/dir{i}" for i in range(50)],
        [f"/m/{i}.{ext}" for ext in ("a", "b", "c", "d") for i in range(10)],
    ]
    for paths in groups:
        assert suggest_batch(paths, threshold=30) is None


def test_hint_counts_largest_homogeneous_group():
    paths = [f"/m/{i}.mkv" for i in range(35)] + [f"/m/{i}.txt" for i in range(5)]
    hint = suggest_batch(paths, threshold=30)
    assert hint is not None
    assert "35" in hint
    assert ".mkv" in hint
