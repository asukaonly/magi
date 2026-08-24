"""End-to-end test: gate() suspends → REST resolves → gate() returns ALLOWED.

This wires the real ``ControlPlaneModule`` (bootstrap path), mounts
the real ``control_router``, and exercises the full production
control-plane loop without any mock prompter. It validates:

* The module's DI overrides are actually picked up by the REST
  router (no monkeypatching).
* ``BrokeredPermissionPrompter`` registers the request, the poll
  endpoint surfaces it, the REST response resolves the broker, and
  the gateway returns the user's decision.
* Session-scope rule persisted by the gateway is found on a
  subsequent ``gate()`` call — no second prompt.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from magi.control.permission.contracts import (
    PermissionOutcome,
    ToolOrigin,
)
from magi.api.routers.control import control_router
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.bootstrap.control_plane import ControlPlaneModule
from magi.control.permission.provider import get_permission_gateway


class _FakeRuntimePaths:
    def __init__(self, base) -> None:
        self.runtime_dir = base
        self.runtime_trace_db_path = base / "runtime_trace.db"
        # permission_rules schema is alembic-owned; production migrates at
        # boot (DatabaseMigrationModule) before the control plane starts.
        from alembic import command

        from magi.db.runner import MIGRATION_TARGETS, _build_config

        from pathlib import Path

        target = next(t for t in MIGRATION_TARGETS if t.name == "permission_rules")
        command.upgrade(_build_config(target, Path(base) / "permission_rules.db"), "head")
        trace_target = next(t for t in MIGRATION_TARGETS if t.name == "runtime_trace")
        command.upgrade(_build_config(trace_target, self.runtime_trace_db_path), "head")


@pytest.mark.asyncio
async def test_e2e_gate_prompts_then_rest_resolves_then_rule_cached(tmp_path) -> None:
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = _FakeRuntimePaths(tmp_path)
    module = ControlPlaneModule(context)
    await module.init()
    try:
        gateway = get_permission_gateway()

        app = FastAPI()
        app.include_router(control_router, prefix="/api/control")
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Kick off a gate() for a dangerous bash in the background.
            gate_task = asyncio.create_task(
                gateway.gate(
                    tool_name="bash",
                    arguments={"command": "rm -rf ~/tmp/project-x"},
                    agent_id="chat",
                    origin=ToolOrigin.CHAT,
                    session_id="sess-e2e",
                    tool_is_dangerous=True,
                )
            )

            # Wait up to 2s for the request to appear in the pending list.
            request_id: str | None = None
            for _ in range(200):
                resp = await client.get(
                    "/api/control/sessions/sess-e2e/permissions"
                )
                assert resp.status_code == 200
                items = resp.json()["items"]
                if items:
                    request_id = items[0]["request_id"]
                    assert items[0]["tool_name"] == "bash"
                    assert items[0]["risk_level"] in {"high", "destructive"}
                    break
                await asyncio.sleep(0.01)
            assert request_id is not None, "pending permission never surfaced"

            # User approves with session scope.
            resp = await client.post(
                f"/api/control/permission/{request_id}/respond",
                json={"outcome": "allow", "scope": "session"},
            )
            assert resp.status_code == 200
            assert resp.json() == {"resolved": True, "request_id": request_id}

            decision = await asyncio.wait_for(gate_task, timeout=2.0)
            assert decision.outcome is PermissionOutcome.ALLOWED
            assert decision.source == "user"
            assert decision.recorded_rule is not None

            # Registry was cleared after resolution.
            resp = await client.get(
                "/api/control/sessions/sess-e2e/permissions"
            )
            assert resp.json()["items"] == []

            # Second gate() on the same tool+args reuses the cached rule —
            # no prompt is shown, decision is immediate.
            decision2 = await gateway.gate(
                tool_name="bash",
                arguments={"command": "rm -rf ~/tmp/project-x"},
                agent_id="chat",
                origin=ToolOrigin.CHAT,
                session_id="sess-e2e",
                tool_is_dangerous=True,
            )
            assert decision2.outcome is PermissionOutcome.ALLOWED
            assert decision2.source.startswith("rule:")
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_e2e_gate_rest_denies_blocks_tool(tmp_path) -> None:
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = _FakeRuntimePaths(tmp_path)
    module = ControlPlaneModule(context)
    await module.init()
    try:
        gateway = get_permission_gateway()
        app = FastAPI()
        app.include_router(control_router, prefix="/api/control")
        transport = ASGITransport(app=app)

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            gate_task = asyncio.create_task(
                gateway.gate(
                    tool_name="bash",
                    # Default mode is HIGH_ONLY: a plain `rm file` classifies
                    # as medium risk and auto-allows; only HIGH-risk commands
                    # (e.g. rm -rf) still prompt the user.
                    arguments={"command": "rm -rf ~/tmp/project-y"},
                    agent_id="chat",
                    origin=ToolOrigin.CHAT,
                    session_id="sess-deny",
                    tool_is_dangerous=True,
                )
            )

            request_id: str | None = None
            for _ in range(200):
                items = (
                    await client.get("/api/control/sessions/sess-deny/permissions")
                ).json()["items"]
                if items:
                    request_id = items[0]["request_id"]
                    break
                await asyncio.sleep(0.01)
            assert request_id is not None

            resp = await client.post(
                f"/api/control/permission/{request_id}/respond",
                json={"outcome": "deny", "reason": "not right now"},
            )
            assert resp.status_code == 200

            decision = await asyncio.wait_for(gate_task, timeout=2.0)
            assert decision.outcome is PermissionOutcome.DENIED
            assert decision.source == "user"
            assert decision.reason == "not right now"
    finally:
        await module.shutdown()


@pytest.mark.asyncio
async def test_e2e_respond_to_unknown_request_id_returns_404(tmp_path) -> None:
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = _FakeRuntimePaths(tmp_path)
    module = ControlPlaneModule(context)
    await module.init()
    try:
        app = FastAPI()
        app.include_router(control_router, prefix="/api/control")
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/control/permission/does-not-exist/respond",
                json={"outcome": "allow"},
            )
            assert resp.status_code == 404
    finally:
        await module.shutdown()
