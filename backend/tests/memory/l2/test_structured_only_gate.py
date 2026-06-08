"""Gate that lets a source-declared structured-only event skip LLM phase1/2.

When a sensor sets ``allow_llm_extraction=False`` (carried in ``metadata_json``),
L2 still does deterministic direct-writes but must NOT call the LLM extractor.
"""

from magi.memory.l2.pipeline.extraction import event_allows_llm_extraction


class _Event:
    def __init__(self, metadata_json):
        self.metadata_json = metadata_json


def test_allows_when_flag_absent():
    assert event_allows_llm_extraction(_Event({})) is True
    assert event_allows_llm_extraction(_Event(None)) is True
    assert event_allows_llm_extraction(_Event({"timeline": {}})) is True


def test_blocks_when_flag_false():
    assert event_allows_llm_extraction(_Event({"allow_llm_extraction": False})) is False


def test_allows_when_flag_true():
    assert event_allows_llm_extraction(_Event({"allow_llm_extraction": True})) is True
