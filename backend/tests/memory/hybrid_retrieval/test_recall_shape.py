from magi.memory.hybrid_retrieval.recall_shape import classify_recall_shape


def test_photo_count_query_requires_exhaustive_coverage() -> None:
    shape = classify_recall_shape("我在天空之城拍过几次照片")

    assert shape.domain_hint == "photo"
    assert shape.operation == "count"
    assert shape.desired_coverage == "exhaustive"
    assert "count" in shape.matched_cues


def test_photo_what_query_requires_exhaustive_coverage() -> None:
    shape = classify_recall_shape("我在天空之城拍过什么照片")

    assert shape.domain_hint == "photo"
    assert shape.operation == "aggregate"
    assert shape.desired_coverage == "exhaustive"


def test_photo_sample_query_stays_sampled() -> None:
    shape = classify_recall_shape("给我看看天空之城的照片")

    assert shape.domain_hint == "photo"
    assert shape.operation == "search"
    assert shape.desired_coverage == "sample"


def test_photo_existence_query_does_not_claim_totals() -> None:
    shape = classify_recall_shape("我是不是拍过天空之城的照片")

    assert shape.domain_hint == "photo"
    assert shape.operation == "existence"
    assert shape.desired_coverage == "sample"


def test_browser_count_query_requires_exhaustive_coverage() -> None:
    shape = classify_recall_shape("example.com 浏览过几次")

    assert shape.domain_hint == "browser"
    assert shape.operation == "count"
    assert shape.desired_coverage == "exhaustive"


def test_music_count_query_requires_exhaustive_coverage() -> None:
    shape = classify_recall_shape("Artist A 听过几次")

    assert shape.domain_hint == "music"
    assert shape.operation == "count"
    assert shape.desired_coverage == "exhaustive"
