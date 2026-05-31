"""TDD tests for Phase 2 cluster G (MemoryQueryPort) and I (RiskLevel PROMOTE).

Phase 2 G: build_tool_capabilities().memory_query is wired with a MemoryQueryPort
  adapter that exposes all 5 methods.

Phase 2 I: RiskLevel, RiskSignal, ClassificationResult are promoted to the SDK
  module magi_plugin_sdk.permissions. Host modules re-export from SDK so
  identity is preserved (host is SDK).
"""
from __future__ import annotations


# ---------------------------------------------------------------------------
# Cluster G — MemoryQueryPort
# ---------------------------------------------------------------------------

def test_memory_query_port_wired():
    """build_tool_capabilities().memory_query must not be None after Phase 2 G."""
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities

    reset_tool_capabilities()
    caps = build_tool_capabilities()
    assert caps.memory_query is not None, "memory_query port must be wired"
    reset_tool_capabilities()


def test_memory_query_port_has_build_query():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities

    reset_tool_capabilities()
    mq = build_tool_capabilities().memory_query
    assert hasattr(mq, "build_query"), "MemoryQueryPort must expose build_query"
    reset_tool_capabilities()


def test_memory_query_port_has_query():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities

    reset_tool_capabilities()
    mq = build_tool_capabilities().memory_query
    assert hasattr(mq, "query"), "MemoryQueryPort must expose query"
    reset_tool_capabilities()


def test_memory_query_port_has_get_canonical_names():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities

    reset_tool_capabilities()
    mq = build_tool_capabilities().memory_query
    assert hasattr(mq, "get_canonical_names"), "MemoryQueryPort must expose get_canonical_names"
    reset_tool_capabilities()


def test_memory_query_port_has_project_historical_recall():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities

    reset_tool_capabilities()
    mq = build_tool_capabilities().memory_query
    assert hasattr(mq, "project_historical_recall"), (
        "MemoryQueryPort must expose project_historical_recall"
    )
    reset_tool_capabilities()


def test_memory_query_port_has_make_conversation_turn():
    from magi.bootstrap.tool_capabilities import build_tool_capabilities, reset_tool_capabilities

    reset_tool_capabilities()
    mq = build_tool_capabilities().memory_query
    assert hasattr(mq, "make_conversation_turn"), (
        "MemoryQueryPort must expose make_conversation_turn"
    )
    reset_tool_capabilities()


def test_memory_query_port_type_annotation():
    """ToolCapabilities.memory_query type annotation must be MemoryQueryPort, not Any."""
    from magi_plugin_sdk.capabilities import MemoryQueryPort, ToolCapabilities
    import typing

    hints = typing.get_type_hints(ToolCapabilities)
    # The annotation should be Optional[MemoryQueryPort]
    memory_query_hint = hints.get("memory_query")
    assert memory_query_hint is not None, "memory_query must have a type hint"
    # Check that MemoryQueryPort appears in the annotation
    hint_str = str(memory_query_hint)
    assert "MemoryQueryPort" in hint_str, (
        f"memory_query type hint should reference MemoryQueryPort; got {hint_str}"
    )


def test_memory_query_port_in_sdk_all():
    """MemoryQueryPort must be exported from magi_plugin_sdk.capabilities.__all__."""
    from magi_plugin_sdk import capabilities

    assert "MemoryQueryPort" in capabilities.__all__, (
        "MemoryQueryPort must appear in magi_plugin_sdk.capabilities.__all__"
    )


# ---------------------------------------------------------------------------
# Cluster I — RiskLevel PROMOTE
# ---------------------------------------------------------------------------

def test_sdk_permissions_module_importable():
    """magi_plugin_sdk.permissions must be importable."""
    import magi_plugin_sdk.permissions  # noqa: F401


def test_risk_level_in_sdk():
    """RiskLevel must be importable from magi_plugin_sdk.permissions."""
    from magi_plugin_sdk.permissions import RiskLevel

    assert RiskLevel.LOW.value == "low"
    assert RiskLevel.MEDIUM.value == "medium"
    assert RiskLevel.HIGH.value == "high"
    assert RiskLevel.DESTRUCTIVE.value == "destructive"


def test_risk_signal_in_sdk():
    """RiskSignal must be importable from magi_plugin_sdk.permissions."""
    from magi_plugin_sdk.permissions import RiskSignal

    sig = RiskSignal(key="test_key", description="test description")
    assert sig.key == "test_key"
    assert sig.description == "test description"


def test_classification_result_in_sdk():
    """ClassificationResult must be importable from magi_plugin_sdk.permissions."""
    from magi_plugin_sdk.permissions import ClassificationResult, RiskLevel, RiskSignal

    result = ClassificationResult(
        level=RiskLevel.LOW,
        signals=[RiskSignal(key="k", description="d")],
        preview=None,
    )
    assert result.level == RiskLevel.LOW
    assert len(result.signals) == 1


def test_sdk_permissions_all():
    """All three types must appear in __all__."""
    from magi_plugin_sdk import permissions

    assert "RiskLevel" in permissions.__all__
    assert "RiskSignal" in permissions.__all__
    assert "ClassificationResult" in permissions.__all__


def test_host_risk_level_is_sdk_risk_level():
    """Host re-export identity: contracts.RiskLevel IS sdk.RiskLevel."""
    from magi.agent.control.permission.contracts import RiskLevel as H
    from magi_plugin_sdk.permissions import RiskLevel as S

    assert H is S, (
        "RiskLevel from host contracts must be the SAME object as "
        "the one from magi_plugin_sdk.permissions (re-export identity)"
    )


def test_host_classification_result_is_sdk_classification_result():
    """Host re-export identity: classifier_models.ClassificationResult IS sdk.ClassificationResult."""
    from magi.agent.control.permission.classifier_models import ClassificationResult as H
    from magi_plugin_sdk.permissions import ClassificationResult as S

    assert H is S, (
        "ClassificationResult from host classifier_models must be the SAME object as "
        "the one from magi_plugin_sdk.permissions (re-export identity)"
    )


def test_host_risk_signal_is_sdk_risk_signal():
    """Host re-export identity: classifier_models.RiskSignal IS sdk.RiskSignal."""
    from magi.agent.control.permission.classifier_models import RiskSignal as H
    from magi_plugin_sdk.permissions import RiskSignal as S

    assert H is S, (
        "RiskSignal from host classifier_models must be the SAME object as "
        "the one from magi_plugin_sdk.permissions (re-export identity)"
    )


def test_risk_level_ordering():
    """RiskLevel ordering must still work after promotion."""
    from magi_plugin_sdk.permissions import RiskLevel

    assert RiskLevel.LOW < RiskLevel.MEDIUM
    assert RiskLevel.MEDIUM < RiskLevel.HIGH
    assert RiskLevel.HIGH < RiskLevel.DESTRUCTIVE
    assert RiskLevel.DESTRUCTIVE >= RiskLevel.HIGH
