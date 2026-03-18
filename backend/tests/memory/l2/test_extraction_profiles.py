from __future__ import annotations

import time

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event


def _make_event(*, source: str, metadata: dict[str, object] | None = None):
    event = Event(
        type=EventTypes.USER_MESSAGE,
        data={"user_id": "u1", "session_id": "s1", "message": "hello"},
        source=source,
        level=EventLevel.INFO,
        timestamp=time.time(),
        metadata=metadata or {},
    )
    return normalize_runtime_event(event)


def test_default_chat_profile_exposes_full_allowlists():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile
    from magi.memory.l2.ontology import ENTITY_TYPE_REGISTRY, PREDICATE_REGISTRY

    profile = resolve_extraction_profile(_make_event(source="chat"))

    assert profile.profile_id == "chat.user_message"
    assert profile.allowed_entity_types == ENTITY_TYPE_REGISTRY
    assert profile.allowed_predicates == PREDICATE_REGISTRY
    assert profile.allow_assertion is True


def test_chrome_history_profile_is_restricted_to_product_visits():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(
        _make_event(
            source="timeline",
            metadata={"extraction_profile_id": "timeline.chrome_history"},
        )
    )

    assert profile.profile_id == "timeline.chrome_history"
    assert profile.allowed_entity_types == frozenset({"product"})
    assert profile.allowed_predicates == frozenset({"VISITED"})
    assert profile.allow_assertion is False


def test_profile_can_disable_assertions_via_override():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(
        _make_event(
            source="chat",
            metadata={
                "profile_overrides": {
                    "allow_assertion": False,
                }
            },
        )
    )

    assert profile.allow_assertion is False


def test_profile_aliases_override_global_aliases():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(
        _make_event(
            source="chat",
            metadata={
                "profile_overrides": {
                    "entity_type_aliases": {
                        "dish": "product",
                    }
                }
            },
        )
    )

    assert profile.entity_type_aliases["dish"] == "product"
