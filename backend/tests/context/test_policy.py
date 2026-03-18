from __future__ import annotations

import unittest

from magi.context.policy import ContextPolicy


class TestContextPolicy(unittest.TestCase):
    def test_default_implicit_context_is_l0_only(self) -> None:
        decision = ContextPolicy().decide(
            user_message="今天天气怎么样",
            task_category="chat",
        )

        self.assertTrue(decision.retrieve_implicit_memory)
        self.assertEqual(decision.retrieval_query, "今天天气怎么样")
        self.assertEqual(decision.allowed_layers, ("L0",))

    def test_procedural_phrase_allows_l4_injection(self) -> None:
        decision = ContextPolicy().decide(
            user_message="按之前那套流程修一下这个 bug",
            task_category="code_execution",
        )

        self.assertTrue(decision.retrieve_implicit_memory)
        self.assertEqual(decision.allowed_layers, ("L0", "L4"))
