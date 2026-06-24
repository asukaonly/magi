from dataclasses import asdict

from magi.memory.hybrid_retrieval.models import RetrievalPayload
from magi.memory.retrieval_projection import project_historical_recall
from magi.memory.tool_context_historical import compact_historical_recall


def test_projection_marks_plain_recall_as_non_exhaustive() -> None:
    projected = project_historical_recall(
        payload=RetrievalPayload(
            l1_events=[
                {
                    "event_id": "evt-1",
                    "content": "照片记录：拍摄了 3 张照片。",
                    "source": "photo_library_apple_photos",
                    "timestamp": 1_702_000_000.0,
                }
            ]
        ),
        request={"query": "我拍过几次照片", "query_mode": "cross_session"},
    )

    assert projected.coverage["kind"] == "sample"
    assert projected.coverage["can_claim_total"] is False

    formatted = compact_historical_recall(asdict(projected), max_items=6, max_text_chars=500)
    assert "representative, not exhaustive" in formatted


def test_projection_preserves_structured_exhaustive_coverage() -> None:
    projected = project_historical_recall(
        payload=RetrievalPayload(
            structured_results=[
                {
                    "domain": "photo",
                    "operation": "count",
                    "title": "Photo recall stats",
                    "coverage": {
                        "kind": "exhaustive",
                        "can_claim_total": True,
                        "total_count": 2,
                        "returned_count": 2,
                        "omitted_count": 0,
                    },
                    "summary": {"session_count": 2, "photo_count": 5},
                    "items": [],
                }
            ]
        ),
        request={"query": "我拍过几次照片", "query_mode": "cross_session"},
    )

    assert projected.coverage["kind"] == "exhaustive"
    assert projected.coverage["can_claim_total"] is True

    formatted = compact_historical_recall(asdict(projected), max_items=6, max_text_chars=500)
    assert "coverage=exhaustive" in formatted
    assert "total-count claims are allowed" in formatted
