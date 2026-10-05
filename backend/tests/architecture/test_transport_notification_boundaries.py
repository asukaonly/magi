"""Enforce notification and retrieval ownership using resolved imports."""

from __future__ import annotations

import ast
from importlib.util import resolve_name
from pathlib import Path

import pytest

_BACKEND_SRC = Path(__file__).resolve().parents[2] / "src"


def _imported_names(source: str, module_name: str, *, is_package: bool = False):
    package = module_name if is_package else module_name.rpartition(".")[0]
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                module = resolve_name("." * node.level + module, package)
            yield module, node.lineno
            for alias in node.names:
                if alias.name != "*":
                    yield f"{module}.{alias.name}", node.lineno


def _boundary_violations(root: Path, targets, forbidden):
    violations = set()
    for target in targets:
        base = root / target
        paths = [base] if base.suffix == ".py" else sorted(base.rglob("*.py"))
        for path in paths:
            relative = path.relative_to(root)
            parts = list(relative.with_suffix("").parts)
            is_package = parts[-1] == "__init__"
            if is_package:
                parts.pop()
            for imported, line in _imported_names(path.read_text(encoding="utf-8"), ".".join(parts), is_package=is_package):
                if any(imported == name or imported.startswith(name + ".") for name in forbidden):
                    violations.add(f"{relative}:{line}: {imported}")
    return sorted(violations)


@pytest.mark.parametrize("targets,forbidden", [
    (("magi/api", "magi/chat", "magi/agent"), ("magi.transport.chat_events", "transport.chat_events")),
    (("magi/chat",), ("magi.channels", "channels")),
    (("magi/chat",), tuple(f"magi.agent.run.{name}" for name in ("builder", "nodes", "registry", "runner", "spec"))),
    (("magi/api/routes.py",), ("magi.transport", "transport")),
    (("magi/chat/task_agent/prompt_service.py",), ("magi.memory.provider", "magi.memory.get_unified_memory", "magi.memory.hybrid_retrieval")),
], ids=["transport-notifications", "channel-ownership", "agent-run-internals", "api-transport", "retrieval-owner"])
def test_production_imports_preserve_runtime_ownership(targets, forbidden):
    assert _boundary_violations(_BACKEND_SRC, targets, forbidden) == []


@pytest.mark.parametrize("source,blocked", [
    ("import magi.transport.chat_events as events", True),
    ("from magi.transport import chat_events as events", True),
    ("from ...transport import chat_events as events", True),
    ("from ...transport.chat_events import publish", True),
    ("from ...agent.run import runner as run", True),
    ("from ...agent.run.runner import Runner", True),
    ("from magi import channels as external", True),
    ("from ... import channels", True),
    ("from ...memory.provider import get_unified_memory as memory", True),
    ("from ...memory.hybrid_retrieval import build_query as query", True),
    ('# from magi.transport import chat_events\ntext = "magi.agent.run.runner"', False),
    ("from . import message_notifications", False),
])
@pytest.mark.parametrize("package_file", [False, True])
def test_boundary_checker_handles_import_spelling_and_ignores_prose(tmp_path, source, blocked, package_file):
    relative = "magi/chat/task_agent/__init__.py" if package_file else "magi/chat/task_agent/service.py"
    path = tmp_path / relative
    path.parent.mkdir(parents=True)
    path.write_text(source, encoding="utf-8")
    violations = _boundary_violations(tmp_path, (relative,), ("magi.transport.chat_events", "magi.agent.run.runner", "magi.channels", "magi.memory.provider", "magi.memory.hybrid_retrieval"))
    assert bool(violations) is blocked
    if blocked:
        assert all(item.startswith(relative + ":1:") for item in violations)
