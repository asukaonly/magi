from __future__ import annotations

import pytest

import time

from magi.events.events import Event, EventLevel, EventTypes
from magi.memory.event_contracts import normalize_runtime_event
from magi_plugin_sdk import ExtractionProfileSpec


def _plugin_profile_specs() -> list[ExtractionProfileSpec]:
    return [
        ExtractionProfileSpec(
            profile_id="source.calendar",
            source_types=["calendar"],
            allowed_entity_types=["activity", "event", "place", "organization"],
            allowed_predicates=["ATTENDED", "PLANS_TO", "VISITED"],
            allow_graph=True,
            allow_assertion=False,
        ),
        ExtractionProfileSpec(
            profile_id="source.chrome_history",
            source_types=["chrome_history"],
            allowed_entity_types=[
                "product",
                "software",
                "technology",
                "media",
                "person",
                "organization",
                "topic",
            ],
            allowed_predicates=[
                "VISITED",
                "USES",
                "INTERESTED_IN",
                "FOLLOWS",
                "VIEWED",
                "WORKS_WITH",
            ],
            allow_graph=True,
            allow_assertion=False,
            extraction_instructions=(
                "Preserve the source title language/script. "
                "Do NOT infer the content entity name from URL domains."
            ),
        ),
        ExtractionProfileSpec(
            profile_id="source.netease_music",
            source_types=["netease_music"],
            allowed_entity_types=["media", "person", "group"],
            allowed_predicates=["LISTENED", "LIKES", "INTERESTED_IN"],
            allowed_assertion_families=["preference_profile"],
            allow_graph=True,
            allow_assertion=True,
            extraction_instructions="NetEase Cloud Music listening profile.",
        ),
        ExtractionProfileSpec(
            profile_id="source.git_activity",
            source_types=["git_activity"],
            allowed_entity_types=["software", "technology", "topic"],
            allowed_predicates=[
                "COMMITTED",
                "CHECKED_OUT",
                "MERGED",
                "REBASED",
                "WORKS_WITH",
                "USES",
            ],
            allow_graph=True,
            allow_assertion=False,
        ),
        ExtractionProfileSpec(
            profile_id="source.terminal_history",
            source_types=["terminal_history"],
            allowed_entity_types=["software", "technology"],
            allowed_predicates=["EXECUTED", "USED", "USES"],
            allow_graph=True,
            allow_assertion=False,
        ),
        ExtractionProfileSpec(
            profile_id="source.screen_time",
            source_types=["screen_time"],
            allowed_entity_types=["software", "media"],
            allowed_predicates=["USES", "VIEWED"],
            allow_graph=True,
            allow_assertion=False,
        ),
    ]


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


def _make_history_import_event(*, event_type: str = "history_import.document"):
    event = _make_event(
        source="history_import",
        content="# Notes\n\nI keep a weekly pottery practice.",
    )
    event.event_type = event_type
    return event


def test_default_chat_profile_exposes_full_allowlists():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile
    from magi.memory.l2.ontology import ENTITY_TYPE_REGISTRY, PREDICATE_REGISTRY

    profile = resolve_extraction_profile(_make_event(source="chat"))

    assert profile.profile_id == "chat.user_message"
    assert profile.allowed_entity_types == ENTITY_TYPE_REGISTRY
    assert profile.allowed_predicates == PREDICATE_REGISTRY
    assert profile.allow_assertion is True


@pytest.mark.parametrize(
    "interaction,expected",
    [("first_context_story", "chat.first_context_story"), ("chat", "chat.user_message")],
)
def test_first_context_metadata_selects_the_host_profile(interaction, expected):
    from magi.memory.l2.extraction_profiles import (
        get_extraction_profiles,
        resolve_extraction_profile,
    )

    event = _make_event(source="chat", content="还行")
    event.metadata_json = {
        "interaction_kind": interaction,
        "first_context": {
            "question_id": "recent_feeling",
            "question_text": "最近有哪件小事，让你心情有一点变化？",
        },
    }
    assert resolve_extraction_profile(event) == get_extraction_profiles()[expected]


@pytest.mark.parametrize(
    "case_source,case_content",
    [
        pytest.param(
            "timeline", "Visited GitHub today", id="timeline_source_falls_back_to_chat_profile"
        ),
        pytest.param("some_unknown_source", "data", id="unknown_source_still_falls_back_to_chat"),
    ],
)
def test_sources_without_specific_profiles_use_chat_fallback(case_source, case_content):
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(_make_event(source=case_source, content=case_content))
    assert profile.profile_id == "chat.user_message"


def test_history_import_profiles_require_matching_source_and_event_type():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    document_profile = resolve_extraction_profile(_make_history_import_event())
    imported_chat_profile = resolve_extraction_profile(
        _make_history_import_event(event_type="history_import.chat")
    )
    wrong_source = _make_history_import_event()
    wrong_source.source = "chat"
    wrong_source_profile = resolve_extraction_profile(wrong_source)

    assert document_profile.profile_id == "history_import.document"
    assert document_profile.source_types == frozenset({"history_import"})
    assert document_profile.event_types == frozenset({"history_import.document"})
    assert document_profile.phase1_instructions is not None
    assert "historical documents, not live chat turns" in document_profile.phase1_instructions
    assert imported_chat_profile.profile_id == "history_import.chat"
    assert imported_chat_profile.event_types == frozenset({"history_import.chat"})
    assert imported_chat_profile.phase1_instructions is not None
    assert "not live chat messages" in imported_chat_profile.phase1_instructions
    assert wrong_source_profile.profile_id == "chat.user_message"


def test_event_specific_profile_wins_before_source_only_profile():
    from magi.memory.l2.extraction_profiles import (
        ExtractionProfile,
        get_extraction_profiles,
        resolve_extraction_profile,
    )

    registry = {
        "source.history_import_generic": ExtractionProfile(
            profile_id="source.history_import_generic",
            source_types=frozenset({"history_import"}),
        ),
        **get_extraction_profiles(),
    }

    profile = resolve_extraction_profile(
        _make_history_import_event(),
        profile_registry=registry,
    )

    assert profile.profile_id == "history_import.document"


@pytest.mark.parametrize("spec", _plugin_profile_specs(), ids=lambda spec: spec.profile_id)
def test_plugin_profile_routing_preserves_declared_constraints(spec):
    from magi.memory.l2.extraction_profiles import (
        build_extraction_profile_registry,
        resolve_extraction_profile,
    )
    from magi.memory.l2.ontology import ASSERTION_FAMILY_ALLOWLIST

    profiles = build_extraction_profile_registry(_plugin_profile_specs())
    profile = resolve_extraction_profile(
        _make_event(source=spec.source_types[0]), profile_registry=profiles
    )
    assert profile == profiles[spec.profile_id]
    assert profile.profile_id == spec.profile_id
    assert profile.source_types == frozenset(spec.source_types)
    assert profile.allowed_entity_types == frozenset(spec.allowed_entity_types)
    assert profile.allowed_predicates == frozenset(spec.allowed_predicates)
    assert profile.allow_graph is spec.allow_graph
    assert profile.allow_assertion is spec.allow_assertion
    assert profile.allowed_assertion_families == (
        frozenset({"preference_profile"})
        if spec.profile_id == "source.netease_music"
        else ASSERTION_FAMILY_ALLOWLIST
    )
    assert profile.extraction_instructions == spec.extraction_instructions
    assert profile.phase1_instructions == spec.extraction_instructions
    assert profile.allowed_assertion_traits is None


# ── YAML config loading ──


def test_load_profiles_from_yaml_handles_missing_file():
    from pathlib import Path
    from magi.memory.l2.extraction_profiles import _load_profiles_from_yaml

    profiles = _load_profiles_from_yaml(Path("/nonexistent/path.yaml"))
    assert "chat.user_message" in profiles


def test_load_profiles_from_yaml_handles_invalid_yaml(tmp_path):
    from magi.memory.l2.extraction_profiles import _load_profiles_from_yaml

    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text("profiles: not_a_dict_value: [bad", encoding="utf-8")
    profiles = _load_profiles_from_yaml(bad_file)
    assert "chat.user_message" in profiles


# ── Source source routing ──


def test_invalid_plugin_profile_is_skipped():
    from magi.memory.l2.extraction_profiles import build_extraction_profile_registry

    profiles = build_extraction_profile_registry(
        [
            {
                "profile_id": "source.bad_source",
                "source_types": ["bad_source"],
                "allowed_entity_types": ["not_a_real_entity_type"],
            }
        ]
    )

    assert "source.bad_source" not in profiles
    assert "chat.user_message" in profiles


def test_plugin_override_preserves_complete_host_registry_and_chat_resolution():
    from copy import deepcopy
    from magi.memory.l2.extraction_profiles import (
        build_extraction_profile_registry,
        get_extraction_profiles,
        resolve_extraction_profile,
    )

    baseline = deepcopy(get_extraction_profiles())
    profiles = build_extraction_profile_registry(
        [
            ExtractionProfileSpec(
                profile_id="chat.user_message",
                source_types=["chat"],
                allowed_entity_types=["software"],
                allowed_predicates=["USES"],
                allow_graph=False,
                allow_assertion=False,
                extraction_instructions="Replace the host policy",
            )
        ]
    )
    assert profiles == baseline
    assert get_extraction_profiles() == baseline
    assert (
        resolve_extraction_profile(_make_event(source="chat"), profile_registry=profiles)
        == baseline["chat.user_message"]
    )


def test_phase1_instructions_override_extraction_instructions():
    from magi.memory.l2.extraction_profiles import build_extraction_profile_registry

    profiles = build_extraction_profile_registry(
        [
            {
                "profile_id": "source.custom_source",
                "source_types": ["custom_source"],
                "allowed_entity_types": ["topic"],
                "allowed_predicates": ["INTERESTED_IN"],
                "extraction_instructions": "legacy instructions",
                "phase1_instructions": "new phase one instructions",
                "allow_assertion": False,
            }
        ]
    )

    profile = profiles["source.custom_source"]
    assert profile.extraction_instructions == "new phase one instructions"
    assert profile.phase1_instructions == "new phase one instructions"


def test_unknown_profile_fields_are_ignored_by_the_parser():
    from magi.memory.l2.extraction_profiles import build_extraction_profile_registry

    specification = {
        "profile_id": "source.custom",
        "source_types": ["custom"],
        "allowed_entity_types": ["topic"],
        "allowed_predicates": ["INTERESTED_IN"],
        "allow_assertion": False,
    }
    baseline = build_extraction_profile_registry([specification])
    with_unknown = build_extraction_profile_registry(
        [{**specification, "unknown_materialization_mode": "direct_write"}]
    )
    assert with_unknown == baseline


@pytest.mark.parametrize(
    "source,event_type",
    [
        ("local_documents", "SOURCE_EVENT"),
        ("obsidian_vault", "SOURCE_EVENT"),
        ("manual_entry", "manual_entry.note"),
        ("history_import", "history_import.document"),
    ],
)
def test_document_instructions_preserve_plugin_permissions(source, event_type):
    from magi.memory.l2.extraction_profiles import (
        resolve_extraction_profile,
        build_extraction_profile_registry,
    )
    from magi.memory.l2.document_policy import PERSONAL_DOCUMENT_INSTRUCTIONS

    event = _make_event(source=source)
    event.event_type = event_type
    registry = build_extraction_profile_registry(
        [
            ExtractionProfileSpec(
                profile_id="source.restricted",
                source_types=[source],
                allowed_entity_types=["concept"],
                allowed_predicates=["REFERENCES"],
                allow_assertion=False,
                extraction_instructions="Keep the source restriction.",
            )
        ]
    )
    profile = resolve_extraction_profile(event, profile_registry=registry)
    assert PERSONAL_DOCUMENT_INSTRUCTIONS in profile.extraction_instructions
    if source != "history_import":
        assert profile.allow_assertion is False
        assert profile.allowed_predicates == frozenset({"REFERENCES"})
        assert "Keep the source restriction." in profile.phase1_instructions


@pytest.mark.parametrize(
    "source,event_type",
    [
        ("local_documents_search", "SOURCE_EVENT"),
        ("obsidian_vault_search", "SOURCE_EVENT"),
        ("chat", "UserMessage"),
        ("history_import", "history_import.chat"),
        ("local_documents", "UserMessage"),
    ],
)
def test_document_policy_is_scoped_to_document_events(source, event_type):
    from magi.memory.l2.document_policy import is_personal_document

    assert not is_personal_document(source=source, event_type=event_type)
