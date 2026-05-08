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


def test_timeline_source_falls_back_to_chat_profile():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(_make_event(source="timeline", content="Visited GitHub today"))

    assert profile.profile_id == "chat.user_message"


def test_calendar_source_uses_calendar_profile_restrictions():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(_make_event(source="calendar", content="Dinner with Alice tomorrow"))

    assert profile.profile_id == "source.calendar"
    assert profile.allow_graph is True
    assert profile.allow_assertion is False


def test_chrome_history_source_uses_chrome_history_profile_restrictions():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(
        _make_event(source="chrome_history", content="Visited GitHub repository page")
    )

    assert profile.profile_id == "source.chrome_history"
    assert profile.allowed_entity_types == frozenset({
        "product", "software", "technology", "media",
        "person", "organization", "topic",
    })
    assert profile.allowed_predicates == frozenset({
        "VISITED", "USES", "INTERESTED_IN", "FOLLOWS",
        "VIEWED", "WORKS_WITH",
    })
    assert profile.allow_assertion is False


# ── YAML config loading ──


def test_yaml_profiles_load_chrome_history():
    from magi.memory.l2.extraction_profiles import get_extraction_profiles

    profiles = get_extraction_profiles()
    assert "source.chrome_history" in profiles
    profile = profiles["source.chrome_history"]
    assert profile.profile_id == "source.chrome_history"
    assert profile.allow_assertion is False
    assert "VISITED" in profile.allowed_predicates
    assert profile.extraction_instructions is not None
    assert "Preserve the source title language/script" in profile.extraction_instructions
    assert "Do NOT infer the content entity name from URL domains" in profile.extraction_instructions


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


# ── Sensor source routing ──


def test_netease_music_source_uses_music_profile():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(
        _make_event(source="netease_music", content="Playing a song")
    )
    assert profile.profile_id == "source.netease_music"
    assert profile.allow_graph is True
    assert profile.allow_assertion is True
    assert "LISTENED" in profile.allowed_predicates
    assert "taste_profile" in profile.allowed_assertion_families
    assert "media" in profile.allowed_entity_types
    assert "person" in profile.allowed_entity_types


def test_git_activity_source_uses_git_profile():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(
        _make_event(source="git_activity", content="commit abc")
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
        _make_event(source="terminal_history", content="docker ps")
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
        _make_event(source="screen_time", content="App usage")
    )
    assert profile.profile_id == "source.screen_time"
    assert profile.allow_graph is True
    assert profile.allow_assertion is False
    assert "USES" in profile.allowed_predicates
    assert "software" in profile.allowed_entity_types


def test_yaml_profiles_load_all_sensor_profiles():
    from magi.memory.l2.extraction_profiles import get_extraction_profiles

    profiles = get_extraction_profiles()
    expected = {
        "source.netease_music",
        "source.git_activity",
        "source.terminal_history",
        "source.screen_time",
    }
    for pid in expected:
        assert pid in profiles, f"Missing profile: {pid}"


def test_netease_music_profile_allows_taste_assertions():
    from magi.memory.l2.extraction_profiles import get_extraction_profiles

    profiles = get_extraction_profiles()
    music_profile = profiles["source.netease_music"]
    assert music_profile.allow_assertion is True
    assert "taste_profile" in music_profile.allowed_assertion_families
    assert "preference_profile" in music_profile.allowed_assertion_families
    assert music_profile.extraction_instructions is not None


def test_unknown_source_still_falls_back_to_chat():
    from magi.memory.l2.extraction_profiles import resolve_extraction_profile

    profile = resolve_extraction_profile(
        _make_event(source="some_unknown_sensor", content="data")
    )
    assert profile.profile_id == "chat.user_message"
