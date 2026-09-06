"""resolve_llm_extraction: combined P1 flag + P2 frequency-gate decision (RFC #56 P2)."""
from __future__ import annotations

import asyncio

from magi.memory.l2.pipeline.extraction import resolve_llm_extraction
from magi.memory.l2.promotion_counter import L2PromotionCounter


class _Ev:
    def __init__(self, metadata_json, source="chrome", event_id="e"):
        self.metadata_json = metadata_json
        self.source = source
        self.event_id = event_id


def _counter(tmp_path):
    return L2PromotionCounter(str(tmp_path / "p.db"))  # self-ensures schema (no initialize needed)


def test_no_policy_uses_p1_flag():
    assert asyncio.run(resolve_llm_extraction(_Ev({}), None)) is True
    assert asyncio.run(resolve_llm_extraction(_Ev({"allow_llm_extraction": False}), None)) is False


def test_frequency_gate_promotes_at_threshold(tmp_path):
    c = _counter(tmp_path)
    md = {"promotion_threshold": 2, "promotion_key": "github.com"}
    assert asyncio.run(resolve_llm_extraction(_Ev(md, event_id="e1"), c)) is False  # count 1 < 2
    assert asyncio.run(resolve_llm_extraction(_Ev(md, event_id="e2"), c)) is True   # count 2 -> promoted
    assert asyncio.run(resolve_llm_extraction(_Ev(md, event_id="e3"), c)) is True   # stays promoted


def test_explicit_optout_beats_frequency(tmp_path):
    c = _counter(tmp_path)
    md = {"allow_llm_extraction": False, "promotion_threshold": 1, "promotion_key": "x"}
    assert asyncio.run(resolve_llm_extraction(_Ev(md), c)) is False


def test_force_full_override_beats_static_optout(tmp_path):
    # RFC #56 P4 escape hatch: a structured-only source force-promotes one event.
    c = _counter(tmp_path)
    md = {"allow_llm_extraction": False, "promotion_override": "force_full"}
    assert asyncio.run(resolve_llm_extraction(_Ev(md), c)) is True


def test_force_full_override_beats_frequency_gate(tmp_path):
    c = _counter(tmp_path)
    md = {"promotion_threshold": 5, "promotion_key": "x", "promotion_override": "force_full"}
    assert asyncio.run(resolve_llm_extraction(_Ev(md), c)) is True  # below threshold, but forced


def test_force_structured_only_override_beats_promotion(tmp_path):
    c = _counter(tmp_path)
    md = {"promotion_threshold": 1, "promotion_key": "x", "promotion_override": "force_structured_only"}
    assert asyncio.run(resolve_llm_extraction(_Ev(md), c)) is False  # would promote, but vetoed


def test_unknown_override_value_falls_through_to_default(tmp_path):
    assert asyncio.run(resolve_llm_extraction(_Ev({"promotion_override": "bogus"}), None)) is True


def test_threshold_without_key_or_counter_allows(tmp_path):
    c = _counter(tmp_path)
    # threshold set but no per-event key -> no gate, allowed
    assert asyncio.run(resolve_llm_extraction(_Ev({"promotion_threshold": 5}), c)) is True
    # counter missing -> no gate, allowed
    assert asyncio.run(
        resolve_llm_extraction(_Ev({"promotion_threshold": 5, "promotion_key": "k"}), None)
    ) is True
