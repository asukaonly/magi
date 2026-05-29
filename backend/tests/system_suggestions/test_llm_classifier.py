from magi.system_suggestions.llm_classifier import parse_classify_response


def test_parse_extracts_category_confidences():
    raw = '{"results": [{"category": "browser_history", "confidence": 0.82}, {"category": "code_activity", "confidence": 0.1}]}'
    assert parse_classify_response(raw) == {"browser_history": 0.82, "code_activity": 0.1}


def test_parse_tolerates_code_fence_and_clamps():
    raw = "```json\n{\"results\": [{\"category\": \"x\", \"confidence\": 1.7}]}\n```"
    assert parse_classify_response(raw) == {"x": 1.0}


def test_parse_returns_empty_on_garbage():
    assert parse_classify_response("not json") == {}


def test_parse_handles_missing_or_bad_confidence():
    raw = '{"results": [{"category": "a"}, {"category": "b", "confidence": "oops"}]}'
    assert parse_classify_response(raw) == {"a": 0.0, "b": 0.0}
