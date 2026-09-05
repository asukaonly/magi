"""Profile admission distinguishes source UI labels from meaningful objects."""

import pytest

from magi.memory.l2.assertions.profile_worthiness import profile_evidence_reason


@pytest.mark.parametrize("label,metadata,reason", [
    ("动态(2)", {}, "navigation_label"),
    ("请帮我修复记忆页面", {}, "task_instruction_label"),
    ("DeepSeek", {"page_kind": "search"}, "non_content_page"),
    ("DeepSeek", {"object_role": "page_title"}, "non_profile_object_role"),
    ("动态规划", {}, None),
    ("动态", {"structured_entity_hints": [{"mention_text": "动态", "semantic_role": "work"}]}, None),
    ("图数据库", {"page_kind": "feed", "structured_entity_hints": [{"mention_text": "图数据库", "semantic_role": "topic"}]}, None),
    ("咖啡", {"profile_eligible": False}, "source_excludes_profile"),
])
def test_source_semantics_control_profile_admission(label, metadata, reason):
    assert profile_evidence_reason({"metadata_json": metadata}, object_id="topic:test", label=label) == reason


@pytest.mark.asyncio
async def test_repeated_navigation_events_do_not_meet_profile_threshold():
    from magi.memory.l2.assertions.derived_rules import _load_edge_evidence_stats
    class Source:
        async def get_evidence_records(self, ids):
            return {identity: {"timestamp": 1000 + index * 86400, "metadata_json": {"page_kind": "feed"}} for index, identity in enumerate(ids)}
    stats = await _load_edge_evidence_stats(edges=[{"triple_id": "edge", "object_id": "media:feed", "observation_count": 99, "evidence_event_ids": ["a", "b", "c"]}], l1_store=Source(), now=200000, canonical_names={"media:feed": "动态(2)"})
    assert stats["edge"].evidence_count == 0
