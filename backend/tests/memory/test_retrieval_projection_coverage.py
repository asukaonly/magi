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
    assert "patterns directly supported" in formatted
    assert "observations from the returned records" in formatted
    assert "overall habits, preferences, diversity, frequency, or totals" in formatted
    assert "returned findings directly establish" in formatted
    assert "report the findings concretely" in formatted


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
    assert "Total-count and overall claims are allowed" in formatted
    assert "source and time scope" in formatted


def test_event_stream_is_rendered_as_historical_record_not_current_fact() -> None:
    projected = project_historical_recall(
        payload=RetrievalPayload(
            l1_events=[
                {
                    "event_id": "evt-old-location",
                    "content": "I live in Hangzhou.",
                    "timestamp": 1_702_000_000.0,
                    "correction_status": "later_corrected",
                }
            ]
        ),
        request={"query": "Where was I living?", "query_mode": "event_stream"},
    )

    assert projected.summary == "当时记录：I live in Hangzhou."
    assert projected.findings[0]["evidence_semantics"] == "historical_record"
    assert projected.findings[0]["correction_status"] == "later_corrected"
    formatted = compact_historical_recall(
        asdict(projected),
        max_items=6,
        max_text_chars=500,
    )
    assert "historical record; not a current fact" in formatted
    assert "later corrected; do not repeat as fact" in formatted


def test_compaction_renders_generic_structured_totals() -> None:
    projected = project_historical_recall(
        payload=RetrievalPayload(
            structured_results=[
                {
                    "domain": "browser",
                    "operation": "count",
                    "title": "Browser recall stats",
                    "coverage": {
                        "kind": "exhaustive",
                        "can_claim_total": True,
                        "total_count": 2,
                        "returned_count": 2,
                        "omitted_count": 0,
                    },
                    "summary": {
                        "event_count": 2,
                        "metric_label": "visits",
                        "metric_total": 5,
                        "by_year": {"2024": 2},
                    },
                    "items": [
                        {
                            "event_id": "evt-browser-1",
                            "timestamp": 1_710_000_000.0,
                            "content": "Visited Example docs.",
                            "metric_value": 3,
                        }
                    ],
                }
            ]
        ),
        request={"query": "example.com 浏览过几次", "query_mode": "cross_session"},
    )

    formatted = compact_historical_recall(asdict(projected), max_items=6, max_text_chars=500)

    assert "Structured Browser Result" in formatted
    assert "Events: 2" in formatted
    assert "Total visits: 5" in formatted
