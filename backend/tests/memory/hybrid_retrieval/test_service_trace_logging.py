"""Verify useful query diagnostics and private-content omission at the public boundary."""

from __future__ import annotations

import logging

import pytest

from magi.memory.hybrid_retrieval.models import RetrievalPayload
from magi.memory.hybrid_retrieval.service import (
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


@pytest.mark.parametrize(
    "trace,expected",
    [
        ({}, []),
        (
            {
                "query_mode": "",
                "indexical_resolved": False,
                "l1_retrieval_scopes": [],
                "dropped_unresolved_entity_count": 0,
            },
            [],
        ),
        (
            {
                "query_mode": "exact_fact",
                "indexical_resolved": False,
                "indexical_cue": "",
                "l1_retrieval_scopes": [],
                "dropped_unresolved_entity_count": 0,
            },
            ["retrieval trace: query_mode='exact_fact'"],
        ),
    ],
)
def test_empty_and_falsy_diagnostics_do_not_emit_unset_fields(caplog, trace, expected):
    with caplog.at_level(logging.INFO, logger="magi.memory.hybrid_retrieval.service"):
        _log_retrieval_trace(RetrievalPayload(trace=trace))
    assert [
        record.getMessage()
        for record in caplog.records
        if record.name == "magi.memory.hybrid_retrieval.service"
    ] == expected


@pytest.mark.asyncio
async def test_public_query_logs_routing_without_private_query_trace(caplog, monkeypatch):
    from types import SimpleNamespace
    from magi.utils import diagnostic_logging
    from magi.memory.hybrid_retrieval.models import RetrievalConfig, RetrievalQuery
    from magi.memory.hybrid_retrieval.service import HybridRetrievalService

    monkeypatch.setattr(diagnostic_logging, "_FULL_CONTENT_LOGGING_ENABLED", False)
    memory = SimpleNamespace(l0=None, l1=None, l2=None, l2_entity_catalog=None, l3=None, l4=None)
    service = HybridRetrievalService(
        memory, config=RetrievalConfig(intent_decider_llm_enabled=False)
    )
    canary = "PRIVATE-QUERY-CANARY-95271"
    with caplog.at_level(logging.INFO):
        result = await service.query(RetrievalQuery(query=canary, query_mode="exact_fact"))
    assert result.trace["query"] == canary
    lines = [record.getMessage() for record in caplog.records]
    trace_lines = [line for line in lines if line.startswith("retrieval trace:")]
    assert len(trace_lines) == 1
    assert "query_mode='exact_fact'" in trace_lines[0]
    assert "mode_source='caller'" in trace_lines[0]
    assert all(canary not in line for line in lines)
