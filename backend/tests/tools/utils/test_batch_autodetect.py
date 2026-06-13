from magi.tools.utils.batch_autodetect import suggest_batch


def test_no_hint_below_threshold():
    assert suggest_batch([f"/m/{i}.mkv" for i in range(10)], threshold=30) is None


def test_hint_above_threshold_homogeneous():
    hint = suggest_batch([f"/m/{i}.mkv" for i in range(50)], threshold=30)
    assert hint is not None
    assert "batch_create" in hint
    assert "50" in hint
    assert ".mkv" in hint


def test_no_hint_when_heterogeneous_below_threshold():
    # 40 files spread across 4 exts → largest group (10) < threshold
    paths = (
        [f"/m/{i}.a" for i in range(10)]
        + [f"/m/{i}.b" for i in range(10)]
        + [f"/m/{i}.c" for i in range(10)]
        + [f"/m/{i}.d" for i in range(10)]
    )
    assert suggest_batch(paths, threshold=30) is None


def test_hint_counts_largest_homogeneous_group():
    paths = [f"/m/{i}.mkv" for i in range(35)] + [f"/m/{i}.txt" for i in range(5)]
    hint = suggest_batch(paths, threshold=30)
    assert hint is not None
    assert "35" in hint
    assert ".mkv" in hint


def test_no_hint_when_no_extensions():
    assert suggest_batch([f"/m/dir{i}" for i in range(50)], threshold=30) is None
