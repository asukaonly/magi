"""Verify dangerous flag on MCP-wrapped tools flows into the existing
permission risk classifier exactly as for built-in dangerous tools."""

from magi.control.permission.classifier import RiskClassifier
from magi.control.permission.contracts import RiskLevel
from magi.mcp.tool_adapter import build_adapter_class


def _adapter(annotations):
    return build_adapter_class(
        "demo",
        {
            "name": "x",
            "description": "",
            "inputSchema": {"type": "object", "properties": {}},
            "annotations": annotations,
        },
        manager=None,
        call_timeout_ms=1000,
        override=None,
    )


def test_destructive_mcp_tool_classified_high():
    tool = _adapter({"destructiveHint": True})()
    info = tool.get_info()
    assert info["dangerous"] is True

    classifier = RiskClassifier()
    result = classifier.classify(
        tool_name=tool.schema.name,
        arguments={},
        tool_is_dangerous=info["dangerous"],
    )
    assert result.level == RiskLevel.HIGH


def test_readonly_mcp_tool_classified_low():
    tool = _adapter({"readOnlyHint": True})()
    info = tool.get_info()
    assert info["dangerous"] is False

    classifier = RiskClassifier()
    result = classifier.classify(
        tool_name=tool.schema.name,
        arguments={},
        tool_is_dangerous=info["dangerous"],
    )
    assert result.level == RiskLevel.LOW


def test_unannotated_mcp_tool_treated_as_dangerous():
    tool = _adapter(None)()
    info = tool.get_info()
    assert info["dangerous"] is True

    classifier = RiskClassifier()
    result = classifier.classify(
        tool_name=tool.schema.name,
        arguments={},
        tool_is_dangerous=info["dangerous"],
    )
    assert result.level == RiskLevel.HIGH
