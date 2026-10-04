"""Host-owned memory capabilities and shared permission contracts."""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_built_memory_capability_routes_queries_and_projection_to_host_owners(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import Mock, AsyncMock
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities
    from magi.memory.hybrid_retrieval.models import RetrievalQuery, ConversationTurn

    payload = {"l1_events": [{"event_id": "event-1", "content": "evidence"}]}
    service = SimpleNamespace(query=AsyncMock(return_value=payload))
    provider = Mock(return_value=service)
    projection = Mock(return_value=object())
    monkeypatch.setattr("magi.memory.provider.get_hybrid_retrieval_service", provider)
    monkeypatch.setattr("magi.memory.retrieval_projection.project_historical_recall", projection)
    reset_tool_capabilities()
    try:
        port = build_tool_capabilities().memory_query
        turn = port.make_conversation_turn(role="user", content="previous message", timestamp=100.0)
        assert turn == ConversationTurn(role="user", content="previous message", timestamp=100.0)
        request = port.build_query(
            query="follow-up",
            user_id="user-1",
            session_id="session-1",
            query_mode="exact_fact",
            limit=3,
            conversation_context=[turn],
        )
        assert isinstance(request, RetrievalQuery)
        assert (
            request.query,
            request.user_id,
            request.session_id,
            request.query_mode,
            request.limit,
            request.conversation_context,
        ) == ("follow-up", "user-1", "session-1", "exact_fact", 3, [turn])
        assert await port.query(request) is payload
        service.query.assert_awaited_once_with(request)
        provider.assert_called_once_with()
        names = {"entity-1": "Alice"}
        plugin_projection = object()
        result = port.project_historical_recall(
            payload=payload,
            request=request,
            plugin_projection_service=plugin_projection,
            canonical_names=names,
        )
        assert result is projection.return_value
        projection.assert_called_once_with(
            payload=payload,
            request=request,
            plugin_projection_service=plugin_projection,
            canonical_names=names,
        )
        assert not hasattr(port, "memory_db_path")
    finally:
        reset_tool_capabilities()


def test_memory_query_port_is_internal_only():
    """Rich query adapters must not be exposed to external plugins."""
    from magi_plugin_sdk import capabilities

    assert "MemoryQueryPort" not in capabilities.__all__, (
        "MemoryQueryPort must remain host-owned"
    )



@pytest.mark.parametrize(
    "name,wire_value",
    [
        ("LOW", "low"),
        ("MEDIUM", "medium"),
        ("HIGH", "high"),
        ("DESTRUCTIVE", "destructive"),
        ("KILL_LISTED", "kill_listed"),
    ],
)
def test_permission_types_share_public_identity_and_classification_wire_values(name, wire_value):
    import json
    from dataclasses import asdict
    from magi_plugin_sdk import permissions as sdk
    from magi.control.permission import classifier_models as host
    from magi.control.permission.contracts import RiskLevel

    for symbol in ["RiskLevel", "RiskSignal", "ClassificationResult"]:
        assert symbol in sdk.__all__
        assert getattr(host, symbol) is getattr(sdk, symbol)
    assert RiskLevel is sdk.RiskLevel
    result = sdk.ClassificationResult(
        level=getattr(sdk.RiskLevel, name),
        signals=[sdk.RiskSignal(key="file_write", description="Changes a file")],
        preview="write preview",
    )
    assert json.loads(json.dumps(asdict(result))) == {
        "level": wire_value,
        "signals": [{"key": "file_write", "description": "Changes a file"}],
        "preview": "write preview",
    }


def test_risk_level_ordering():
    """RiskLevel ordering must still work after promotion."""
    from magi_plugin_sdk.permissions import RiskLevel

    assert RiskLevel.LOW < RiskLevel.MEDIUM
    assert RiskLevel.MEDIUM < RiskLevel.HIGH
    assert RiskLevel.HIGH < RiskLevel.DESTRUCTIVE
    assert RiskLevel.DESTRUCTIVE >= RiskLevel.HIGH



@pytest.mark.asyncio
async def test_host_memory_query_port_resolves_names_without_exposing_db_path(monkeypatch):
    """Resolve names through the host-owned database without exposing its path."""
    from magi.bootstrap.tool_capabilities import _HostMemoryQueryPort

    port = _HostMemoryQueryPort()

    class _FakeService:
        memory_db_path = "/tmp/mem.db"

        async def query(self, request):  # pragma: no cover
            return None

    # Inject directly into the cache attribute the adapter uses so no real
    # memory initialisation is triggered.
    port._service = _FakeService()
    calls = []

    async def lookup(db_path, entity_ids):
        calls.append((db_path, entity_ids))
        return {"entity-1": "Alice"}

    monkeypatch.setattr("magi.memory.l2.entities.catalog.lookup.get_canonical_names", lookup)
    assert not hasattr(port, "memory_db_path")
    assert await port.get_canonical_names({"entity-1"}) == {"entity-1": "Alice"}
    assert calls == [("/tmp/mem.db", {"entity-1"})]
