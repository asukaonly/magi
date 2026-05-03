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
async def test_mcp_module_loads_disabled_server(tmp_path):
    """Server with autostart=true but enabled=false should not run."""
    set_runtime_dir(tmp_path)
    cfg_dir = tmp_path / "config" / "mcp"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "demo.toml").write_text(
        """
[server]
id = "demo"
name = "Demo"
enabled = false
autostart = true

[transport]
kind = "stdio"
command = "x"
"""
    )
    try:
        module = MCPModule(RuntimeBootstrapContext())
        await module.init()
        try:
            mgr = get_active_manager()
            assert mgr is not None
            assert len(mgr.list_configs()) == 1
            assert mgr.is_running("demo") is False
        finally:
            await module.shutdown()
    finally:
        from magi.utils import runtime as rt_mod
        rt_mod._runtime_paths = None

