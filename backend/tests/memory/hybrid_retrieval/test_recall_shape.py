"""Shape parsing verifies contracts, not model semantic accuracy."""
import pytest
from magi.memory.hybrid_retrieval.recall_shape import RecallShape, parse_recall_shape

@pytest.mark.parametrize("operation", ["count", "enumerate", "aggregate"])
def test_exhaustive_request_does_not_claim_source_completeness(operation):
    shape = parse_recall_shape({"domain_hint": "photo", "operation": operation})
    assert shape.desired_coverage == "exhaustive"
    assert "can_claim_total" not in shape.to_dict()

@pytest.mark.parametrize("raw", [None, [], "count", {"domain_hint": []}, {"domain_hint": "photo", "operation": "delete"}])
def test_invalid_shape_is_unknown(raw):
    assert parse_recall_shape(raw) == RecallShape()
