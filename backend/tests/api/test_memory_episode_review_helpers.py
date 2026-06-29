"""Tests for memory episode review serialization helpers."""

from __future__ import annotations

import json

from magi.api.services.l2_episode_review_helpers import (
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


def test_serialize_l1_event_preview_keeps_short_content():
    preview = serialize_l1_event_preview(
        {
            "event_id": "e1",
            "timestamp": 123.0,
            "event_type": "UserMessage",
            "source": "chat",
            "content": "hello",
        },
        membership={
            "episode_id": "ep1",
            "event_id": "e1",
            "membership_role": "member",
            "membership_confidence": 0.8,
            "added_at": 124.0,
        },
    )

    assert preview["event_id"] == "e1"
    assert preview["content_preview"] == "hello"
    assert preview["membership_confidence"] == 0.8


def test_score_episode_candidate_rewards_time_and_shared_topics():
    score, reasons = score_episode_candidate(
        {
            "time_start": 100,
            "time_end": 200,
            "primary_topic_keys": ["travel", "japan"],
            "primary_place_ids": ["place:tokyo"],
        },
        {
            "time_start": 210,
            "time_end": 260,
            "primary_topic_keys": ["japan"],
            "primary_place_ids": ["place:tokyo"],
        },
    )

    assert score > 0
    assert "nearby_time" in reasons
    assert "shared_topics" in reasons
    assert "shared_places" in reasons
