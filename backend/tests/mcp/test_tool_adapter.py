import pytest
from magi_plugin_sdk.tools import ParameterType

from magi.mcp.log_security import register_mcp_transport_secrets
from magi.mcp.tool_adapter import build_adapter_class

REMOTE_TOOL = {
    "name": "create_issue",
    "description": "Create a GitHub issue",
    "inputSchema": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "body": {"type": "string"},
            "labels": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title"],
    },
    "annotations": {"destructiveHint": True},
}


class FakeManager:
    last_call = None

    async def call_remote(self, server_id, tool_name, args, timeout_ms):
        FakeManager.last_call = (server_id, tool_name, args, timeout_ms)
        return {"content": [{"type": "text", "text": "ok"}], "isError": False}


@pytest.mark.asyncio
async def test_schema_translation_and_call():
    cls = build_adapter_class(
        server_id="github",
        remote=REMOTE_TOOL,
        manager=FakeManager(),
        call_timeout_ms=30000,
        override=None,
    )
    inst = cls()
    schema = inst.schema
    assert schema.name == "mcp__github__create_issue"
    assert schema.dangerous is True
    assert schema.category == "mcp"
    names = {p.name for p in schema.parameters}
    assert names == {"title", "body", "labels"}
    title = next(p for p in schema.parameters if p.name == "title")
    assert title.required is True and title.type == ParameterType.STRING
    labels = next(p for p in schema.parameters if p.name == "labels")
    assert labels.type == ParameterType.ARRAY
    assert labels.array_item_type == ParameterType.STRING

    result = await inst.execute({"title": "Bug"}, context=None)
    assert result.success is True
    assert FakeManager.last_call == ("github", "create_issue", {"title": "Bug"}, 30000)


def test_default_dangerous_when_no_annotation():
    remote = {
        "name": "x",
        "description": "d",
        "inputSchema": {"type": "object", "properties": {}},
    }
    cls = build_adapter_class(
        "s", remote, manager=None, call_timeout_ms=1000, override=None
    )
    assert cls().schema.dangerous is True


def test_readonly_hint_makes_safe():
    remote = {
        "name": "x",
        "description": "d",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"readOnlyHint": True},
    }
    cls = build_adapter_class(
        "s", remote, manager=None, call_timeout_ms=1000, override=None
    )
    schema = cls().schema
    assert schema.dangerous is False
    # readOnlyHint also surfaces the tool in the `/`-picker by default.
    assert schema.metadata.get("user_invocable") is True


def test_no_annotation_keeps_user_invocable_off():
    remote = {
        "name": "x",
        "description": "d",
        "inputSchema": {"type": "object", "properties": {}},
    }
    cls = build_adapter_class(
        "s", remote, manager=None, call_timeout_ms=1000, override=None
    )
    assert "user_invocable" not in cls().schema.metadata


def test_destructive_hint_keeps_user_invocable_off():
    remote = {
        "name": "x",
        "description": "d",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"destructiveHint": True},
    }
    cls = build_adapter_class(
        "s", remote, manager=None, call_timeout_ms=1000, override=None
    )
    assert "user_invocable" not in cls().schema.metadata


@pytest.mark.asyncio
async def test_iserror_result_returns_failed_tool_result():
    class Err:
        async def call_remote(self, *a, **kw):
            return {
                "content": [{"type": "text", "text": "rate limited"}],
                "isError": True,
            }

    cls = build_adapter_class(
        "s",
        {
            "name": "x",
            "description": "d",
            "inputSchema": {"type": "object", "properties": {}},
        },
        manager=Err(),
        call_timeout_ms=1000,
        override=None,
    )
    result = await cls().execute({}, context=None)
    assert result.success is False
    assert "rate limited" in result.error


@pytest.mark.asyncio
async def test_iserror_result_redacts_custom_mcp_transport_secret():
    secret = "mcp-tool-error-custom-secret"
    register_mcp_transport_secrets(
        {"transport": {"kind": "stdio", "env": {"UNUSUAL_SETTING": secret}}}
    )

    class Err:
        async def call_remote(self, *a, **kw):
            return {
                "content": [{"type": "text", "text": f"failed with {secret}"}],
                "isError": True,
            }

    cls = build_adapter_class(
        "s",
        {
            "name": "x",
            "description": "d",
            "inputSchema": {"type": "object", "properties": {}},
        },
        manager=Err(),
        call_timeout_ms=1000,
        override=None,
    )

    result = await cls().execute({}, context=None)

    assert result.success is False
    assert secret not in result.error
    assert "[REDACTED]" in result.error


def test_override_forces_dangerous_off():
    from magi.mcp.config import ToolOverride

    remote = {
        "name": "rm",
        "description": "d",
        "inputSchema": {"type": "object", "properties": {}},
        "annotations": {"destructiveHint": True},
    }
    cls = build_adapter_class(
        "s",
        remote,
        manager=None,
        call_timeout_ms=1000,
        override=ToolOverride(dangerous=False),
    )
    assert cls().schema.dangerous is False
