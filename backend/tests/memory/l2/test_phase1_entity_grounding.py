"""Phase 1 entity evidence and script contract tests."""

from __future__ import annotations

import pytest

from magi.memory.l2.models import L2BatchEvent, L2EventWindow
from magi.memory.l2.pipeline.entity_grounding import (
    evidence_script_names,
    materialize_grounded_future_intent_entities,
    normalize_phase1_entity_contract,
)
from magi.memory.l2.pipeline.history_markdown import HISTORY_DOCUMENT_EVENT_TYPE


def _window(content: str, *, event_type: str = "") -> L2EventWindow:
    return L2EventWindow(
        events=[
            L2BatchEvent(
                event_id="evt-1",
                content=content,
                event_type=event_type,
                author_type="user",
            )
        ]
    )


def _entity(
    surface: str,
    normalized_name: str,
    entity_type: str,
    *,
    alias_signals: list[str] | None = None,
) -> dict[str, object]:
    return {
        "surface": surface,
        "normalized_name": normalized_name,
        "entity_type": entity_type,
        "specificity": "concrete",
        "resolved_id": None,
        "is_new": True,
        "alias_signals": alias_signals or [],
        "confidence": 0.9,
    }


def test_repairs_translated_abstract_entities_and_claim_reference() -> None:
    surface = "慢悠悠的晨间散步和随性觅食"
    translated = "slow morning walk and casual breakfast hunting"
    payload: dict[str, object] = {
        "entities": [
            _entity(
                surface,
                translated,
                "activity",
                alias_signals=[translated],
            ),
            _entity("DIIV", "DIIV", "group"),
        ],
        "fact_claims": [
            {
                "subject_ref": "user:self",
                "subject_type": "user",
                "predicate": "LIKES",
                "object_ref": translated,
                "object_type": "activity",
            }
        ],
        "resolved_refs": [],
        "diagnostics": {"entity_status": "found"},
    }

    normalizations = normalize_phase1_entity_contract(
        payload,
        _window(f"我喜欢{surface}，散步时经常听 DIIV。"),
    )

    entities = payload["entities"]
    assert isinstance(entities, list)
    assert entities[0]["normalized_name"] == surface
    assert entities[0]["alias_signals"] == []
    assert entities[1]["normalized_name"] == "DIIV"
    claims = payload["fact_claims"]
    assert isinstance(claims, list)
    assert claims[0]["object_ref"] == surface
    assert payload["diagnostics"] == {
        "entity_status": "found",
        "repaired_entity_name_count": 1,
        "dropped_entity_alias_count": 1,
        "rewritten_claim_entity_ref_count": 1,
    }
    assert normalizations


def test_keeps_same_script_normalization() -> None:
    payload: dict[str, object] = {
        "entities": [
            _entity(
                "有方向但不设具体目的地的旅行方式",
                "不设具体目的地的旅行方式",
                "concept",
            )
        ],
        "fact_claims": [],
        "resolved_refs": [],
    }

    normalize_phase1_entity_contract(
        payload,
        _window("我喜欢有方向但不设具体目的地的旅行方式。"),
    )

    entities = payload["entities"]
    assert isinstance(entities, list)
    assert entities[0]["normalized_name"] == "不设具体目的地的旅行方式"


def test_does_not_rewrite_ambiguous_translated_claim_reference() -> None:
    translated = "unbound travel style"
    payload: dict[str, object] = {
        "entities": [
            _entity("随性旅行方式", translated, "concept"),
            _entity("自由旅行方式", translated, "concept"),
        ],
        "fact_claims": [
            {
                "object_ref": translated,
                "object_type": "concept",
            }
        ],
        "resolved_refs": [],
    }

    normalize_phase1_entity_contract(
        payload,
        _window("我在比较随性旅行方式和自由旅行方式。"),
    )

    claims = payload["fact_claims"]
    assert isinstance(claims, list)
    assert claims[0]["object_ref"] == translated


def test_keeps_only_aliases_observed_in_current_evidence() -> None:
    payload: dict[str, object] = {
        "entities": [
            _entity(
                "微信",
                "WeChat",
                "software",
                alias_signals=["WeChat", "Weixin"],
            )
        ],
        "fact_claims": [],
        "resolved_refs": [],
    }

    normalize_phase1_entity_contract(
        payload,
        _window("我在微信（WeChat）上和朋友聊天。"),
    )

    entities = payload["entities"]
    assert isinstance(entities, list)
    assert entities[0]["normalized_name"] == "微信"
    assert entities[0]["alias_signals"] == ["WeChat"]


def test_drops_entity_absent_from_current_evidence() -> None:
    payload: dict[str, object] = {
        "entities": [_entity("历史里的项目", "历史里的项目", "project")],
        "fact_claims": [],
        "resolved_refs": [],
        "diagnostics": {"entity_status": "found"},
    }

    normalize_phase1_entity_contract(payload, _window("今天只记录了散步。"))

    assert payload["entities"] == []
    assert payload["diagnostics"] == {
        "entity_status": "none",
        "rejected_entity_count": 1,
    }


def test_drops_history_document_entity_found_only_in_blockquote() -> None:
    payload: dict[str, object] = {
        "entities": [_entity("引用中的项目", "引用中的项目", "project")],
        "fact_claims": [],
        "resolved_refs": [],
    }

    normalize_phase1_entity_contract(
        payload,
        _window(
            "我自己的记录。\n\n> 引用中的项目",
            event_type=HISTORY_DOCUMENT_EVENT_TYPE,
        ),
    )

    assert payload["entities"] == []


def test_materializes_missing_grounded_future_intent_target() -> None:
    payload: dict[str, object] = {
        "entities": [_entity("海边", "海边", "place")],
        "fact_claims": [
            {
                "subject_ref": "user:self",
                "subject_type": "user",
                "predicate": "PLANS_TO",
                "object_ref": "秋天去一次海边",
                "object_type": "activity",
                "fact_kind": "future_intent",
                "polarity": "positive",
                "specificity": "concrete",
                "evidence_text": "我想秋天去一次海边",
                "confidence": 0.84,
            }
        ],
        "diagnostics": {"entity_status": "found"},
    }

    normalizations = materialize_grounded_future_intent_entities(payload)

    entities = payload["entities"]
    assert isinstance(entities, list)
    assert entities == [
        _entity("海边", "海边", "place"),
        {
            "surface": "秋天去一次海边",
            "normalized_name": "秋天去一次海边",
            "entity_type": "activity",
            "specificity": "concrete",
            "resolved_id": None,
            "is_new": True,
            "alias_signals": [],
            "confidence": 0.9,
        },
    ]
    assert payload["diagnostics"] == {
        "entity_status": "found",
        "materialized_future_intent_entity_count": 1,
    }
    assert normalizations == [
        "entities: materialized 1 grounded future-intent targets omitted by the model"
    ]


def test_does_not_duplicate_existing_future_intent_target() -> None:
    target = "秋天去一次海边"
    payload: dict[str, object] = {
        "entities": [_entity(target, target, "activity")],
        "fact_claims": [
            {
                "predicate": "PLANS_TO",
                "object_ref": target,
                "object_type": "activity",
                "fact_kind": "future_intent",
                "specificity": "concrete",
                "evidence_text": f"我想{target}",
                "confidence": 0.96,
            }
        ],
        "diagnostics": {"entity_status": "found"},
    }

    normalizations = materialize_grounded_future_intent_entities(payload)

    assert payload["entities"] == [_entity(target, target, "activity")]
    assert payload["diagnostics"] == {"entity_status": "found"}
    assert normalizations == []


def test_does_not_materialize_future_intent_target_absent_from_evidence() -> None:
    payload: dict[str, object] = {
        "entities": [],
        "fact_claims": [
            {
                "predicate": "PLANS_TO",
                "object_ref": "去海边",
                "object_type": "activity",
                "fact_kind": "future_intent",
                "specificity": "concrete",
                "evidence_text": "我想休息一下",
                "confidence": 0.96,
            }
        ],
        "diagnostics": {"entity_status": "none"},
    }

    assert materialize_grounded_future_intent_entities(payload) == []
    assert payload["entities"] == []
    assert payload["diagnostics"] == {"entity_status": "none"}


@pytest.mark.parametrize(
    ("predicate", "fact_kind", "specificity"),
    [
        ("LIKES", "stable_preference", "concrete"),
        ("PLANS_TO", "explicit_fact", "concrete"),
        ("PLANS_TO", "future_intent", "underspecified"),
    ],
)
def test_only_materializes_concrete_future_intent_targets(
    predicate: str,
    fact_kind: str,
    specificity: str,
) -> None:
    payload: dict[str, object] = {
        "entities": [],
        "fact_claims": [
            {
                "predicate": predicate,
                "object_ref": "去海边",
                "object_type": "activity",
                "fact_kind": fact_kind,
                "specificity": specificity,
                "evidence_text": "我计划去海边",
                "confidence": 0.96,
            }
        ],
        "diagnostics": {"entity_status": "none"},
    }

    assert materialize_grounded_future_intent_entities(payload) == []
    assert payload["entities"] == []


def test_detects_scripts_from_non_assistant_current_evidence() -> None:
    window = L2EventWindow(
        events=[
            L2BatchEvent(
                event_id="evt-user",
                content="我最近在听 DIIV。",
                author_type="user",
            ),
            L2BatchEvent(
                event_id="evt-assistant",
                content="Русский контекст",
                author_type="assistant",
            ),
        ]
    )

    assert evidence_script_names(window) == ("Han", "Latin")
