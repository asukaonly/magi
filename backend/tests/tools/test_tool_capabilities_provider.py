"""Tool capability provider boundary tests."""

from __future__ import annotations

from pathlib import Path

from _shared.source_imports import imported_names
from magi.core.tool_capabilities import ToolCapabilities


def test_runtime_modules_do_not_import_bootstrap_tool_capabilities() -> None:
    source_root = Path(__file__).parents[2] / "src" / "magi"
    offenders: list[str] = []

    for path in source_root.rglob("*.py"):
        relative = path.relative_to(source_root)
        if relative.parts[0] == "bootstrap":
            continue
        source = path.read_text(encoding="utf-8-sig")
        # Every spelling of this declared import includes the module identifier.
        if "tool_capabilities" not in source:
            continue
        parts = relative.with_suffix("").parts
        package = ".".join(("magi", *parts[:-1]))
        if "magi.bootstrap.tool_capabilities" in imported_names(source, package=package):
            offenders.append(str(relative))

    assert offenders == []


def test_capability_provider_reset_removes_previously_registered_host_bundle():
    from magi.tools.capabilities import (
        build_tool_capabilities,
        configure_tool_capabilities_provider,
        reset_tool_capabilities_provider,
    )
    from types import SimpleNamespace

    reset_tool_capabilities_provider()
    before = build_tool_capabilities()
    assert isinstance(before, ToolCapabilities)
    assert before.trace is None and before.chat is None
    host_chat = SimpleNamespace()
    registered = ToolCapabilities(chat=host_chat)
    configure_tool_capabilities_provider(lambda: registered)
    try:
        assert build_tool_capabilities() is registered
        assert build_tool_capabilities().chat is host_chat
    finally:
        reset_tool_capabilities_provider()
    after = build_tool_capabilities()
    assert isinstance(after, ToolCapabilities)
    assert after.chat is None and after.trace is None
    assert after is not registered
