"""Tests for memory episode review serialization helpers."""

from __future__ import annotations

import json

import pytest

from magi.memory.l2.episodes.presentation import (
    build_episode_display_fields,
    score_episode_candidate,
    serialize_episodic_summary,
    serialize_l1_event_preview,
)


def test_display_fields_prefer_user_overrides():
    episode = {
        "episode_id": "ep1",
        "user_label": "Tokyo trip",
        "user_note": "Manual recap",
        "time_start": 1,
        "time_end": 2,
    }
    summary = {
        "content": "Generated recap",
        "insight_metadata": {"label": "Generated title"},
    }

    fields = build_episode_display_fields(episode, serialize_episodic_summary(summary))

    assert fields["display_title"] == "Tokyo trip"
    assert fields["display_description"] == "Manual recap"
    assert fields["display_source"] == "user_override"


def test_summary_serialization_accepts_json_metadata_string():
    serialized = serialize_episodic_summary(
        {
            "summary_id": "sum1",
            "content": "Generated recap",
            "insight_metadata": json.dumps({"label": "Generated title", "fallback": True}),
            "updated_at": 42,
        }
    )

    assert serialized == {
        "summary_id": "sum1",
        "content": "Generated recap",
        "label": "Generated title",
        "updated_at": 42,
        "is_fallback": True,
    }


def test_summary_serialization_prefers_structured_content_label():
    serialized = serialize_episodic_summary(
        {
            "summary_id": "sum-episode",
            "content": (
                '{\n'
                '  "label": "看 Lelit Marax 清洁视频",\n'
                '  "content": "在 Bilibili 看了 Lelit Marax 咖啡机清洗教程。",\n'
                '  "key_entities": [{"id": "lelit-marax"'
            ),
            "insight_metadata": json.dumps({"label": "media:lelit-mara"}),
            "updated_at": 42,
        }
    )

    assert serialized["label"] == "看 Lelit Marax 清洁视频"
    assert serialized["content"] == "在 Bilibili 看了 Lelit Marax 咖啡机清洗教程。"


@pytest.mark.parametrize("truncated", [False, True])
def test_display_fields_extract_structured_summary_without_metadata_leakage(truncated):
    data = {
        "label": "查海胆日文与 Umi",
        "content": "在 Google 和 Gemini 间查找日文写法。",
        "key_entities": [{"id": "gemini"}],
    }
    encoded = json.dumps(data, ensure_ascii=False)
    if truncated:
        encoded = encoded[: encoded.index('"gemini"') + 3]
    fields = build_episode_display_fields(
        {"episode_id": "episode", "label": "raw-label", "summary": encoded}, None
    )
    assert fields == {
        "display_title": "查海胆日文与 Umi",
        "display_description": "在 Google 和 Gemini 间查找日文写法。",
        "display_source": "generated",
    }


@pytest.mark.parametrize(
    "content,expected",
    [("hello", "hello"), ("字" * 240, "字" * 240), ("字" * 241, "字" * 240 + "...")],
)
def test_event_preview_preserves_membership_and_truncation_boundary(content, expected):
    preview = serialize_l1_event_preview(
        {
            "event_id": "event",
            "timestamp": 123.0,
            "event_type": "UserMessage",
            "source": "chat",
            "content": content,
        },
        membership={
            "episode_id": "episode",
            "event_id": "event",
            "membership_role": "member",
            "membership_confidence": 0.8,
            "added_at": 124.0,
        },
    )
    assert preview == {
        "episode_id": "episode",
        "event_id": "event",
        "membership_role": "member",
        "membership_confidence": 0.8,
        "added_at": 124.0,
        "timestamp": 123.0,
        "event_type": "UserMessage",
        "source": "chat",
        "source_item_id": None,
        "content_preview": expected,
    }


@pytest.mark.parametrize(
    "candidate,reason",
    [
        ({"time_start": 210, "time_end": 260}, "nearby_time"),
        ({"primary_topic_keys": ["japan"]}, "shared_topics"),
        ({"primary_place_ids": ["place:tokyo"]}, "shared_places"),
        ({"primary_entity_ids": ["person:friend"]}, "shared_entities"),
    ],
)
def test_each_episode_match_signal_increases_score_independently(candidate, reason):
    source = {
        "time_start": 100,
        "time_end": 200,
        "primary_topic_keys": ["japan"],
        "primary_place_ids": ["place:tokyo"],
        "primary_entity_ids": ["person:friend"],
    }
    unrelated = {
        "time_start": 200000,
        "time_end": 200100,
        "primary_topic_keys": ["coding"],
        "primary_place_ids": ["place:paris"],
        "primary_entity_ids": ["person:other"],
    }
    baseline, baseline_reasons = score_episode_candidate(source, unrelated)
    score, reasons = score_episode_candidate(source, {**unrelated, **candidate})
    assert baseline == 0 and baseline_reasons == []
    assert score > baseline
    assert reasons == [reason]
