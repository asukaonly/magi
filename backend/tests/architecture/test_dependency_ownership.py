"""Declared import edges at runtime ownership boundaries."""
import ast
from importlib.util import resolve_name
from pathlib import Path
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"

def imported_names(source, *, package):
    imports = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = resolve_name("." * node.level + (node.module or ""), package) if node.level else node.module or ""
            imports.add(base)
            imports.update(f"{base}.{alias.name}" for alias in node.names)
    return imports

@pytest.mark.parametrize("source,package,expected", [
    ("from magi import llm as model", "magi.memory.portrait", "magi.llm"),
    ("from ... import llm as model", "magi.memory.portrait", "magi.llm"),
    ("import magi.llm as model", "magi.memory.portrait", "magi.llm"),
    ("# from magi import llm\nLABEL = 'magi.llm'", "magi.memory.portrait", None),
])
def test_import_edges_resolve_aliases_and_ignore_text(source, package, expected):
    edges = imported_names(source, package=package)
    assert ("magi.llm" in edges) == (expected is not None)

@pytest.mark.parametrize("target,forbidden", [
    ("magi/memory/manual_entries/application.py", ("magi.api", "fastapi", "magi.core.container")),
    ("magi/memory/portrait", ("magi.chat", "magi.personality", "magi.llm", "magi.config", "magi.api")),
    ("magi/chat/task_agent/runtime_dependencies.py", ("magi.core.container", "magi.bootstrap.context", "magi.core.runtime_bootstrap_context")),
    ("magi/chat/task_agent/runtime_execution_builder.py", ("magi.runtime_trace.chat_trace.read_service",)),
    ("magi/api/services/__init__.py", ("magi.events.service_access", "magi.skills.service_access", "magi.personality.current_state")),
])
def test_declared_imports_respect_owning_layers(target, forbidden):
    root = SRC / target
    files = sorted(root.rglob("*.py")) if root.is_dir() else [root]
    assert files and all(path.is_file() for path in files)
    violations = []
    for path in files:
        parts = path.relative_to(SRC).with_suffix("").parts
        package = ".".join(parts[:-1])
        for imported in imported_names(path.read_text(), package=package):
            if any(imported == prefix or imported.startswith(prefix + ".") for prefix in forbidden):
                violations.append((str(path.relative_to(SRC)), imported))
    assert violations == []


def test_api_dependencies_do_not_traverse_bootstrap_context():
    violations = []
    for path in (SRC / "magi/api").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (isinstance(node, ast.Attribute) and node.attr == "runtime_bootstrap_context") or (
                isinstance(node, ast.Constant) and node.value == "runtime_bootstrap_context"
            ):
                violations.append(str(path.relative_to(SRC)))
    assert violations == []


def test_core_runtime_bindings_only_expose_runtime_roots():
    tree = ast.parse((SRC / "magi/core/runtime_bindings.py").read_text())
    assert {node.name for node in tree.body if isinstance(node, ast.FunctionDef)} == {
        "require_runtime_command_queue", "require_agent_runtime", "get_optional_agent_runtime",
    }
