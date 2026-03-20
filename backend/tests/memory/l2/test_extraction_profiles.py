from __future__ import annotations

import time

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event


def _make_event(*, source: str, content: str = "hello"):
    event = Event(
        type=EventTypes.USER_MESSAGE,
        data={
            "user_id": "u1",
            "session_id": "s1",
            "content": content,
            "author_type": "user",
            "content_type": "text",
        },
        source=source,
        level=EventLevel.INFO,
        timestamp=time.time(),
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


def test_timeline_source_uses_calendar_profile_restrictions():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(_make_event(source="timeline", content="Visited GitHub today"))

    assert profile.profile_id == "timeline.calendar"
    assert profile.allowed_entity_types == frozenset({"activity", "event", "place", "organization"})
    assert profile.allowed_predicates == frozenset({"ATTENDED", "PLANS_TO", "VISITED"})
    assert profile.allow_assertion is False


def test_calendar_source_uses_calendar_profile_restrictions():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(_make_event(source="calendar", content="Dinner with Alice tomorrow"))

    assert profile.profile_id == "timeline.calendar"
    assert profile.allow_graph is True
    assert profile.allow_assertion is False
