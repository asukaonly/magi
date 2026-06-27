"""Round 5 I2: trace keys emitted by the hybrid retrieval service must
land in the module logger so ops can grep the backend log instead of
having to reload the payload object.

Verified at the helper level — the public ``query`` path is exercised by
integration tests; this file pins the format and the key set.
"""

from __future__ import annotations

import logging

from magi.memory.hybrid_retrieval.models import RetrievalPayload
from magi.memory.hybrid_retrieval.service import (
    _TRACE_KEYS_LOGGED,
    _log_retrieval_trace,
)


def test_log_emits_when_trace_populated(caplog) -> None:
    payload = RetrievalPayload(
        trace={
            "query_mode": "episode_recall",
            "mode_source": "indexical_override",
            "indexical_resolved": True,
            "indexical_cue": "当时",
            "dropped_unresolved_entity_count": 3,
            "irrelevant_key": "should_not_appear",
        }
    )
    with caplog.at_level(logging.INFO, logger="magi.memory.hybrid_retrieval.service"):
        _log_retrieval_trace(payload)

    msgs = [r.getMessage() for r in caplog.records]
    assert any("retrieval trace:" in m for m in msgs), msgs
    line = next(m for m in msgs if "retrieval trace:" in m)
    assert "mode_source='indexical_override'" in line
    assert "indexical_cue='当时'" in line
    assert "indexical_resolved=True" in line
    assert "dropped_unresolved_entity_count=3" in line
    assert "query_mode='episode_recall'" in line
    # Keys not in the allowlist must NOT leak.
    assert "irrelevant_key" not in line


def test_log_skips_when_trace_empty(caplog) -> None:
    payload = RetrievalPayload(trace={})
    with caplog.at_level(logging.INFO, logger="magi.memory.hybrid_retrieval.service"):
        _log_retrieval_trace(payload)
    assert not any("retrieval trace:" in r.getMessage() for r in caplog.records)


def test_log_skips_falsy_values(caplog) -> None:
    """Unset / falsy entries are dropped so the line stays short."""
    payload = RetrievalPayload(
        trace={
            "query_mode": "exact_fact",
            "indexical_resolved": False,  # don't emit
            "indexical_cue": "",  # don't emit
            "l1_retrieval_scopes": [],  # don't emit
            "dropped_unresolved_entity_count": 0,  # don't emit (only > 0 matters)
        }
    )
    with caplog.at_level(logging.INFO, logger="magi.memory.hybrid_retrieval.service"):
        _log_retrieval_trace(payload)
    line = next(r.getMessage() for r in caplog.records if "retrieval trace:" in r.getMessage())
    assert "query_mode='exact_fact'" in line
    assert "indexical_resolved" not in line
    assert "indexical_cue" not in line
    assert "l1_retrieval_scopes" not in line
    assert "dropped_unresolved_entity_count" not in line


def test_log_keys_allowlist_is_documented() -> None:
    """The keys we log are an explicit allowlist — adding a new trace key
    to the payload must NOT auto-leak it. This test pins the current set
    so additions go through deliberate review."""
    assert _TRACE_KEYS_LOGGED == (
        "query_mode",
        "mode_source",
        "inferred_mode",
        "indexical_resolved",
        "indexical_cue",
        "indexical_cue_orphaned",
        "mode_rrf_applied",
        "l1_retrieval_scopes",
        "recall_shape",
        "structured_recall",
        "dropped_unresolved_entity_count",
    )
