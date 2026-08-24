"""Structural-match tests for the ring-2 service protocols.

Task 1 of the P2 refactor inverts ``ChatHandlerDependencies`` typing so the
generic run-loop handlers depend on ring-2 ``Protocol`` surfaces instead of
the concrete chat service classes. These tests pin the structural contract:
the concrete chat services must remain valid implementations of the protocols
(so construction sites keep passing them unchanged), and the dependency
bundle must no longer import any concrete chat service class.
"""
from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path

from magi.agent.task_agents.common.service_protocols import (
    HistoryServiceProtocol,
    PromptServiceProtocol,
)
from magi.chat.task_agent.context_assembler import ChatContextAssembler
from magi.chat.task_agent.prompt_service import ChatPromptService


class TestPromptServiceProtocol(unittest.TestCase):
    def test_chat_prompt_service_is_structural_match(self) -> None:
        service = ChatPromptService(llm_adapter=None, llm_pool=None)
        self.assertIsInstance(service, PromptServiceProtocol)

    def test_protocol_surface_is_exactly_the_unified_loop_methods(self) -> None:
        expected = {
            "call_llm",
            "call_llm_stream",
            "augment_system_prompt_with_reply_context",
        }
        members = {
            name
            for name in dir(PromptServiceProtocol)
            if not name.startswith("_")
        }
        self.assertEqual(members, expected)


class TestHistoryServiceProtocol(unittest.TestCase):
    def test_chat_context_assembler_is_structural_match(self) -> None:
        # __init__ only stores the path (it does not open the DB), so a bare
        # temp path is enough to build an instance for the structural check.
        service = ChatContextAssembler(l1_db_path=Path("/tmp/magi-test-l1.db"))
        self.assertIsInstance(service, HistoryServiceProtocol)


class TestDependencyBundleImports(unittest.TestCase):
    def test_handlers_module_imports_no_concrete_chat_service(self) -> None:
        from magi.agent.task_agents.handlers import handlers as handlers_module

        handlers_path = Path(inspect.getfile(handlers_module))
        tree = ast.parse(handlers_path.read_text())
        imported_names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    imported_names.add(alias.name)
        for forbidden in (
            "ChatPromptService",
            "ChatPlanningService",
            "ChatContextAssembler",
        ):
            self.assertNotIn(
                forbidden,
                imported_names,
                f"{forbidden} must not be imported by the dependency bundle",
            )


if __name__ == "__main__":
    unittest.main()
