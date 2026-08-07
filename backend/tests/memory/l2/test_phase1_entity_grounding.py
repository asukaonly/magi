"""Phase 1 entity evidence and script contract tests."""

from __future__ import annotations

from magi.memory.l2.models import L2BatchEvent, L2EventWindow
from magi.memory.l2.pipeline.entity_grounding import (
    evidence_script_names,
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
    resolved_id: str | None = None,
) -> dict[str, object]:
    return {
        "surface": surface,
        "normalized_name": normalized_name,
        "entity_type": entity_type,
        "specificity": "concrete",
        "resolved_id": resolved_id,
        "is_new": resolved_id is None,
        "alias_signals": alias_signals or [],
        "confidence": 0.9,
    }


def test_repairs_translated_abstract_entities_and_claim_reference() -> None:
    surface = "晨间散步"
    translated = "morning walk"
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


def test_drops_sentence_like_new_entity_without_dropping_claim() -> None:
    action = "今年秋天去海边"
    payload: dict[str, object] = {
        "entities": [_entity(action, action, "activity")],
        "fact_claims": [
            {
                "subject_ref": "user:self",
                "subject_type": "user",
                "predicate": "PLANS_TO",
                "object_ref": action,
                "object_type": "activity",
            }
        ],
        "resolved_refs": [],
    }

    normalize_phase1_entity_contract(payload, _window(f"我计划{action}。"))

    assert payload["entities"] == []
    assert payload["fact_claims"] == [
        {
            "subject_ref": "user:self",
            "subject_type": "user",
            "predicate": "PLANS_TO",
            "object_ref": action,
            "object_type": "activity",
        }
    ]
    assert payload["diagnostics"] == {
        "entity_status": "none",
        "rejected_entity_count": 1,
        "rejected_sentence_like_entity_count": 1,
    }


def test_drops_multi_action_phrase_but_keeps_reusable_entity_names() -> None:
    sentence_like = "慢悠悠的晨间散步和随性觅食"
    payload: dict[str, object] = {
        "entities": [
            _entity(sentence_like, sentence_like, "activity"),
            _entity("攀岩", "攀岩", "activity"),
            _entity("陶艺", "陶艺", "skill"),
            _entity("Magi 记忆重构", "Magi 记忆重构", "project"),
        ],
        "fact_claims": [],
        "resolved_refs": [],
    }

    normalize_phase1_entity_contract(
        payload,
        _window(f"我喜欢{sentence_like}，也在练习攀岩和陶艺，并参与 Magi 记忆重构。"),
    )

    entities = payload["entities"]
    assert isinstance(entities, list)
    assert [entity["normalized_name"] for entity in entities] == [
        "攀岩",
        "陶艺",
        "Magi 记忆重构",
    ]


def test_preserves_verified_existing_entity_identity_even_for_sentence_like_title() -> None:
    title = "I Want to Hold Your Hand"
    payload: dict[str, object] = {
        "entities": [
            _entity(
                title,
                title,
                "media",
                resolved_id="media:existing-title",
            )
        ],
        "fact_claims": [],
        "resolved_refs": [],
    }

    normalize_phase1_entity_contract(payload, _window(f"I listened to {title}."))

    assert payload["entities"] == [
        {
            "surface": title,
            "normalized_name": title,
            "entity_type": "media",
            "specificity": "concrete",
            "resolved_id": "media:existing-title",
            "is_new": False,
            "alias_signals": [],
            "confidence": 0.9,
        }
    ]


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
