from magi.system_suggestions.throttle import SuggestionThrottle


def test_throttle_reclassifies_when_candidate_set_changes():
    th = SuggestionThrottle(reclassify_after=3)
    assert th.should_classify("s1", frozenset({"a"})) is True   # first time
    th.store("s1", frozenset({"a"}), ["P-a"])
    assert th.should_classify("s1", frozenset({"a"})) is False  # unchanged, < N
    assert th.should_classify("s1", frozenset({"b"})) is True   # changed set


def test_throttle_reclassifies_after_n_checks():
    th = SuggestionThrottle(reclassify_after=2)
    th.store("s1", frozenset({"a"}), ["P-a"])
    assert th.should_classify("s1", frozenset({"a"})) is False  # 1st skip
    assert th.should_classify("s1", frozenset({"a"})) is True   # 2nd -> >= N
    assert th.get_cached("s1") == ["P-a"]
