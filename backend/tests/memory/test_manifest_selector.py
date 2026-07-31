"""Tests for the cross-layer ManifestSelector."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from magi.memory.hybrid_retrieval import manifest_selector as manifest_selector_module
from magi.memory.hybrid_retrieval.manifest_candidates import (
    apply_manifest_selection,
    build_manifest_candidates,
    truncate_manifest_text,
)
from magi.memory.hybrid_retrieval.manifest_selector import ManifestSelector
from magi.memory.hybrid_retrieval.models import RetrievalConfig, RetrievalPayload


def _make_payload(**kwargs: list) -> RetrievalPayload:
    return RetrievalPayload(
        l1_events=kwargs.get("l1_events", []),
        l2_entity_cards=kwargs.get("l2_entity_cards", []),
        l3_reflections=kwargs.get("l3_reflections", []),
        l4_procedures=kwargs.get("l4_procedures", []),
    )


def _sample_payload() -> RetrievalPayload:
    return _make_payload(
        l1_events=[
            {"event_id": "e1", "content": "Had dinner at Sushi place", "timestamp": 1700000000},
            {"event_id": "e2", "content": "Went to the gym", "timestamp": 1700100000},
            {
                "event_id": "e3",
                "content": "Bought groceries at Trader Joe",
                "timestamp": 1700200000,
            },
        ],
        l2_entity_cards=[
            {
                "entity_id": "ent1",
                "name": "Alice",
                "entity_type": "person",
                "attributes": {"role": "friend"},
            },
        ],
        l3_reflections=[
            {"summary_id": "s1", "content": "User exercises regularly", "period": "2024-W01"},
        ],
        l4_procedures=[
            {"skill_id": "sk1", "optimized_prompt": "Search web for restaurant reviews"},
        ],
    )


# ---------------------------------------------------------------------------
# Config / construction
# ---------------------------------------------------------------------------


def test_manifest_selector_default_config():
    config = RetrievalConfig()
    assert config.manifest_selector_enabled is False
    assert config.manifest_selector_top_k == 20
    assert config.manifest_selector_max_output == 10


# ---------------------------------------------------------------------------
# _build_candidate_list
# ---------------------------------------------------------------------------


def test_build_candidate_list_covers_all_layers():
    payload = _sample_payload()
    manifest = build_manifest_candidates(payload, max_chars=400)
    candidates = manifest.candidates
    index_map = manifest.index_map
    assert len(candidates) == 6  # 3 L1 + 1 L2 + 1 L3 + 1 L4
    assert len(index_map) == 6
    layers = [c[0] for c in candidates]
    assert layers == ["L1", "L1", "L1", "L2", "L3", "L4"]
    fields = [m[0] for m in index_map]
    assert fields == [
        "l1_events",
        "l1_events",
        "l1_events",
        "l2_entity_cards",
        "l3_reflections",
        "l4_procedures",
    ]


def test_build_candidate_list_empty_payload():
    payload = _make_payload()
    manifest = build_manifest_candidates(payload, max_chars=400)
    assert manifest.candidates == []
    assert manifest.index_map == []


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


def test_parse_response_valid_json():
    selected = ManifestSelector._parse_response('{"selected": [2, 0, 4]}', 5)
    assert selected == [2, 0, 4]


def test_parse_response_with_response_object():
    resp = SimpleNamespace(content='{"selected": [1, 3]}')
    selected = ManifestSelector._parse_response(resp, 5)
    assert selected == [1, 3]


def test_parse_response_deduplicates():
    selected = ManifestSelector._parse_response('{"selected": [1, 1, 2]}', 5)
    assert selected == [1, 2]


def test_parse_response_filters_out_of_range():
    selected = ManifestSelector._parse_response('{"selected": [0, 99, -1, 2]}', 5)
    assert selected == [0, 2]


def test_parse_response_invalid_json_returns_all():
    selected = ManifestSelector._parse_response("not json", 3)
    assert selected == [0, 1, 2]


def test_invalid_response_log_omits_content_when_full_logging_is_disabled(
    monkeypatch,
    caplog,
):
    monkeypatch.setattr(
        manifest_selector_module,
        "full_content_logging_enabled",
        lambda: False,
    )

    with caplog.at_level("WARNING", logger=manifest_selector_module.logger.name):
        selected = ManifestSelector._parse_response(
            "MANIFEST-CONTENT-CANARY",
            3,
        )

    assert selected == [0, 1, 2]
    assert "MANIFEST-CONTENT-CANARY" not in caplog.text
    assert "content omitted" in caplog.text


def test_parse_response_missing_selected_key_returns_all():
    selected = ManifestSelector._parse_response('{"indices": [1]}', 4)
    assert selected == [0, 1, 2, 3]


def test_parse_response_empty_selected_returns_all():
    selected = ManifestSelector._parse_response('{"selected": []}', 3)
    assert selected == [0, 1, 2]


# ---------------------------------------------------------------------------
# _apply_selection
# ---------------------------------------------------------------------------


def test_apply_selection_reorders_and_prunes():
    payload = _sample_payload()
    index_map = [
        ("l1_events", 0),
        ("l1_events", 1),
        ("l1_events", 2),
        ("l2_entity_cards", 0),
        ("l3_reflections", 0),
        ("l4_procedures", 0),
    ]
    # Select only index 2 (L1 event #2), 3 (L2 card #0), 5 (L4 proc #0)
    selected = [2, 3, 5]
    result = apply_manifest_selection(payload, selected, index_map)
    assert len(result.l1_events) == 1
    assert result.l1_events[0]["event_id"] == "e3"
    assert len(result.l2_entity_cards) == 1
    assert result.l2_entity_cards[0]["entity_id"] == "ent1"
    assert result.l3_reflections == []  # not selected
    assert len(result.l4_procedures) == 1


def test_apply_selection_preserves_order():
    payload = _sample_payload()
    index_map = [
        ("l1_events", 0),
        ("l1_events", 1),
        ("l1_events", 2),
        ("l2_entity_cards", 0),
        ("l3_reflections", 0),
        ("l4_procedures", 0),
    ]
    # Select L1 events in reverse order: index 2, then 0
    selected = [2, 0]
    result = apply_manifest_selection(payload, selected, index_map)
    assert len(result.l1_events) == 2
    assert result.l1_events[0]["event_id"] == "e3"  # index 2 first
    assert result.l1_events[1]["event_id"] == "e1"  # index 0 second


# ---------------------------------------------------------------------------
# select() end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_calls_llm_and_prunes():
    config = RetrievalConfig(
        manifest_selector_enabled=True,
        manifest_selector_top_k=10,
        manifest_selector_max_output=2,
    )
    selector = ManifestSelector(config)
    payload = _sample_payload()

    bridge = SimpleNamespace(
        chat=AsyncMock(return_value=SimpleNamespace(content='{"selected": [0, 4]}')),
    )
    result = await selector.select(payload, query="Where did I eat?", llm_bridge=bridge)
    bridge.chat.assert_awaited_once()
    assert result.trace["manifest_selector"] == "applied"
    assert result.trace["manifest_selector_input_count"] == 6
    assert result.trace["manifest_selector_output_count"] == 2
    # Index 0 → L1 events[0], Index 4 → L3 reflections[0]
    assert len(result.l1_events) == 1
    assert result.l1_events[0]["event_id"] == "e1"
    assert len(result.l3_reflections) == 1
    assert result.l2_entity_cards == []
    assert result.l4_procedures == []


@pytest.mark.asyncio
async def test_select_skips_when_no_bridge():
    config = RetrievalConfig(manifest_selector_enabled=True)
    selector = ManifestSelector(config)
    payload = _sample_payload()
    result = await selector.select(payload, query="test", llm_bridge=None)
    assert result.trace["manifest_selector"] == "skipped_no_bridge"
    assert len(result.l1_events) == 3  # unchanged


@pytest.mark.asyncio
async def test_select_skips_empty_payload():
    config = RetrievalConfig(manifest_selector_enabled=True)
    selector = ManifestSelector(config)
    payload = _make_payload()
    bridge = SimpleNamespace(chat=AsyncMock())
    result = await selector.select(payload, query="test", llm_bridge=bridge)
    assert result.trace["manifest_selector"] == "skipped_empty"
    bridge.chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_select_falls_back_on_llm_error():
    config = RetrievalConfig(manifest_selector_enabled=True)
    selector = ManifestSelector(config)
    payload = _sample_payload()
    original_count = len(payload.l1_events)
    bridge = SimpleNamespace(
        chat=AsyncMock(side_effect=RuntimeError("LLM timeout")),
    )
    result = await selector.select(payload, query="test", llm_bridge=bridge)
    assert result.trace["manifest_selector"] == "error_fallback"
    assert len(result.l1_events) == original_count  # unchanged


@pytest.mark.asyncio
async def test_select_falls_back_on_invalid_json():
    config = RetrievalConfig(manifest_selector_enabled=True)
    selector = ManifestSelector(config)
    payload = _sample_payload()
    bridge = SimpleNamespace(
        chat=AsyncMock(return_value=SimpleNamespace(content="not json at all")),
    )
    result = await selector.select(payload, query="test", llm_bridge=bridge)
    # Invalid JSON → parse returns all indices → payload unchanged
    assert result.trace["manifest_selector"] == "applied"
    assert len(result.l1_events) == 3


# ---------------------------------------------------------------------------
# _truncate helper
# ---------------------------------------------------------------------------


def test_truncate_short():
    assert truncate_manifest_text("hello", 100) == "hello"


def test_truncate_long():
    assert truncate_manifest_text("a" * 50, 20) == "a" * 17 + "..."


def test_truncate_exact():
    assert truncate_manifest_text("abcde", 5) == "abcde"
