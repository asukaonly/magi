from magi.memory.l2.assertions.state_machine import RETRIEVAL_EXCLUDED_STATUSES


def test_shadow_is_excluded_from_retrieval():
    assert "shadow" in RETRIEVAL_EXCLUDED_STATUSES
