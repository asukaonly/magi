"""Keep complete assertion facts through the final answer-facing context."""
from dataclasses import asdict

from magi.memory.hybrid_retrieval.models import RetrievalPayload, RetrievalQuery
from magi.memory.retrieval_projection import project_historical_recall
from magi.memory.tool_context_historical import compact_historical_recall


def test_affinity_target_polarity_validity_and_evidence_survive_final_context():
    assertion = {
        "assertion_id": "jazz",
        "entity_id": "user:local_user",
        "target_entity_id": "other:jazz",
        "trait_name": "preference.affinity",
        "trait_value": "dislike",
        "natural_summary": "用户在工作时不喜欢爵士乐",
        "confidence_score": 0.9,
        "valid_from": 1704067200.0,
        "valid_to": 1735689600.0,
        "temporal_scope": "temporary",
        "scope": {"all_of": [{"dimension": "activity", "context_id": "working"}]},
        "evidence_events": ["event-direct-report"],
        "source_domain": "user_authored",
        "inference_depth": "semantic",
    }
    recall = project_historical_recall(
        payload=RetrievalPayload(l2_assertions=[assertion]),
        request=RetrievalQuery(query="我工作时喜欢什么音乐", user_id="local_user", query_mode="exact_fact"),
        canonical_names={"user:local_user": "用户", "other:jazz": "爵士乐"},
    )
    finding = recall.findings[0]
    assert (finding["subject"], finding["predicate"], finding["value"], finding["target"]) == (
        "用户", "preference.affinity", "dislike", "爵士乐",
    )
    for field in ("valid_from", "valid_to", "temporal_scope", "scope", "evidence_events", "natural_summary"):
        assert finding[field] == assertion[field]
    assert finding["feedback_ref"] == "assertion:jazz"
    rendered = compact_historical_recall(asdict(recall), max_items=10, max_text_chars=1000)
    assert "爵士乐" in rendered and "dislike" in rendered
    assert "用户在工作时不喜欢爵士乐" in rendered
    assert "valid_from=" in rendered and "valid_to=" in rendered
    assert "temporal_scope=temporary" in rendered


def test_equal_affinity_values_for_distinct_targets_are_not_collapsed():
    rows = [{
        "assertion_id": target, "entity_id": "user:local_user",
        "target_entity_id": f"other:{target}", "trait_name": "preference.affinity",
        "trait_value": "like", "confidence_score": 0.9,
    } for target in ("jazz", "tea")]
    recall = project_historical_recall(
        payload=RetrievalPayload(l2_assertions=rows),
        request=RetrievalQuery(query="我的偏好", user_id="local_user", query_mode="exact_fact"),
        canonical_names={"user:local_user": "用户", "other:jazz": "爵士乐", "other:tea": "茶"},
    )
    rendered = compact_historical_recall(asdict(recall), max_items=10, max_text_chars=1000)
    assert "target: 爵士乐" in rendered
    assert "target: 茶" in rendered
    assert "×2" not in rendered


def test_same_fact_with_distinct_validity_intervals_is_not_aggregated():
    from magi.memory.recall_rendering import aggregate_by_statement

    rows = [{
        "kind": "assertion", "statement": "用户 preference.affinity: like; target: 爵士乐",
        "feedback_ref": "assertion:jazz", "valid_from": start, "valid_to": end,
    } for start, end in ((1.0, 2.0), (3.0, 4.0))]
    assert len(aggregate_by_statement(rows)) == 2
