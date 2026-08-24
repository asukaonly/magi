from __future__ import annotations

from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from unittest.mock import patch

from magi.context import ContextAssemblyService, PromptContextAssembler, PromptContextRenderer
from magi.personality.loader import PersonalityConfig
from magi.personality.models import EmotionalState
from magi.utils.runtime import RuntimePaths


class _FakeMemory:
    personality_name = "default"

    async def get_core_personality(self):
        return PersonalityConfig()

    async def get_emotional_state(self):
        return EmotionalState(
            current_mood="focused", mood_intensity=0.8, energy_level=0.7, stress_level=0.2
        )

    async def get_relationship(self, user_id: str):
        _ = user_id
        return {"sentiment_score": 0.2, "trust_level": 0.6}

    async def get_milestones(self, limit: int = 200):
        _ = limit
        return []


class TestContextAssemblyService(unittest.IsolatedAsyncioTestCase):
    async def test_build_prompt_package_can_disable_implicit_memory_retrieval(self):
        retrieval_memory_provider = AsyncMock(return_value=self._empty_retrieval_payload())
        service = ContextAssemblyService(
            agent_id="chat-agent",
            agent_type="chat",
            prompt_context_assembler=PromptContextAssembler(),
            prompt_context_renderer=PromptContextRenderer(),
            memory=_FakeMemory(),
            retrieval_memory_provider=retrieval_memory_provider,
        )

        package = await service.build_prompt_package(
            user_id="u1",
            session_id="s1",
            user_message="Recheck the previous memory answer",
            task_category="recall_feedback_correction",
            tools=[],
            allow_implicit_memory=False,
        )

        retrieval_memory_provider.assert_not_awaited()
        self.assertEqual(package.memory_availability, "available")
        self.assertEqual(package.memory_retrieval_status, "bypassed")
        self.assertEqual(
            package.prompt_context.self_memory.retrieval_memory.l0_workbench,
            [],
        )

    async def test_build_prompt_package_exposes_unavailable_memory_without_failing_turn(self):
        service = ContextAssemblyService(
            agent_id="chat-agent",
            agent_type="chat",
            prompt_context_assembler=PromptContextAssembler(),
            prompt_context_renderer=PromptContextRenderer(),
            memory=_FakeMemory(),
            retrieval_memory_provider=None,
        )

        package = await service.build_prompt_package(
            user_id="u1",
            session_id="s1",
            user_message="What did we discuss yesterday?",
            task_category="chat",
            tools=[],
        )

        self.assertEqual(package.memory_availability, "unavailable")
        self.assertEqual(package.memory_retrieval_status, "unavailable")
        self.assertEqual(
            package.prompt_context.self_memory.retrieval_memory.l0_workbench,
            [],
        )

    async def test_build_prompt_package_degrades_retrieval_failure_to_unavailable(self):
        retrieval_memory_provider = AsyncMock(side_effect=RuntimeError("storage offline"))
        service = ContextAssemblyService(
            agent_id="chat-agent",
            agent_type="chat",
            prompt_context_assembler=PromptContextAssembler(),
            prompt_context_renderer=PromptContextRenderer(),
            memory=_FakeMemory(),
            retrieval_memory_provider=retrieval_memory_provider,
        )

        package = await service.build_prompt_package(
            user_id="u1",
            session_id="s1",
            user_message="What did we discuss yesterday?",
            task_category="chat",
            tools=[],
        )

        self.assertEqual(package.memory_availability, "unavailable")
        self.assertEqual(package.memory_retrieval_status, "failed")

    async def test_build_prompt_package_uses_user_message_for_retrieval_query(self):
        retrieval_memory_provider = AsyncMock(
            return_value={
                "l0_workbench": [
                    {
                        "session": {"session_id": "s1"},
                        "attention_items": [
                            {
                                "kind": "focus",
                                "summary": "The user is revisiting a refactor discussion.",
                                "status": "active",
                                "evidence_mode": "direct",
                            }
                        ],
                    }
                ],
                "l2_entity_cards": [{"entity_id": "user:u1"}],
                "l3_reflection_memory": [{"summary": "User wants to switch jobs"}],
                "l4_procedural_memory": [{"skill_name": "browser.open"}],
                "preference_memory": {},
            }
        )
        service = ContextAssemblyService(
            agent_id="chat-agent",
            agent_type="chat",
            prompt_context_assembler=PromptContextAssembler(),
            prompt_context_renderer=PromptContextRenderer(),
            memory=_FakeMemory(),
            retrieval_memory_provider=retrieval_memory_provider,
        )

        package = await service.build_prompt_package(
            user_id="u1",
            session_id="s1",
            user_message="帮我回忆昨天聊过的重构方案",
            task_category="chat",
            tools=[],
            recent_tool_errors=[
                {
                    "tool_name": "memory_query",
                    "error_code": "TIMEOUT",
                    "error_message": "request timed out",
                }
            ],
        )

        retrieval_memory_provider.assert_awaited_once_with(
            user_id="u1",
            session_id="s1",
            query="帮我回忆昨天聊过的重构方案",
            task_category="chat",
            context_text="帮我回忆昨天聊过的重构方案",
            workspace_path=None,
            allowed_layers=("L0",),
        )
        self.assertIn("# Recent Tool Errors", package.system_prompt)
        self.assertEqual(
            package.prompt_context.self_memory.retrieval_memory.l0_workbench[0][
                "attention_items"
            ][0]["kind"],
            "focus",
        )

    async def test_build_prompt_package_allows_l4_only_for_procedural_opt_in(self):
        retrieval_memory_provider = AsyncMock(
            return_value={
                "l0_workbench": [
                    {
                        "session": {"session_id": "s1"},
                        "attention_items": [
                            {
                                "kind": "focus",
                                "summary": "The user is fixing the current bug.",
                                "status": "active",
                                "evidence_mode": "direct",
                            }
                        ],
                    }
                ],
                "l2_entity_cards": [],
                "l3_reflection_memory": [],
                "l4_procedural_memory": [{"skill_name": "repo_fix_flow"}],
                "preference_memory": {},
            }
        )
        service = ContextAssemblyService(
            agent_id="chat-agent",
            agent_type="chat",
            prompt_context_assembler=PromptContextAssembler(),
            prompt_context_renderer=PromptContextRenderer(),
            memory=_FakeMemory(),
            retrieval_memory_provider=retrieval_memory_provider,
        )

        package = await service.build_prompt_package(
            user_id="u1",
            session_id="s1",
            user_message="按之前那套流程修一下这个 bug",
            task_category="code_execution",
            tools=[],
        )

        retrieval_memory_provider.assert_awaited_once_with(
            user_id="u1",
            session_id="s1",
            query="按之前那套流程修一下这个 bug",
            task_category="code_execution",
            context_text="按之前那套流程修一下这个 bug",
            workspace_path=None,
            allowed_layers=("L0", "L4"),
        )
        retrieval = package.prompt_context.self_memory.retrieval_memory
        self.assertEqual(retrieval.l4_procedural_memory[0]["skill_name"], "repo_fix_flow")

    async def test_build_prompt_package_uses_session_workspace_path_when_available(self):
        retrieval_memory_provider = AsyncMock(return_value=self._empty_retrieval_payload())
        session_workspace_provider = AsyncMock(return_value="/tmp/magi")
        service = ContextAssemblyService(
            agent_id="chat-agent",
            agent_type="chat",
            prompt_context_assembler=PromptContextAssembler(),
            prompt_context_renderer=PromptContextRenderer(),
            memory=_FakeMemory(),
            retrieval_memory_provider=retrieval_memory_provider,
            session_workspace_provider=session_workspace_provider,
        )

        package = await service.build_prompt_package(
            user_id="u1",
            session_id="s1",
            user_message="看一下当前项目目录",
            task_category="chat",
            tools=[],
        )

        session_workspace_provider.assert_awaited_once_with(user_id="u1", session_id="s1")
        self.assertEqual(package.prompt_context.runtime_system.cwd, "/tmp/magi")
        self.assertIn("* Working Directory: /tmp/magi", package.system_prompt)

    async def test_build_prompt_package_uses_stored_persona_id_for_prompt_identity(self):
        persona_config = PersonalityConfig.from_dict(
            {
                "name": "Pinned Persona",
                "identity_core": {
                    "identity_statement": "Pinned identity should drive this queued turn.",
                },
                "registers": {
                    "chat": {
                        "description": "Pinned chat",
                        "behavior": "Answer as the pinned persona.",
                    },
                },
            }
        )
        persona_lookup = AsyncMock(
            return_value=SimpleNamespace(
                persona_id="persona-pinned",
                slug="pinned_persona",
                config=persona_config,
            )
        )
        service = ContextAssemblyService(
            agent_id="chat-agent",
            agent_type="chat",
            prompt_context_assembler=PromptContextAssembler(),
            prompt_context_renderer=PromptContextRenderer(),
            memory=_FakeMemory(),
            retrieval_memory_provider=AsyncMock(return_value=self._empty_retrieval_payload()),
            persona_lookup=persona_lookup,
        )

        package = await service.build_prompt_package(
            user_id="u1",
            session_id="s1",
            user_message="queued turn",
            task_category="chat",
            tools=[],
            persona_id="persona-pinned",
        )

        persona_lookup.assert_awaited_once_with("persona-pinned")
        self.assertEqual(package.prompt_context.metadata["persona_id"], "persona-pinned")
        self.assertIn("Pinned Persona", package.system_prompt)
        self.assertIn("Pinned identity should drive this queued turn.", package.system_prompt)

    async def test_build_prompt_package_falls_back_to_managed_default_workspace(self):
        retrieval_memory_provider = AsyncMock(return_value=self._empty_retrieval_payload())
        managed_workspace = Path.cwd() / ".tmp-managed-chat-workspace"
        managed_workspace.mkdir(parents=True, exist_ok=True)
        self.addCleanup(lambda: managed_workspace.rmdir() if managed_workspace.exists() else None)
        service = ContextAssemblyService(
            agent_id="chat-agent",
            agent_type="chat",
            prompt_context_assembler=PromptContextAssembler(),
            prompt_context_renderer=PromptContextRenderer(),
            memory=_FakeMemory(),
            retrieval_memory_provider=retrieval_memory_provider,
        )

        with patch(
            "magi.context.assembler.get_default_chat_workspace_path",
            return_value=str(managed_workspace),
        ):
            package = await service.build_prompt_package(
                user_id="u1",
                session_id="s1",
                user_message="看一下默认目录",
                task_category="chat",
                tools=[],
            )

        self.assertEqual(package.prompt_context.runtime_system.cwd, str(managed_workspace))
        self.assertIn(f"* Working Directory: {managed_workspace}", package.system_prompt)

    async def test_build_prompt_package_renders_active_text_and_pdf_attachments(self):
        retrieval_memory_provider = AsyncMock(return_value=self._empty_retrieval_payload())
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        runtime_paths = RuntimePaths(Path(temp_dir.name) / "runtime")
        text_path = (
            runtime_paths.chat_derived_dir / "s1" / "turn-1" / "att-text.txt"
        )
        pdf_path = (
            runtime_paths.chat_derived_dir / "s1" / "turn-1" / "att-pdf.txt"
        )
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text("Alpha\nBeta\n", encoding="utf-8")
        pdf_path.write_text("Quarterly summary", encoding="utf-8")

        service = ContextAssemblyService(
            agent_id="chat-agent",
            agent_type="chat",
            prompt_context_assembler=PromptContextAssembler(),
            prompt_context_renderer=PromptContextRenderer(),
            memory=_FakeMemory(),
            retrieval_memory_provider=retrieval_memory_provider,
        )

        with patch(
            "magi.core.chat_assets.paths.get_runtime_paths",
            return_value=runtime_paths,
        ):
            package = await service.build_prompt_package(
                user_id="u1",
                session_id="s1",
                user_message="帮我总结附件",
                task_category="chat",
                tools=[],
                attachments=[
                    {
                        "attachment_id": "att-text",
                        "session_id": "s1",
                        "turn_id": "turn-1",
                        "kind": "text_file",
                        "original_name": "notes.md",
                        "parse_status": "parsed",
                        "derived_text_path": str(text_path),
                        "character_count": 11,
                        "truncated": False,
                    },
                    {
                        "attachment_id": "att-pdf",
                        "session_id": "s1",
                        "turn_id": "turn-1",
                        "kind": "pdf",
                        "original_name": "report.pdf",
                        "parse_status": "parsed",
                        "derived_text_path": str(pdf_path),
                        "character_count": 17,
                        "truncated": False,
                        "page_count": 2,
                    },
                ],
            )

        self.assertIn("# Active Attachments", package.system_prompt)
        self.assertIn("notes.md", package.system_prompt)
        self.assertIn("Alpha\nBeta", package.system_prompt)
        self.assertIn("report.pdf", package.system_prompt)
        self.assertIn("Quarterly summary", package.system_prompt)

    async def test_build_prompt_package_prefers_full_attachment_text_over_excerpt(self):
        retrieval_memory_provider = AsyncMock(return_value=self._empty_retrieval_payload())
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        runtime_paths = RuntimePaths(Path(temp_dir.name) / "runtime")
        text_path = (
            runtime_paths.chat_derived_dir / "s1" / "turn-1" / "att-text.txt"
        )
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text("First line\nSecond line\nFinal line", encoding="utf-8")

        service = ContextAssemblyService(
            agent_id="chat-agent",
            agent_type="chat",
            prompt_context_assembler=PromptContextAssembler(),
            prompt_context_renderer=PromptContextRenderer(),
            memory=_FakeMemory(),
            retrieval_memory_provider=retrieval_memory_provider,
        )

        with patch(
            "magi.core.chat_assets.paths.get_runtime_paths",
            return_value=runtime_paths,
        ):
            package = await service.build_prompt_package(
                user_id="u1",
                session_id="s1",
                user_message="完整看看附件",
                task_category="chat",
                tools=[],
                attachments=[
                    {
                        "attachment_id": "att-text",
                        "session_id": "s1",
                        "turn_id": "turn-1",
                        "kind": "text_file",
                        "original_name": "notes.md",
                        "parse_status": "parsed",
                        "derived_text_excerpt": "First line",
                        "derived_text_path": str(text_path),
                        "character_count": len("First line\nSecond line\nFinal line"),
                        "truncated": False,
                    },
                ],
            )

        self.assertIn("First line\nSecond line\nFinal line", package.system_prompt)
        self.assertNotIn("```text\nFirst line\n```", package.system_prompt)

    async def test_build_prompt_package_does_not_read_derived_text_outside_chat_storage(
        self,
    ):
        retrieval_memory_provider = AsyncMock(return_value=self._empty_retrieval_payload())
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        runtime_paths = RuntimePaths(Path(temp_dir.name) / "runtime")
        outside = runtime_paths.base_dir / "private.txt"
        outside.write_text("PRIVATE OUTSIDE TEXT", encoding="utf-8")
        service = ContextAssemblyService(
            agent_id="chat-agent",
            agent_type="chat",
            prompt_context_assembler=PromptContextAssembler(),
            prompt_context_renderer=PromptContextRenderer(),
            memory=_FakeMemory(),
            retrieval_memory_provider=retrieval_memory_provider,
        )

        with patch(
            "magi.core.chat_assets.paths.get_runtime_paths",
            return_value=runtime_paths,
        ):
            package = await service.build_prompt_package(
                user_id="u1",
                session_id="s1",
                user_message="看看附件",
                task_category="chat",
                tools=[],
                attachments=[
                    {
                        "attachment_id": "att-text",
                        "session_id": "s1",
                        "turn_id": "turn-1",
                        "kind": "text_file",
                        "original_name": "notes.md",
                        "parse_status": "parsed",
                        "derived_text_path": str(outside),
                    }
                ],
            )

        self.assertNotIn("PRIVATE OUTSIDE TEXT", package.system_prompt)

    @staticmethod
    def _empty_retrieval_payload() -> dict[str, object]:
        return {
            "l0_workbench": [],
            "l2_entity_cards": [],
            "l3_reflection_memory": [],
            "l4_procedural_memory": [],
            "preference_memory": {},
        }
