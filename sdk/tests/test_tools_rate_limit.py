"""Tests for provider rate-limit projection in SDK tool results."""

import pytest
from magi_plugin_sdk.tools import MultiProviderTool, ToolSchema


class _RateLimitError(RuntimeError):
    status_code = 429
    retry_after_seconds = 3.0


class _Provider:
    name = "limited"

    def is_ready(self, config) -> bool:
        return True

    async def execute(self, params, config):
        raise _RateLimitError("slow down")


class _Tool(MultiProviderTool):
    def _init_schema(self) -> None:
        self.schema = ToolSchema(name="test", description="test", category="test")

    def _register_providers(self) -> None:
        self.register_provider(_Provider())

    def _get_provider_config(self, provider_name: str):
        return {}

    def _get_default_provider(self) -> str:
        return "limited"

    async def execute(self, parameters, context):
        return await self.execute_with_provider("limited", parameters)


@pytest.mark.asyncio
async def test_multi_provider_tool_projects_rate_limit_metadata() -> None:
    result = await _Tool().execute_with_provider("limited", {})

    assert result.success is False
    assert result.error_code == "RATE_LIMITED"
    assert result.data == {"retry_after_seconds": 3.0}
