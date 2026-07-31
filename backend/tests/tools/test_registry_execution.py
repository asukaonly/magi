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
async def test_dangerous_tool_requires_permission():
    result = await _registry(DangerousTool).execute("dangerous_probe", {}, _context())

    assert result.success is False
    assert result.error_code == ToolErrorCode.PERMISSION_DENIED.value
    assert "dangerous_tools" in str(result.error)


@pytest.mark.asyncio
async def test_auth_tool_requires_authenticated_permission():
    result = await _registry(AuthTool).execute("auth_probe", {}, _context())

    assert result.success is False
    assert result.error_code == ToolErrorCode.AUTH_REQUIRED.value
    assert "authentication" in str(result.error)


@pytest.mark.asyncio
async def test_role_tool_requires_allowed_role():
    result = await _registry(RoleTool).execute(
        "role_probe",
        {},
        _context(env_vars={"role": "guest"}),
    )

    assert result.success is False
    assert result.error_code == ToolErrorCode.ROLE_NOT_ALLOWED.value
    assert "admin" in str(result.error)


@pytest.mark.asyncio
async def test_invalid_parameters_short_circuit_execution():
    result = await _registry(InvalidParamsTool).execute("invalid_probe", {}, _context())

    assert result.success is False
    assert result.error_code == ToolErrorCode.INVALID_PARAMETERS.value
    assert result.error == "bad params"


@pytest.mark.asyncio
async def test_timeout_returns_timeout_code():
    result = await _registry(TimeoutTool).execute("timeout_probe", {}, _context())

    assert result.success is False
    assert result.error_code == ToolErrorCode.TIMEOUT.value
    assert result.execution_time is not None


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
