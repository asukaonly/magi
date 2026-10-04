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


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [False, True])
async def test_postprocessing_obeys_default_opt_out_and_selection_budgets(enabled):
    from copy import deepcopy
    from magi.memory.hybrid_retrieval.models import RetrievalQuery
    from magi.memory.hybrid_retrieval.service_postprocessing import (
        HybridRetrievalPostProcessingMixin,
    )

    config = RetrievalConfig(manifest_selector_enabled=True) if enabled else RetrievalConfig()
    payload = RetrievalPayload(
        l1_events=[{"event_id": f"e{i}", "content": f"Memory {i}"} for i in range(25)]
    )
    expected = deepcopy(payload)
    bridge = SimpleNamespace(chat=AsyncMock(return_value="invalid-json"))
    host = SimpleNamespace(
        _config=config, _manifest_selector=ManifestSelector(config), _llm_provider_bridge=bridge
    )
    result = await HybridRetrievalPostProcessingMixin()._select_manifest_if_enabled(
        payload, request=RetrievalQuery(query="Find my memories"), host=host
    )
    if not enabled:
        bridge.chat.assert_not_awaited()
        assert result == expected
    else:
        bridge.chat.assert_awaited_once()
        prompt = bridge.chat.await_args.kwargs["messages"][0]["content"]
        assert [line for line in prompt.splitlines() if line.startswith("[")] == [
            f"[{i}] (L1) Memory {i}" for i in range(20)
        ]
        assert result.l1_events == expected.l1_events[:10]
        assert result.trace["manifest_selector_input_count"] == 20
        assert result.trace["manifest_selector_output_count"] == 10


def _complete_payload():
    payload = _sample_payload()
    payload.l2_relationships = [
        {"subject_name": "Alice", "predicate": "LIKES", "object_name": "Jazz"}
    ]
    payload.l2_assertions = [{"entity_name": "Alice", "trait_family": "sleep", "value": "rested"}]
    payload.l2_experiences = [{"title": "Field trip", "magi_interpretation": "Explored the coast"}]
    payload.l0_workbench = [{"sentinel": "untouched workbench"}]
    payload.trace = {"prior_trace": "preserve"}
    return payload


# ---------------------------------------------------------------------------
# _build_candidate_list
# ---------------------------------------------------------------------------


def test_manifest_candidates_bind_each_text_to_its_exact_payload_position():
    manifest = build_manifest_candidates(_complete_payload(), max_chars=400)
    assert list(zip(manifest.candidates, manifest.index_map, strict=True)) == [
        (("L1", "[1700000000] Had dinner at Sushi place"), ("l1_events", 0)),
        (("L1", "[1700100000] Went to the gym"), ("l1_events", 1)),
        (("L1", "[1700200000] Bought groceries at Trader Joe"), ("l1_events", 2)),
        (("L2", 'Alice (person): {"role": "friend"}'), ("l2_entity_cards", 0)),
        (("L2", "Alice --LIKES--> Jazz"), ("l2_relationships", 0)),
        (("L2", "Alice [sleep]: rested"), ("l2_assertions", 0)),
        (("L2", "Field trip: Explored the coast"), ("l2_experiences", 0)),
        (("L3", "[2024-W01] User exercises regularly"), ("l3_reflections", 0)),
        (("L4", "Search web for restaurant reviews"), ("l4_procedures", 0)),
    ]


# ---------------------------------------------------------------------------
# _parse_response
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_response,candidate_count,first_index,second_index,third_index",
    [
        pytest.param('{"selected": [2, 0, 4]}', 5, 2, 0, 4, id="parse_response_valid_json"),
        pytest.param("not json", 3, 0, 1, 2, id="parse_response_invalid_json_returns_all"),
    ],
)
def test_parse_response_selects_indices_or_falls_back(
    model_response, candidate_count, first_index, second_index, third_index
):
    selected = ManifestSelector._parse_response(model_response, candidate_count)
    assert selected == [first_index, second_index, third_index]


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
@pytest.mark.parametrize(
    "failure,status,attempted",
    [
        ("missing_bridge", "skipped_no_bridge", False),
        ("provider_error", "error_fallback", True),
        ("invalid_json", "applied", True),
    ],
)
async def test_selector_fallback_preserves_every_payload_family(failure, status, attempted):
    from dataclasses import asdict

    config = RetrievalConfig(manifest_selector_enabled=True)
    payload = _complete_payload()
    expected = asdict(payload)
    bridge = SimpleNamespace(
        chat=AsyncMock(
            return_value="invalid-json",
            side_effect=RuntimeError("unavailable") if failure == "provider_error" else None,
        )
    )
    result = await ManifestSelector(config).select(
        payload,
        query="Find my memories",
        llm_bridge=None if failure == "missing_bridge" else bridge,
    )
    if attempted:
        bridge.chat.assert_awaited_once()
    else:
        bridge.chat.assert_not_awaited()
    actual = asdict(result)
    assert actual.pop("trace")["manifest_selector"] == status
    assert result.trace["prior_trace"] == expected.pop("trace")["prior_trace"]
    assert actual == expected


@pytest.mark.asyncio
async def test_select_skips_empty_payload():
    config = RetrievalConfig(manifest_selector_enabled=True)
    selector = ManifestSelector(config)
    payload = _make_payload()
    from copy import deepcopy

    expected = deepcopy(payload)
    bridge = SimpleNamespace(chat=AsyncMock())
    result = await selector.select(payload, query="test", llm_bridge=bridge)
    assert result.trace["manifest_selector"] == "skipped_empty"
    bridge.chat.assert_not_awaited()
    expected.trace["manifest_selector"] = "skipped_empty"
    assert result == expected


# ---------------------------------------------------------------------------
# _truncate helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "input_text,max_length",
    [
        pytest.param("hello", 100, id="truncate_short"),
        pytest.param("abcde", 5, id="truncate_exact"),
    ],
)
def test_truncate_preserves_text_within_limit(input_text, max_length):
    assert truncate_manifest_text(input_text, max_length) == input_text


def test_truncate_long():
    assert truncate_manifest_text("a" * 50, 20) == "a" * 17 + "..."
