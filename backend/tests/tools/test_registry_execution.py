"""Tests for tool registry execution policy and failure handling."""

from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest

from magi.tools import registry_execution as registry_execution_module
from magi.tools.registry import ToolRegistry
from magi.tools.schema import (
    ToolErrorCode,
    ToolExecutionContext,
    ToolResult,
    ToolSchema,
)


class _BaseTool:
    SCHEMA: ToolSchema

    def get_schema(self) -> ToolSchema:
        return self.SCHEMA

    async def validate_parameters(self, params: Dict[str, Any]) -> tuple[bool, str]:
        return True, ""

    async def execute(self, params: Dict[str, Any], context: Any) -> ToolResult:
        return ToolResult(success=True, data="ok")

    async def after_execution(self, result: ToolResult, context: Any) -> ToolResult:
        return result


class DangerousTool(_BaseTool):
    SCHEMA = ToolSchema(
        name="dangerous_probe",
        description="Requires dangerous permission",
        category="test",
        dangerous=True,
    )


class AuthTool(_BaseTool):
    SCHEMA = ToolSchema(
        name="auth_probe",
        description="Requires authentication",
        category="test",
        requires_auth=True,
    )


class RoleTool(_BaseTool):
    SCHEMA = ToolSchema(
        name="role_probe",
        description="Requires role",
        category="test",
        allowed_roles=["admin"],
    )


class InvalidParamsTool(_BaseTool):
    SCHEMA = ToolSchema(
        name="invalid_probe",
        description="Rejects parameters",
        category="test",
    )

    async def validate_parameters(self, params: Dict[str, Any]) -> tuple[bool, str]:
        return False, "bad params"

    async def execute(self, params: Dict[str, Any], context: Any) -> ToolResult:
        raise AssertionError("execute should not run after validation failure")


class TimeoutTool(_BaseTool):
    SCHEMA = ToolSchema(
        name="timeout_probe",
        description="Times out",
        category="test",
        timeout=0,
    )

    async def execute(self, params: Dict[str, Any], context: Any) -> ToolResult:
        await asyncio.sleep(0.05)
        return ToolResult(success=True)


class RaisesTool(_BaseTool):
    SCHEMA = ToolSchema(
        name="raises_probe",
        description="Raises an error",
        category="test",
    )

    async def execute(self, params: Dict[str, Any], context: Any) -> ToolResult:
        raise RuntimeError("boom")


def _registry(*tool_classes: type[_BaseTool]) -> ToolRegistry:
    registry = ToolRegistry()
    for tool_class in tool_classes:
        registry.register(tool_class)  # type: ignore[arg-type]
    return registry


def _context(**kwargs: Any) -> ToolExecutionContext:
    return ToolExecutionContext(agent_id="test-agent", **kwargs)


@pytest.mark.asyncio
async def test_invalid_parameters_short_circuit_execution():
    result = await _registry(InvalidParamsTool).execute("invalid_probe", {}, _context())

    assert result.success is False
    assert result.error_code == ToolErrorCode.INVALID_PARAMETERS.value
    assert result.error == "bad params"


@pytest.mark.asyncio
async def test_tool_timeout_cancels_started_body_and_awaits_cleanup(monkeypatch):
    from unittest.mock import AsyncMock

    started = asyncio.Event()
    cleaned = asyncio.Event()
    cancelled = []

    async def execute(self, params, context):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.append(True)
            raise
        finally:
            await asyncio.sleep(0)
            cleaned.set()

    monkeypatch.setattr(TimeoutTool, "execute", execute)
    monkeypatch.setattr(TimeoutTool, "SCHEMA", TimeoutTool.SCHEMA.model_copy(update={"timeout": 1}))
    after = AsyncMock()
    monkeypatch.setattr(TimeoutTool, "after_execution", after)
    invocation = asyncio.create_task(
        _registry(TimeoutTool).execute("timeout_probe", {}, _context())
    )
    try:
        await asyncio.wait_for(started.wait(), 1)
        assert not cleaned.is_set()
        result = await asyncio.wait_for(invocation, 3)
        assert not result.success
        assert result.error_code == ToolErrorCode.TIMEOUT.value
        assert cleaned.is_set() and cancelled == [True]
        after.assert_not_awaited()
    finally:
        if not invocation.done():
            invocation.cancel()
            await asyncio.gather(invocation, return_exceptions=True)


@pytest.mark.asyncio
async def test_execution_exception_returns_execution_error_code():
    result = await _registry(RaisesTool).execute("raises_probe", {}, _context())

    assert result.success is False
    assert result.error_code == ToolErrorCode.EXECUTION_ERROR.value
    assert result.error == "boom"


@pytest.mark.asyncio
async def test_execution_exception_log_omits_error_content_when_disabled(
    monkeypatch,
    caplog,
):
    secret_error = "private tool exception content"
    monkeypatch.setattr(
        registry_execution_module,
        "full_content_logging_enabled",
        lambda: False,
    )

    class PrivateRaisesTool(_BaseTool):
        SCHEMA = ToolSchema(
            name="private_raises_probe",
            description="Raises private content",
            category="test",
        )

        async def execute(
            self,
            params: Dict[str, Any],
            context: Any,
        ) -> ToolResult:
            raise RuntimeError(secret_error)

    with caplog.at_level(
        "WARNING",
        logger=registry_execution_module.logger.name,
    ):
        result = await _registry(PrivateRaisesTool).execute(
            "private_raises_probe",
            {},
            _context(),
        )

    assert result.error == secret_error
    assert secret_error not in caplog.text
    assert "error_type=RuntimeError" in caplog.text

@pytest.mark.asyncio
@pytest.mark.parametrize("tool_class,error_code,allowed_context", [
    (DangerousTool, ToolErrorCode.PERMISSION_DENIED, {"permissions":["dangerous_tools"]}),
    (AuthTool, ToolErrorCode.AUTH_REQUIRED, {"permissions":["authenticated"]}),
    (RoleTool, ToolErrorCode.ROLE_NOT_ALLOWED, {"env_vars":{"role":"admin"}}),
])
async def test_permission_denial_prevents_body_and_hooks_but_allows_authorized_control(tool_class, error_code, allowed_context, monkeypatch):
    calls = []
    async def validate(self, params):
        calls.append("validate")
        return True, ""
    async def execute(self, params, context):
        calls.append("execute")
        return ToolResult(success=True, data="executed")
    async def after(self, result, context):
        calls.append("after")
        return result
    monkeypatch.setattr(tool_class,"validate_parameters",validate)
    monkeypatch.setattr(tool_class,"execute",execute)
    monkeypatch.setattr(tool_class,"after_execution",after)
    registry = _registry(tool_class)
    denied = await registry.execute(tool_class.SCHEMA.name, {}, _context())
    assert not denied.success
    assert denied.error_code == error_code.value
    assert calls == []
    allowed = await registry.execute(tool_class.SCHEMA.name, {}, _context(**allowed_context))
    assert allowed.success and allowed.data == "executed"
    assert calls == ["validate","execute","after"]
