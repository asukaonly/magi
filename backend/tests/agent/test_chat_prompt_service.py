from __future__ import annotations

import unittest

from magi.chat.task_agent.prompt_service import ChatPromptService
from magi.agent.task_agents.common.service_protocols import PromptServiceProtocol


class TestChatPromptService(unittest.TestCase):
    def test_augment_working_context_includes_recent_tool_state_block(self) -> None:
        service: PromptServiceProtocol = ChatPromptService(llm_adapter=None, llm_pool=None)

        self.assertIsInstance(service, PromptServiceProtocol)
        prompt = service.augment_working_context_with_reply_context(
            working_context="BASE WORKING CONTEXT",
            reply_context=None,
            recent_tool_state=[
                {
                    "tool_name": "photo_library_resolve_photo_refs",
                    "status": "success",
                    "execution_time_ms": 842,
                    "outcome": "Resolved 2 photo assets",
                    "handles": ["asset_ref_id:abc"],
                }
            ],
        )

        self.assertIn("# Recent Tool State", prompt)
        self.assertIn("photo_library_resolve_photo_refs", prompt)
        self.assertIn("duration_ms=842", prompt)
        self.assertIn("trace_query", prompt)
