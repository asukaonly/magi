"""Boundary tests for transport-owned notification responsibilities."""

from __future__ import annotations

import ast
from pathlib import Path


_BACKEND_SRC = Path(__file__).resolve().parents[2] / "src"
_FORBIDDEN_IMPORT_MODULES = {
    "magi.transport.chat_events",
    "transport.chat_events",
}


def _transport_chat_event_imports() -> list[str]:
    violations: list[str] = []
    for package in ("api", "chat", "agent"):
        for path in (_BACKEND_SRC / "magi" / package).rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in _FORBIDDEN_IMPORT_MODULES:
                            violations.append(f"{path.relative_to(_BACKEND_SRC)}:{node.lineno}")
                elif isinstance(node, ast.ImportFrom) and node.module in _FORBIDDEN_IMPORT_MODULES:
                    violations.append(f"{path.relative_to(_BACKEND_SRC)}:{node.lineno}")
    return sorted(violations)


def test_runtime_layers_do_not_reach_into_transport_chat_events() -> None:
    assert _transport_chat_event_imports() == []


def test_transport_exports_only_transport_assembly() -> None:
    import magi.transport as transport

    assert not hasattr(transport, "broadcast_chat_message_upsert")
    assert not hasattr(transport, "broadcast_chat_message_hidden")
    assert transport.__all__ == ["create_transport_app"]


def _chat_channel_imports() -> list[str]:
    violations: list[str] = []
    for path in (_BACKEND_SRC / "magi" / "chat").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "magi.channels" or alias.name.startswith("magi.channels."):
                        violations.append(f"{path.relative_to(_BACKEND_SRC)}:{node.lineno}")
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module == "magi.channels" or module.startswith("magi.channels."):
                    violations.append(f"{path.relative_to(_BACKEND_SRC)}:{node.lineno}")
                elif module == "magi" and any(alias.name == "channels" for alias in node.names):
                    violations.append(f"{path.relative_to(_BACKEND_SRC)}:{node.lineno}")
                elif module == "channels" or module.startswith("channels."):
                    violations.append(f"{path.relative_to(_BACKEND_SRC)}:{node.lineno}")
                elif not module and any(alias.name == "channels" for alias in node.names):
                    violations.append(f"{path.relative_to(_BACKEND_SRC)}:{node.lineno}")
    return sorted(violations)


def test_chat_layer_does_not_import_channels_layer() -> None:
    assert _chat_channel_imports() == []
