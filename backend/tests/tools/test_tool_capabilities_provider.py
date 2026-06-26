"""Tool capability provider boundary tests."""

from __future__ import annotations

import ast
from pathlib import Path

from magi_plugin_sdk.capabilities import ToolCapabilities


def test_runtime_modules_do_not_import_bootstrap_tool_capabilities() -> None:
    source_root = Path(__file__).parents[2] / "src" / "magi"
    offenders: list[str] = []

    for path in source_root.rglob("*.py"):
        relative = path.relative_to(source_root)
        if relative.parts[0] == "bootstrap":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module == "magi.bootstrap.tool_capabilities":
                offenders.append(f"{relative}:{node.lineno}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "magi.bootstrap.tool_capabilities":
                        offenders.append(f"{relative}:{node.lineno}")

    assert offenders == []


def test_tool_capabilities_provider_defaults_to_empty_sdk_bundle() -> None:
    from magi.tools.capabilities import build_tool_capabilities, reset_tool_capabilities_provider

    reset_tool_capabilities_provider()

    capabilities = build_tool_capabilities()

    assert isinstance(capabilities, ToolCapabilities)
    assert capabilities.trace is None
    assert capabilities.chat is None


def test_tool_capabilities_provider_returns_registered_bundle() -> None:
    from magi.tools.capabilities import (
        build_tool_capabilities,
        configure_tool_capabilities_provider,
        reset_tool_capabilities_provider,
    )

    capabilities = ToolCapabilities()
    reset_tool_capabilities_provider()
    configure_tool_capabilities_provider(lambda: capabilities)

    try:
        assert build_tool_capabilities() is capabilities
    finally:
        reset_tool_capabilities_provider()
