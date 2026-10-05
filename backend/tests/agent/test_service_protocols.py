from __future__ import annotations

import ast
import inspect
from importlib.util import resolve_name

import pytest


def _chat_imports(source, package):
    dependencies = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            dependencies.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = resolve_name("." * node.level + (node.module or ""), package) if node.level else node.module or ""
            dependencies.extend(module + "." + alias.name for alias in node.names)
    return [name for name in dependencies if name == "magi.chat" or name.startswith("magi.chat.")]


def test_execution_handlers_depend_on_protocols_without_importing_chat_domain():
    from magi.agent.task_agents.handlers import handlers
    assert _chat_imports(inspect.getsource(handlers), handlers.__package__) == []


@pytest.mark.parametrize("source", [
    "from magi.chat.task_agent.prompt_service import ChatPromptService as Service",
    "import magi.chat.task_agent.prompt_service as prompts",
    "from magi import chat",
    "from ....chat.task_agent import prompt_service",
])
def test_import_boundary_detects_direct_relative_and_module_aliases(source):
    assert _chat_imports(source, "magi.agent.task_agents.handlers")
