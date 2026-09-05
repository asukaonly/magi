from __future__ import annotations

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


def test_first_context_story_uses_constrained_chat_profile():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    event = _make_event(source="chat", content="还行")
    event.metadata_json = {
        "interaction_kind": "first_context_story",
        "first_context": {
            "question_id": "recent_feeling",
            "question_text": "最近有哪件小事，让你心情有一点变化？",
        },
    }

    profile = resolve_extraction_profile(event)

    assert profile.profile_id == "chat.first_context_story"
    assert profile.allow_graph is True
    assert profile.allow_assertion is True
    assert profile.extraction_instructions is not None
    assert "may or may not answer that question" in profile.extraction_instructions
    assert "ignore the question" in profile.extraction_instructions
    assert "normal explicit-evidence rules" in profile.extraction_instructions
    assert "gibberish" in profile.extraction_instructions


def test_timeline_source_falls_back_to_chat_profile():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(
        _make_event(source="timeline", content="Visited GitHub today")
    )

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


def test_calendar_source_uses_calendar_profile_restrictions():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(
        _make_event(source="calendar", content="Dinner with Alice tomorrow"),
        plugin_profile_specs=_plugin_profile_specs(),
    )

    assert profile.profile_id == "source.calendar"
    assert profile.allow_graph is True
    assert profile.allow_assertion is False


def test_chrome_history_source_uses_chrome_history_profile_restrictions():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(
        _make_event(source="chrome_history", content="Visited GitHub repository page"),
        plugin_profile_specs=_plugin_profile_specs(),
    )

    assert profile.profile_id == "source.chrome_history"
    assert profile.allowed_entity_types == frozenset(
        {
            "product",
            "software",
            "technology",
            "media",
            "person",
            "organization",
            "topic",
        }
    )
    assert profile.allowed_predicates == frozenset(
        {
            "VISITED",
            "USES",
            "INTERESTED_IN",
            "FOLLOWS",
            "VIEWED",
            "WORKS_WITH",
        }
    )
    assert profile.allow_assertion is False


# ── YAML config loading ──


def test_plugin_profiles_load_chrome_history():
    from magi.memory.l2.extraction_profiles import build_extraction_profile_registry

    profiles = build_extraction_profile_registry(_plugin_profile_specs())
    assert "source.chrome_history" in profiles
    profile = profiles["source.chrome_history"]
    assert profile.profile_id == "source.chrome_history"
    assert profile.allow_assertion is False
    assert "VISITED" in profile.allowed_predicates
    assert profile.extraction_instructions is not None
    assert "Preserve the source title language/script" in profile.extraction_instructions
    assert (
        "Do NOT infer the content entity name from URL domains" in profile.extraction_instructions
    )


def test_yaml_profiles_always_include_default_chat():
    from magi.memory.l2.extraction_profiles import get_extraction_profiles

    profiles = get_extraction_profiles()
    assert "chat.user_message" in profiles


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


def test_netease_music_source_uses_music_profile():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(
        _make_event(source="netease_music", content="Playing a song"),
        plugin_profile_specs=_plugin_profile_specs(),
    )
    assert profile.profile_id == "source.netease_music"
    assert profile.allow_graph is True
    assert profile.allow_assertion is True
    assert "LISTENED" in profile.allowed_predicates
    assert "preference_profile" in profile.allowed_assertion_families
    assert "media" in profile.allowed_entity_types
    assert "person" in profile.allowed_entity_types


def test_git_activity_source_uses_git_profile():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(
        _make_event(source="git_activity", content="commit abc"),
        plugin_profile_specs=_plugin_profile_specs(),
    )
    assert profile.profile_id == "source.git_activity"
    assert profile.allow_graph is True
    assert profile.allow_assertion is False
    assert "COMMITTED" in profile.allowed_predicates
    assert "WORKS_WITH" in profile.allowed_predicates
    assert "software" in profile.allowed_entity_types
    assert "technology" in profile.allowed_entity_types


def test_terminal_history_source_uses_terminal_profile():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(
        _make_event(source="terminal_history", content="docker ps"),
        plugin_profile_specs=_plugin_profile_specs(),
    )
    assert profile.profile_id == "source.terminal_history"
    assert profile.allow_graph is True
    assert profile.allow_assertion is False
    assert "EXECUTED" in profile.allowed_predicates
    assert "USES" in profile.allowed_predicates
    assert "software" in profile.allowed_entity_types


def test_screen_time_source_uses_screen_time_profile():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(
        _make_event(source="screen_time", content="App usage"),
        plugin_profile_specs=_plugin_profile_specs(),
    )
    assert profile.profile_id == "source.screen_time"
    assert profile.allow_graph is True
    assert profile.allow_assertion is False
    assert "USES" in profile.allowed_predicates
    assert "software" in profile.allowed_entity_types


def test_plugin_profiles_load_all_source_profiles():
    from magi.memory.l2.extraction_profiles import build_extraction_profile_registry

    profiles = build_extraction_profile_registry(_plugin_profile_specs())
    expected = {
        "source.netease_music",
        "source.git_activity",
        "source.terminal_history",
        "source.screen_time",
    }
    for pid in expected:
        assert pid in profiles, f"Missing profile: {pid}"


def test_netease_music_profile_allows_preference_assertions():
    from magi.memory.l2.extraction_profiles import build_extraction_profile_registry

    profiles = build_extraction_profile_registry(_plugin_profile_specs())
    music_profile = profiles["source.netease_music"]
    assert music_profile.allow_assertion is True
    assert "preference_profile" in music_profile.allowed_assertion_families
    assert music_profile.extraction_instructions is not None


def test_unknown_source_still_falls_back_to_chat():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(_make_event(source="some_unknown_source", content="data"))
    assert profile.profile_id == "chat.user_message"


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


def test_plugin_profile_cannot_override_host_chat_profile():
    from magi.memory.l2.extraction_profiles import build_extraction_profile_registry

    profiles = build_extraction_profile_registry(
        [
            ExtractionProfileSpec(
                profile_id="chat.user_message",
                source_types=["chat"],
                allowed_entity_types=["software"],
                allowed_predicates=["USES"],
            )
        ]
    )

    assert profiles["chat.user_message"].allowed_entity_types != frozenset({"software"})


def test_plugin_allow_assertion_is_preserved():
    from magi.memory.l2.extraction_profiles import build_extraction_profile_registry

    profiles = build_extraction_profile_registry(_plugin_profile_specs())

    assert profiles["source.calendar"].allow_assertion is False
    assert profiles["source.netease_music"].allow_assertion is True


def test_phase1_and_summary_instructions_are_independent():
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
                "summary_instructions": "summary wording instructions",
                "allow_assertion": False,
            }
        ]
    )

    profile = profiles["source.custom_source"]
    assert profile.extraction_instructions == "new phase one instructions"
    assert profile.phase1_instructions == "new phase one instructions"
    assert profile.summary_instructions == "summary wording instructions"


def test_unknown_profile_fields_do_not_change_materialization_authority():
    from magi.memory.l2.extraction_profiles import build_extraction_profile_registry

    profiles = build_extraction_profile_registry(
        [
            {
                "profile_id": "source.bad_mode",
                "source_types": ["bad_mode"],
                "allowed_entity_types": ["topic"],
                "allowed_predicates": ["INTERESTED_IN"],
                "unknown_materialization_mode": "direct_write",
            }
        ]
    )

    assert profiles["source.bad_mode"].allow_assertion is True


def test_allowed_assertion_traits_default_to_all():
    from magi.memory.l2.extraction_profiles import build_extraction_profile_registry

    profiles = build_extraction_profile_registry(
        [
            {
                "profile_id": "source.trait_defaults",
                "source_types": ["trait_defaults"],
                "allowed_entity_types": ["topic"],
                "allowed_predicates": ["INTERESTED_IN"],
                "allow_assertion": True,
            }
        ]
    )

    assert profiles["source.trait_defaults"].allowed_assertion_traits is None
