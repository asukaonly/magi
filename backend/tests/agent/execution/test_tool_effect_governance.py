from __future__ import annotations

import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from _shared.sqlite_privacy import assert_sqlite_fragment_absent
from magi.agent.background import BackgroundTaskStore
from magi.agent.execution.tool_invocation_service import (
    InvocationContext,
    ToolCall,
    ToolInvocationService,
)
from magi.events.domain_payloads import TaskContext
from magi.tools.schema import ToolExecutionContext, ToolResult


class _Tool:
    def __init__(
        self,
        *,
        policy: str,
        idempotency_parameter: str | None = None,
    ) -> None:
        self._schema = SimpleNamespace(
            name="effect_tool",
            effect_replay_policy=policy,
            effect_idempotency_key_parameter=idempotency_parameter,
        )

    def get_schema(self):
        return self._schema


class _Registry:
    def __init__(
        self,
        *,
        policy: str,
        results: list[object],
        idempotency_parameter: str | None = None,
    ) -> None:
        self._tool = _Tool(
            policy=policy,
            idempotency_parameter=idempotency_parameter,
        )
        self.execute = AsyncMock(side_effect=results)

    def get_tool(self, _name: str):
        return self._tool


def _context(*, with_identity: bool = True) -> InvocationContext:
    return InvocationContext(
        tool_category="test",
        task_context=TaskContext(
            session_id="session-1" if with_identity else None,
            turn_id="turn-1" if with_identity else None,
            task_id=None,
            user_id="user-1",
        ),
        execution_context=ToolExecutionContext(
            agent_id="test-agent",
            workspace=".",
            env_vars={"trace_tool_call_id": "call-1"},
        ),
    )


@pytest.fixture
def ledger(runtime_paths_with_schema) -> BackgroundTaskStore:
    return BackgroundTaskStore(db_path=str(runtime_paths_with_schema.background_tasks_db_path))


@pytest.mark.asyncio
async def test_effect_intent_and_completion_are_durable_without_raw_arguments(
    ledger: BackgroundTaskStore,
) -> None:
    secret = "private-effect-argument-must-not-be-persisted"
    registry = _Registry(
        policy="non_idempotent",
        results=[ToolResult(success=True, data={"ok": True})],
    )
    service = ToolInvocationService(
        registry,
        effect_ledger=ledger,
        require_effect_ledger=True,
    )

    result = await service.invoke(
        ToolCall(name="effect_tool", args={"value": secret}),
        _context(),
    )

    assert result.success is True
    with sqlite3.connect(ledger.db_path) as connection:
        row = connection.execute(
            """
            SELECT state, replay_policy, arguments_digest
            FROM tool_effect_attempts
            """
        ).fetchone()
    assert row is not None
    assert row[0:2] == ("succeeded", "non_idempotent")
    assert len(str(row[2])) == 64
    assert_sqlite_fragment_absent(ledger.db_path, secret)


@pytest.mark.asyncio
async def test_cancelled_effect_becomes_uncertain_and_blocks_automatic_retry(
    ledger: BackgroundTaskStore,
) -> None:
    registry = _Registry(
        policy="non_idempotent",
        results=[asyncio.CancelledError(), ToolResult(success=True)],
    )
    service = ToolInvocationService(
        registry,
        effect_ledger=ledger,
        require_effect_ledger=True,
    )
    call = ToolCall(name="effect_tool", args={"target": "same"})

    with pytest.raises(asyncio.CancelledError):
        await service.invoke(call, _context())
    retry = await service.invoke(call, _context())

    assert retry.success is False
    assert retry.error_code == "TOOL_EFFECT_UNCERTAIN"
    assert retry.metadata["automatic_retry_allowed"] is False
    assert registry.execute.await_count == 1


@pytest.mark.asyncio
async def test_idempotent_policy_allows_retry_after_ambiguous_result(
    ledger: BackgroundTaskStore,
) -> None:
    registry = _Registry(
        policy="idempotent",
        results=[
            ToolResult(success=False, error="timed out", error_code="TIMEOUT"),
            ToolResult(success=True, data="done"),
        ],
    )
    service = ToolInvocationService(
        registry,
        effect_ledger=ledger,
        require_effect_ledger=True,
    )
    call = ToolCall(name="effect_tool", args={"target": "same"})

    first = await service.invoke(call, _context())
    second = await service.invoke(call, _context())

    assert first.success is False
    assert second.success is True
    assert registry.execute.await_count == 2


@pytest.mark.asyncio
async def test_idempotency_key_policy_requires_the_declared_key(
    ledger: BackgroundTaskStore,
) -> None:
    registry = _Registry(
        policy="idempotent_with_key",
        idempotency_parameter="request_id",
        results=[
            ToolResult(success=False, error="timed out", error_code="TIMEOUT"),
            ToolResult(success=True),
        ],
    )
    service = ToolInvocationService(
        registry,
        effect_ledger=ledger,
        require_effect_ledger=True,
    )
    call = ToolCall(name="effect_tool", args={"target": "same"})

    await service.invoke(call, _context())
    retry = await service.invoke(call, _context())

    assert retry.error_code == "TOOL_EFFECT_UNCERTAIN"
    assert registry.execute.await_count == 1


@pytest.mark.asyncio
async def test_read_only_tool_does_not_touch_effect_ledger() -> None:
    registry = _Registry(
        policy="read_only",
        results=[ToolResult(success=True, data="ok")],
    )
    effect_ledger = SimpleNamespace(
        begin_tool_effect=AsyncMock(side_effect=AssertionError("must not persist")),
    )
    service = ToolInvocationService(
        registry,
        effect_ledger=effect_ledger,
        require_effect_ledger=True,
    )

    result = await service.invoke(
        ToolCall(name="effect_tool", args={}),
        _context(),
    )

    assert result.success is True
    effect_ledger.begin_tool_effect.assert_not_awaited()


@pytest.mark.asyncio
async def test_effectful_tool_without_stable_identity_fails_closed(
    ledger: BackgroundTaskStore,
) -> None:
    registry = _Registry(
        policy="unknown",
        results=[ToolResult(success=True)],
    )
    service = ToolInvocationService(
        registry,
        effect_ledger=ledger,
        require_effect_ledger=True,
    )

    result = await service.invoke(
        ToolCall(name="effect_tool", args={}),
        _context(with_identity=False),
    )

    assert result.success is False
    assert result.error_code == "TOOL_EFFECT_IDENTITY_REQUIRED"
    registry.execute.assert_not_awaited()


@pytest.mark.asyncio
async def test_service_resolves_runtime_bound_ledger(
    ledger: BackgroundTaskStore,
) -> None:
    registry = _Registry(
        policy="non_idempotent",
        results=[ToolResult(success=True)],
    )
    registry.resolve_tool_effect_ledger = lambda: (ledger, True)  # type: ignore[attr-defined]
    service = ToolInvocationService(registry)

    result = await service.invoke(
        ToolCall(name="effect_tool", args={"target": "bound"}),
        _context(),
    )

    assert result.success is True
    with sqlite3.connect(ledger.db_path) as connection:
        assert connection.execute("SELECT state FROM tool_effect_attempts").fetchone() == (
            "succeeded",
        )
