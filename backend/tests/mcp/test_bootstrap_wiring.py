"""Smoke test: MCPModule initializes against an empty config dir."""

import pytest

from magi.bootstrap.context import RuntimeBootstrapContext
from magi.mcp.lifecycle import MCPModule, get_active_manager
from magi.utils.runtime import set_runtime_dir


@pytest.mark.asyncio
async def test_mcp_module_with_empty_config(tmp_path):
    set_runtime_dir(tmp_path)
    try:
        ctx = RuntimeBootstrapContext()
        module = MCPModule(ctx)
        await module.init()
        try:
            mgr = get_active_manager()
            assert mgr is not None
            assert mgr.list_configs() == []
            assert (tmp_path / "config" / "mcp").is_dir()
        finally:
            await module.shutdown()
        assert get_active_manager() is None
    finally:
        from magi.utils import runtime as rt_mod
        rt_mod._runtime_paths = None


@pytest.mark.asyncio
async def test_autostart_dispatches_only_enabled_opted_in_servers(tmp_path, monkeypatch):
    import asyncio
    import json
    import sys
    from unittest.mock import AsyncMock
    from magi.mcp.manager import MCPManager
    from magi.mcp import lifecycle

    set_runtime_dir(tmp_path)
    directory = tmp_path / "config" / "mcp"
    directory.mkdir(parents=True, exist_ok=True)
    for server_id, enabled, autostart in [
        ("disabled", False, True),
        ("enabled", True, True),
        ("manual", True, False),
    ]:
        (directory / f"{server_id}.toml").write_text(
            f'[server]\nid = "{server_id}"\nname = "{server_id}"\nenabled = {str(enabled).lower()}\nautostart = {str(autostart).lower()}\n[transport]\nkind = "stdio"\ncommand = {json.dumps(sys.executable)}\nargs = ["-c", "pass"]\n'
        )
    manager = MCPManager(registry=object())
    entered = asyncio.Event()
    release = asyncio.Event()

    async def start(server_id):
        entered.set()
        await release.wait()

    manager.start_server = AsyncMock(side_effect=start)
    monkeypatch.setattr(lifecycle, "MCPManager", lambda **kwargs: manager)
    module = MCPModule(RuntimeBootstrapContext())
    try:
        await module.init()
        assert get_active_manager() is manager
        assert {config.server.id for config in manager.list_configs()} == {
            "disabled",
            "enabled",
            "manual",
        }
        await asyncio.wait_for(entered.wait(), 2)
        assert module._autostart_task is not None and not module._autostart_task.done()
        release.set()
        await asyncio.wait_for(module._autostart_task, 2)
        manager.start_server.assert_awaited_once_with("enabled")
    finally:
        release.set()
        await module.shutdown()
    assert get_active_manager() is None
