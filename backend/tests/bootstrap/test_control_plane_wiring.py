"""Tests for control-plane bootstrap wiring."""

from __future__ import annotations

from pathlib import Path

import pytest

from magi.control.common import InteractionBroker
from magi.control.permission.contracts import (
    PermissionOutcome,
    ToolOrigin,
)
from magi.control.permission.gateway import PermissionGateway
from magi.control.permission.rules import PermissionRuleStore
from magi.control.session_store import ControlSessionStore
from magi.control.settings_manager import ControlSettingsManager
from magi.control.user_content_clear import ControlUserContentClearCoordinator
from magi.bootstrap.context import RuntimeBootstrapContext
from magi.bootstrap.control_plane import ControlPlaneModule
from magi.core.container import get_container
from magi.control.provider import (
    resolve_control_interaction_broker,
    resolve_control_session_store,
    resolve_control_settings_manager,
    resolve_pending_permission_registry,
    resolve_permission_rule_store,
)
from magi.control.permission.provider import get_permission_gateway


class _FakeRuntimePaths:
    def __init__(self, base: Path) -> None:
        self.runtime_dir = base
        # permission_rules schema is alembic-owned; production migrates at
        # boot (DatabaseMigrationModule) before the control plane starts.
        from alembic import command

        from magi.db.runner import MIGRATION_TARGETS, _build_config

        target = next(t for t in MIGRATION_TARGETS if t.name == "permission_rules")
        command.upgrade(_build_config(target, base / "permission_rules.db"), "head")


@pytest.mark.asyncio
async def test_control_plane_module_wires_all_singletons(tmp_path: Path) -> None:
    context = RuntimeBootstrapContext()
    context.core.runtime_paths = _FakeRuntimePaths(tmp_path)

    module = ControlPlaneModule(context)
    try:
        await module.init()

        wiring = module.wiring
        assert wiring is not None
        assert isinstance(wiring.settings_manager, ControlSettingsManager)
        assert isinstance(wiring.rule_store, PermissionRuleStore)
        assert isinstance(wiring.broker, InteractionBroker)
        assert isinstance(wiring.session_store, ControlSessionStore)
        assert isinstance(wiring.gateway, PermissionGateway)
        assert isinstance(
            wiring.user_content_clear,
            ControlUserContentClearCoordinator,
        )

        # All DI bindings resolve to the same instances.
        assert resolve_control_session_store() is wiring.session_store
        assert resolve_control_settings_manager() is wiring.settings_manager
        assert resolve_control_interaction_broker() is wiring.broker
        assert resolve_permission_rule_store() is wiring.rule_store
        assert get_permission_gateway() is wiring.gateway
        assert resolve_pending_permission_registry() is wiring.pending_permissions

        # The gateway now has a prompter attached: brokered prompter
        # that records to the shared pending-permissions registry.
        assert wiring.gateway._prompter is not None  # type: ignore[attr-defined]

        # Plan-mode guard is wired: the gateway refuses write tools
        # once the session's plan mode is active.
        await wiring.session_store.enter_plan_mode("sid-1")
        decision = await wiring.gateway.gate(
            tool_name="bash",
            arguments={"command": "ls"},
            agent_id="chat",
            session_id="sid-1",
            origin=ToolOrigin.CHAT,
            tool_is_dangerous=True,
        )
        assert decision.outcome is PermissionOutcome.DENIED
        assert decision.source == "plan_mode"

        # The permission_rules.db was created under runtime_dir.
        assert (tmp_path / "permission_rules.db").exists()
    finally:
        await module.shutdown()

    # After shutdown, DI overrides are cleared.
    container = get_container()
    with pytest.raises(RuntimeError):
        get_permission_gateway()
    # Tidy: make sure container providers really reset.
    assert not container.permission_gateway.overridden


@pytest.mark.asyncio
async def test_control_plane_module_without_runtime_paths_uses_inmemory_rules(
    tmp_path: Path,
) -> None:
    context = RuntimeBootstrapContext()  # no runtime paths
    module = ControlPlaneModule(context)
    try:
        await module.init()
        # Rules are in-memory only; adding + listing works.
        store = resolve_permission_rule_store()
        rules = store.list_rules(session_id=None)
        assert rules == []
    finally:
        await module.shutdown()
