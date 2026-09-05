from __future__ import annotations

from magi_plugin_sdk.sources import SourceMemoryPolicy
from magi.awareness.source_projection import SourceProjection


def test_source_memory_policy_to_from_dict_roundtrip():
    policy = SourceMemoryPolicy(
        memory_domain="external_activity",
        ingest_target="l1_only",
        cognition_eligible=True,
        tom_depth="self",
        retention_class="ephemeral",
        importance_bias=0.7,
        author_type="external",
        content_type="observation",
    )
    d = policy.to_dict()
    assert d["memory_domain"] == "external_activity"
    assert d["ingest_target"] == "l1_only"
    assert d["importance_bias"] == 0.7

    restored = SourceMemoryPolicy.from_dict(d)
    assert restored == policy


def test_source_memory_policy_default_roundtrip():
    policy = SourceMemoryPolicy()
    restored = SourceMemoryPolicy.from_dict(policy.to_dict())
    assert restored == policy


def test_source_projection_to_from_dict_roundtrip():
    p = SourceProjection(
        title="X",
        summary="Y",
        content="Z",
        embedding_head="head",
        metadata={"k": "v", "n": 1},
    )
    d = p.to_dict()
    assert d["title"] == "X"
    assert d["metadata"] == {"k": "v", "n": 1}

    restored = SourceProjection.from_dict(d)
    assert restored == p


def test_timeline_event_already_has_to_from_dict():
    """Smoke check that the existing TimelineEvent.to_dict/from_dict still work."""
    from magi.timeline.contracts import TimelineEvent
    assert hasattr(TimelineEvent, "to_dict")
    assert hasattr(TimelineEvent, "from_dict")
