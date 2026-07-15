from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from magi.chat import ChatContextSummaryRecord, ChatMessageRecord, ChatStore
from magi.chat.read.models import ChatDisplayMessage
from magi.agent.orchestration import (
    OrchestrationStore,
    PlannedSubtask,
    SubtaskDefinition,
    SubtaskPlan,
    TaskOrchestrationState,
    WorkerResult,
)
from magi.chat.task_agent.context_assembler import ChatContextAssembler
from magi.agent.task_agents.handlers import ExecutionMode, ExecutionRequest, IntentDecision, OrchestrationPlan, ToolSelection
from magi.chat.task_agent import planning_service as planning_service_module
from magi.tools.context_routing import RouteDecision
from magi.chat.task_agent.chat_task_agent import ChatTaskAgent
from magi.agent.task_agents.explore_task_agent import EXPLORE_TASK_COMPLETED
from magi.agent.runtime.contracts import FactRecord
from magi.agent.runtime.types import TaskAgentType
from magi.context.contracts import PromptPackage
from magi.events.events import EventTypes


class _FakeLLMAdapter:
    model_name = "fake-model"
    supports_embeddings = False


@pytest.mark.asyncio
async def test_chat_task_agent_requires_explicit_session_id_for_user_messages() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    user_fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"content": "hello", "user_id": "u-chat"},
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id="corr_1",
    )

    merged = await agent.merge_facts([user_fact])

    with pytest.raises(ValueError, match="Session ID is required"):
        await agent.build_context(merged)


@pytest.mark.asyncio
async def test_chat_context_assembler_uses_explicit_session_pairs_without_state_file(tmp_path: Path, runtime_paths_with_schema) -> None:
    from magi.chat.read_service import ChatReadService

    isolated_read_service = ChatReadService()
    isolated_read_service._chat_db_path = runtime_paths_with_schema.chat_db_path
    isolated_read_service._l1_db_path = tmp_path / "l1.sqlite3"
    isolated_read_service._runtime_trace_db_path = tmp_path / "runtime_trace.sqlite3"

    service = ChatContextAssembler(
        l1_db_path=tmp_path / "l1.sqlite3",
        runtime_trace_db_path=tmp_path / "runtime_trace.sqlite3",
        chat_read_service_factory=lambda: isolated_read_service,
    )

    history = await service.get_or_load_history("u-chat", "s-chat")
    assert history == []

    key = service.history_key("u-chat", "s-chat")
    service.append_user_message(key, "hello")
    service.append_assistant_message(key, "world")

    assert service.get_conversation_history("u-chat", "s-chat") == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "world"},
    ]
    assert not (tmp_path / "chat_sessions.json").exists()


@pytest.mark.asyncio
async def test_chat_context_assembler_reloads_cache_when_history_version_changes(tmp_path: Path, runtime_paths_with_schema) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-1",
        message_text="hello",
        created_at_ms=100,
    )

    service = ChatContextAssembler(
        l1_db_path=tmp_path / "l1.sqlite3",
        runtime_trace_db_path=tmp_path / "runtime_trace.sqlite3",
        chat_store=chat_store,
        chat_read_service_factory=lambda: __import__("magi.chat.read_service", fromlist=["get_chat_read_service"]).get_chat_read_service(),
    )

    initial_history = await service.get_or_load_history("u-chat", "s-chat")
    assert initial_history == [{"role": "user", "content": "hello"}]

    await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-2",
        message_text="follow up",
        created_at_ms=200,
    )

    refreshed_history = await service.get_or_load_history("u-chat", "s-chat")

    assert refreshed_history == [
        {"role": "user", "content": "hello"},
        {"role": "user", "content": "follow up"},
    ]


@pytest.mark.asyncio
async def test_chat_context_assembler_loads_active_summary_context_and_tail(tmp_path: Path, runtime_paths_with_schema) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-1",
        message_text="original topic",
        attachment_payloads=[
            {
                "attachment_id": "attachment-old",
                "kind": "pdf",
                "original_name": "original.pdf",
            }
        ],
        created_at_ms=100,
    )
    second_message = await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-2",
        message_text="tail starts here",
        created_at_ms=200,
    )
    await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-3",
        message_text="latest tail",
        created_at_ms=300,
    )
    await chat_store.activate_context_summary(
        ChatContextSummaryRecord(
            summary_id="summary-1",
            session_id="s-chat",
            parent_summary_id=None,
            status="active",
            summary_kind="token_budget",
            persona_scope=None,
            covered_from_message_id="msg-1",
            covered_to_message_id=second_message.message_id,
            first_kept_message_id=second_message.message_id,
            covered_to_sequence_no=2,
            session_origin="Started with build system debugging.",
            summary_text="The first turn established the original topic.",
            prompt_profile="general_chat",
            model_provider=None,
            model_id=None,
            token_count_before=1200,
            token_count_after=120,
            quality_status="accepted",
            created_at_ms=400,
            updated_at_ms=400,
        )
    )

    from magi.chat.read_service import ChatReadService

    isolated_read_service = ChatReadService()
    isolated_read_service._chat_db_path = runtime_paths_with_schema.chat_db_path
    isolated_read_service._l1_db_path = tmp_path / "l1.sqlite3"
    isolated_read_service._runtime_trace_db_path = tmp_path / "runtime_trace.sqlite3"

    service = ChatContextAssembler(
        l1_db_path=tmp_path / "l1.sqlite3",
        runtime_trace_db_path=tmp_path / "runtime_trace.sqlite3",
        chat_store=chat_store,
        chat_read_service_factory=lambda: isolated_read_service,
    )

    history_context = await service.get_or_load_history_context("u-chat", "s-chat")

    assert history_context.session_origin == "Started with build system debugging."
    # commit b357735a (persona boundary summaries) wraps the active
    # token-budget summary in a "# Rolling Token-Budget Summary" markdown
    # section so it can be combined with persona-boundary / attachment
    # manifest sections in the prompt.
    assert history_context.session_summary == (
        "# Rolling Token-Budget Summary\n"
        "The first turn established the original topic.\n\n"
        "# Session Attachment References\n"
        "These are lightweight references to files attached in this session.\n"
        "Use `read_chat_attachment` with an `attachment_id` when the user asks about an earlier attachment; do not guess attachment contents from memory.\n"
        "- attachment_id=attachment-old; name=original.pdf; kind=pdf; turn_id=turn-1"
    )
    assert history_context.messages == [
        {"role": "user", "content": "tail starts here"},
        {"role": "user", "content": "latest tail"},
    ]


@pytest.mark.asyncio
async def test_chat_context_assembler_keeps_complete_tail_beyond_legacy_limit(
    tmp_path: Path,
) -> None:
    all_messages = [
        ChatDisplayMessage(
            role="user",
            content=f"message-{index}",
            timestamp=index,
            kind="user",
            message_id=f"msg-{index}",
            message_kind="user_text",
        )
        for index in range(1, 1102)
    ]
    active_summary = ChatContextSummaryRecord(
        summary_id="summary-long",
        session_id="s-long",
        parent_summary_id=None,
        status="active",
        summary_kind="token_budget",
        persona_scope=None,
        covered_from_message_id="msg-1",
        covered_to_message_id="msg-1",
        first_kept_message_id="msg-2",
        covered_to_sequence_no=1,
        session_origin="Long session origin.",
        summary_text="The first message was summarized.",
        prompt_profile="general_chat",
        model_provider=None,
        model_id=None,
        token_count_before=10_000,
        token_count_after=100,
        quality_status="accepted",
        created_at_ms=2_000,
        updated_at_ms=2_000,
    )

    class _SummaryStore:
        async def get_history_version(self, session_id: str) -> int:
            assert session_id == "s-long"
            return 1

        async def get_active_context_summary(self, *, session_id: str):  # type: ignore[no-untyped-def]
            assert session_id == "s-long"
            return active_summary

    class _BoundedReadService:
        def get_conversation_history(
            self,
            *,
            user_id: str,
            session_id: str,
            limit: int | None = 200,
            start_message_id: str | None = None,
        ) -> list[ChatDisplayMessage]:
            assert user_id == "u-chat"
            assert session_id == "s-long"
            assert start_message_id == "msg-2"
            tail = all_messages[1:]
            if limit is None:
                return list(tail)
            return tail[-min(limit, 1000) :]

        def get_session_attachment_references(
            self,
            user_id: str,
            session_id: str,
            limit: int = 40,
        ) -> list[dict[str, object]]:
            assert user_id == "u-chat"
            assert session_id == "s-long"
            assert limit == 40
            return []

    service = ChatContextAssembler(
        l1_db_path=tmp_path / "l1.sqlite3",
        chat_store=_SummaryStore(),  # type: ignore[arg-type]
        chat_read_service_factory=_BoundedReadService,
    )

    history_context = await service.get_or_load_history_context("u-chat", "s-long")

    assert len(history_context.messages) == 1100
    assert history_context.messages[0] == {"role": "user", "content": "message-2"}
    assert history_context.messages[-1] == {"role": "user", "content": "message-1101"}


@pytest.mark.asyncio
async def test_chat_context_assembler_keeps_history_when_attachment_manifest_fails(
    tmp_path: Path,
) -> None:
    class _AttachmentFailureReadService:
        def get_conversation_history(
            self,
            *,
            user_id: str,
            session_id: str,
            limit: int | None = 200,
            start_message_id: str | None = None,
        ) -> list[ChatDisplayMessage]:
            _ = (user_id, session_id, limit, start_message_id)
            return [
                ChatDisplayMessage(
                    role="user",
                    content="history remains available",
                    timestamp=100,
                    kind="user",
                    message_id="message-1",
                    message_kind="user_text",
                )
            ]

        def get_session_attachment_references(
            self,
            user_id: str,
            session_id: str,
            limit: int = 40,
        ) -> list[dict[str, object]]:
            _ = (user_id, session_id, limit)
            raise RuntimeError("attachment metadata unavailable")

    service = ChatContextAssembler(
        l1_db_path=tmp_path / "l1.sqlite3",
        chat_read_service_factory=_AttachmentFailureReadService,
    )

    history_context = await service.get_or_load_history_context("u-chat", "s-chat")

    assert history_context.messages == [
        {"role": "user", "content": "history remains available"}
    ]
    assert history_context.session_summary is None


@pytest.mark.asyncio
async def test_chat_context_assembler_summarizes_previous_persona_segment(tmp_path: Path, runtime_paths_with_schema) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-a",
        message_text="old persona request",
        created_at_ms=100,
        persona_id="persona-a",
    )
    await chat_store.append_message(
        ChatMessageRecord(
            message_id="assistant-a",
            session_id="s-chat",
            turn_id="turn-a",
            user_id="u-chat",
            role="assistant",
            message_kind="assistant_final",
            content_text="old persona answer with its own voice",
            payload_json="{}",
            is_final=True,
            is_visible=True,
            created_at_ms=150,
            sequence_no=2,
            replaces_message_id=None,
            replaced_by_message_id=None,
            persona_id="persona-a",
        )
    )
    current_user_message = await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-b",
        message_text="continue as the current persona",
        created_at_ms=200,
        persona_id="persona-b",
    )

    from magi.chat.read_service import ChatReadService

    isolated_read_service = ChatReadService()
    isolated_read_service._chat_db_path = runtime_paths_with_schema.chat_db_path
    isolated_read_service._l1_db_path = tmp_path / "l1.sqlite3"
    isolated_read_service._runtime_trace_db_path = tmp_path / "runtime_trace.sqlite3"

    calls = []

    async def summary_generator(summary_input):  # type: ignore[no-untyped-def]
        calls.append(summary_input)
        return "Neutral continuity from the previous persona segment."

    service = ChatContextAssembler(
        l1_db_path=tmp_path / "l1.sqlite3",
        runtime_trace_db_path=tmp_path / "runtime_trace.sqlite3",
        chat_store=chat_store,
        chat_read_service_factory=lambda: isolated_read_service,
        persona_boundary_summary_generator=summary_generator,
    )

    history_context = await service.get_or_load_history_context(
        "u-chat",
        "s-chat",
        active_persona_id="persona-b",
    )

    assert history_context.messages == [
        {"role": "user", "content": "continue as the current persona"},
    ]
    assert "# Persona Boundary Summary" in (history_context.session_summary or "")
    assert "Neutral continuity from the previous persona segment." in (history_context.session_summary or "")
    assert len(calls) == 1
    assert [message.role for message in calls[0].messages] == ["user", "assistant"]
    assert calls[0].messages[1].persona_id == "persona-a"

    active_summary = await chat_store.get_active_context_summary(
        session_id="s-chat",
        summary_kind="persona_boundary",
        persona_scope="persona-b",
    )
    assert active_summary is not None
    assert active_summary.first_kept_message_id == current_user_message.message_id
    assert active_summary.summary_text == "Neutral continuity from the previous persona segment."

    reloaded_context = await service.get_or_load_history_context(
        "u-chat",
        "s-chat",
        active_persona_id="persona-b",
    )
    assert reloaded_context.session_summary == history_context.session_summary
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_chat_context_assembler_never_treats_read_failure_as_empty_history(
    tmp_path: Path,
    runtime_paths_with_schema,
) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-1",
        message_text="hello",
        created_at_ms=100,
    )

    from magi.chat.read_service import ChatReadService

    real_read_service = ChatReadService()
    real_read_service._chat_db_path = runtime_paths_with_schema.chat_db_path
    real_read_service._l1_db_path = tmp_path / "l1.sqlite3"
    real_read_service._runtime_trace_db_path = tmp_path / "runtime_trace.sqlite3"

    class _FlakyReadService:
        def __init__(self) -> None:
            self.calls = 0

        def get_conversation_history(
            self,
            *,
            user_id: str,
            session_id: str,
            limit: int = 200,
            start_message_id: str | None = None,
        ):  # type: ignore[no-untyped-def]
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transient read failure")
            return real_read_service.get_conversation_history(
                user_id=user_id,
                session_id=session_id,
                limit=limit,
                start_message_id=start_message_id,
            )

        def get_session_attachment_references(
            self,
            user_id: str,
            session_id: str,
            limit: int = 40,
        ):  # type: ignore[no-untyped-def]
            return real_read_service.get_session_attachment_references(
                user_id,
                session_id,
                limit,
            )

    flaky_read_service = _FlakyReadService()
    service = ChatContextAssembler(
        l1_db_path=tmp_path / "l1.sqlite3",
        runtime_trace_db_path=tmp_path / "runtime_trace.sqlite3",
        chat_store=chat_store,
        chat_read_service_factory=lambda: flaky_read_service,
    )

    with pytest.raises(RuntimeError, match="Conversation history is unavailable"):
        await service.get_or_load_history("u-chat", "s-chat")
    second_history = await service.get_or_load_history("u-chat", "s-chat")

    assert second_history == [{"role": "user", "content": "hello"}]


def test_chat_tool_state_view_extracts_asset_ref_handles_from_tool_state() -> None:
    # The handle extractor moved with the rest of the tool-call state view
    # (chat domain Step 1 of the ChatHistoryService decomposition). It is
    # a module-level helper inside ``tool_state_view``, not a static method
    # on the assembler.
    from magi.chat.task_agent.tool_state_view import _extract_reusable_handles

    handles = _extract_reusable_handles(
        {
            "historical_recall": {
                "asset_refs": [
                    {
                        "asset_ref_id": "asset-1",
                        "event_id": "evt-1",
                    }
                ]
            }
        }
    )

    assert "asset_ref_id:asset-1" in handles
    assert "event_id:evt-1" in handles


@pytest.mark.asyncio
async def test_chat_task_agent_builds_reply_aware_prompt_context(tmp_path: Path, runtime_paths_with_schema) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    original_user_message = await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-1",
        message_text="Can you clarify the build step?",
        created_at_ms=100,
    )
    assistant_message = ChatMessageRecord(
        message_id="msg-assistant-root",
        session_id="s-chat",
        turn_id="turn-1",
        user_id="u-chat",
        role="assistant",
        message_kind="assistant_final",
        content_text="Run the desktop dev script from the repo root.",
        payload_json=json.dumps(
            {
                "attachments": [
                    {
                        "attachment_id": "att-root-1",
                        "kind": "image",
                        "original_name": "desktop-dev.png",
                    }
                ],
                "asset_refs": [
                    {
                        "asset_ref_id": "asset-root-1",
                        "event_id": "evt-photo-root-1",
                        "original_name": "desktop-dev.png",
                        "resolver_tool": "photo_library_resolve_photo_refs",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        is_final=True,
        is_visible=True,
        created_at_ms=150,
        sequence_no=2,
        replaces_message_id=None,
        replaced_by_message_id=None,
    )
    await chat_store.append_message(assistant_message)
    await chat_store.bump_history_version("s-chat")
    await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-2",
        message_text="What if I only want the backend?",
        created_at_ms=200,
        reply_to_message_id=assistant_message.message_id,
    )

    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter(), chat_store=chat_store)

    async def _fake_build_prompt_package(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return PromptPackage(prompt_context=None, system_prompt="BASE SYSTEM PROMPT")

    agent._context_service.build_prompt_package = _fake_build_prompt_package  # type: ignore[method-assign]

    reply_fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "What if I only want the backend?",
            "user_id": "u-chat",
            "session_id": "s-chat",
            "turn_id": "turn-2",
            "metadata": {
                "reply_to_message_id": assistant_message.message_id,
            },
        },
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id="corr_reply_1",
    )

    context = await agent.build_context(await agent.merge_facts([reply_fact]))

    assert getattr(context, "reply_context", None) is not None
    assert context.reply_context.message_id == assistant_message.message_id
    assert context.reply_context.role == "assistant"
    assert context.reply_context.is_explicit_reply is True
    assert context.reply_context.content_excerpt == "Run the desktop dev script from the repo root."
    assert context.reply_context.references_prior_turn is True
    assert context.reply_context.structured_payload == {
        "attachments": [
            {
                "attachment_id": "att-root-1",
                "kind": "image",
                "original_name": "desktop-dev.png",
            }
        ],
        "asset_refs": [
            {
                "asset_ref_id": "asset-root-1",
                "event_id": "evt-photo-root-1",
                "original_name": "desktop-dev.png",
                "resolver_tool": "photo_library_resolve_photo_refs",
            }
        ],
    }

    request = await agent._handler_registry.get(ExecutionMode.DIRECT_LLM).build_request(
        ExecutionRequest(
            mode=ExecutionMode.DIRECT_LLM,
            context=context,
            intent=IntentDecision(
                intent="chat",
                difficulty="normal",
                execution_mode=ExecutionMode.DIRECT_LLM,
            ),
            tool_selection=ToolSelection(),
        )
    )

    assert "BASE SYSTEM PROMPT" in request.system_prompt
    assert "Current message is replying to:" in request.system_prompt
    assert "- speaker: assistant" in request.system_prompt
    assert 'Run the desktop dev script from the repo root.' in request.system_prompt
    assert '"attachment_id": "att-root-1"' in request.system_prompt
    assert '"asset_ref_id": "asset-root-1"' in request.system_prompt
    assert request.messages[-1]["role"] == "user"
    assert "What if I only want the backend?" in request.messages[-1]["content"]
    assert "[Current message reply target]" in request.messages[-1]["content"]
    assert "attachment_id=att-root-1" in request.messages[-1]["content"]
    assert original_user_message.reply_to_message_id is None


@pytest.mark.asyncio
async def test_chat_task_agent_falls_back_to_recent_photo_context_without_explicit_reply(tmp_path: Path, runtime_paths_with_schema) -> None:
    chat_store = ChatStore(db_path=str(runtime_paths_with_schema.chat_db_path))
    await chat_store.initialize()
    await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-1",
        message_text="2022年9月我在哪里拍了照片",
        created_at_ms=100,
    )
    assistant_message = ChatMessageRecord(
        message_id="msg-assistant-photo-root",
        session_id="s-chat",
        turn_id="turn-1",
        user_id="u-chat",
        role="assistant",
        message_kind="assistant_final",
        content_text="我找到了几张 2022 年 9 月的照片。",
        payload_json=json.dumps(
            {
                "asset_refs": [
                    {
                        "asset_ref_id": "asset-root-1",
                        "event_id": "evt-photo-root-1",
                        "original_name": "hangzhou.jpg",
                        "resolver_tool": "photo_library_resolve_photo_refs",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        is_final=True,
        is_visible=True,
        created_at_ms=150,
        sequence_no=2,
        replaces_message_id=None,
        replaced_by_message_id=None,
    )
    await chat_store.append_message(assistant_message)
    await chat_store.bump_history_version("s-chat")
    await chat_store.create_user_turn(
        session_id="s-chat",
        user_id="u-chat",
        turn_id="turn-2",
        message_text="发出来看看",
        created_at_ms=200,
    )

    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter(), chat_store=chat_store)

    async def _fake_build_prompt_package(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return PromptPackage(prompt_context=None, system_prompt="BASE SYSTEM PROMPT")

    agent._context_service.build_prompt_package = _fake_build_prompt_package  # type: ignore[method-assign]

    follow_up_fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={
            "content": "发出来看看",
            "user_id": "u-chat",
            "session_id": "s-chat",
            "turn_id": "turn-2",
        },
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id="corr_reply_implicit_1",
    )

    context = await agent.build_context(await agent.merge_facts([follow_up_fact]))

    assert getattr(context, "reply_context", None) is not None
    assert context.reply_context.message_id == assistant_message.message_id
    assert context.reply_context.is_explicit_reply is False
    assert context.reply_context.structured_payload == {
        "asset_refs": [
            {
                "asset_ref_id": "asset-root-1",
                "event_id": "evt-photo-root-1",
                "original_name": "hangzhou.jpg",
                "resolver_tool": "photo_library_resolve_photo_refs",
            }
        ]
    }

    request = await agent._handler_registry.get(ExecutionMode.DIRECT_LLM).build_request(
        ExecutionRequest(
            mode=ExecutionMode.DIRECT_LLM,
            context=context,
            intent=IntentDecision(
                intent="chat",
                difficulty="normal",
                execution_mode=ExecutionMode.DIRECT_LLM,
            ),
            tool_selection=ToolSelection(),
        )
    )

    assert "Most recent assistant turn includes reusable context:" in request.system_prompt
    assert '"asset_ref_id": "asset-root-1"' in request.system_prompt
    assert "photo_library_resolve_photo_refs" in request.system_prompt


@pytest.mark.asyncio
async def test_chat_task_agent_context_service_resolves_session_workspace_from_read_service() -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    class _FakeReadService:
        async def aget_session_summary(self, user_id: str, session_id: str):
            assert user_id == "u-chat"
            assert session_id == "s-chat"
            return SimpleNamespace(workspace_path="/tmp/magi")

    agent._chat_read_service = _FakeReadService()

    package = await agent._context_service.build_prompt_package(
        user_id="u-chat",
        session_id="s-chat",
        user_message="where am i",
        task_category="chat",
        tools=[],
    )

    assert package.prompt_context.runtime_system.cwd == "/tmp/magi"
    assert "* Working Directory: /tmp/magi" in package.system_prompt


@pytest.mark.asyncio
async def test_chat_task_agent_completes_orchestration_after_worker_fact(tmp_path: Path, monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    agent._orchestration_store = OrchestrationStore(tmp_path / "orchestrations.json")
    agent._task_orchestrator._orchestration_store = agent._orchestration_store

    async def _fake_generate_subtask_plan(*args, **kwargs):  # type: ignore[no-untyped-def]
        _ = (args, kwargs)
        return SubtaskPlan(
            summary="planned",
            subtasks=[
                PlannedSubtask(
                    description="scan backend",
                    subagent_type="CodeExplore",
                    prompt="Inspect backend layout",
                    parallel_group="group_a",
                )
            ],
        )

    async def _fake_launch(state, **_kwargs):  # type: ignore[no-untyped-def]
        state.subtasks[0].worker_id = "worker_1"
        state.subtasks[0].status = "running"
        await agent._orchestration_store.save_orchestration(state)
        return None

    async def _fake_aggregate(state):  # type: ignore[no-untyped-def]
        assert state.subtasks[0].worker_result is not None
        return "aggregated answer"

    monkeypatch.setattr(agent._task_orchestrator, "_plan_subtasks", _fake_generate_subtask_plan)
    monkeypatch.setattr(agent._task_orchestrator, "_launch_workers", _fake_launch)
    monkeypatch.setattr(agent._task_orchestrator, "_aggregate_orchestration", _fake_aggregate)

    user_fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"content": "Analyze repo architecture", "user_id": "u-chat", "session_id": "s-chat"},
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id="corr_1",
    )
    merged = await agent.merge_facts([user_fact])
    context = await agent.build_context(merged)
    request = ExecutionRequest(
        mode=ExecutionMode.ORCHESTRATION_LAUNCH,
        context=context,
        intent=IntentDecision(
            intent="repo_analysis",
            difficulty="normal",
            execution_mode=ExecutionMode.ORCHESTRATION_LAUNCH,
            route_decision=RouteDecision(
                profile="research",
                graph_shape="plan_fanout",
                complexity="large",
            ),
            orchestration_plan=OrchestrationPlan(
                mode="decompose",
                default_leaf_type="general-purpose",
                allow_parallel=True,
            ),
        ),
        tool_selection=ToolSelection(),
    )
    request = await agent._handler_registry.get(ExecutionMode.ORCHESTRATION_LAUNCH).build_request(request)
    launch_result = await agent._handler_registry.get(ExecutionMode.ORCHESTRATION_LAUNCH).execute(request)
    assert launch_result.skip_emit is True

    states = await agent._orchestration_store.list_orchestrations(user_id="u-chat", session_id="s-chat")
    assert len(states) == 1
    state = states[0]
    assert state.subtasks[0].worker_id == "worker_1"
    assert state.subtasks[0].status == "running"

    completed_fact = FactRecord(
        agent_id="chat:u-chat",
        event_type="WORKER_AGENT_COMPLETED",
        payload={
            "worker_id": "worker_1",
            "orchestration_id": state.orchestration_id,
            "subtask_id": state.subtasks[0].subtask_id,
            "worker_result": {
                "result_status": "success",
                "summary": "backend analyzed",
                "findings": [{"title": "backend", "detail": "runtime path"}],
                "evidence": [{"path": "/tmp/backend.py", "detail": "entrypoint"}],
                "gaps": [],
                "next_steps": ["aggregate"],
                "failure_reason": None,
            },
            "user_id": "u-chat",
            "session_id": "s-chat",
        },
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id="worker_1",
    )

    merged_update = await agent.merge_facts([completed_fact])
    update_context = await agent.build_context(merged_update)
    update_request = ExecutionRequest(
        mode=ExecutionMode.ORCHESTRATION_UPDATE,
        context=update_context,
        intent=IntentDecision(
            intent="worker_orchestration_update",
            difficulty="normal",
            execution_mode=ExecutionMode.ORCHESTRATION_UPDATE,
        ),
        tool_selection=ToolSelection(),
    )
    update_result = await agent._handler_registry.get(ExecutionMode.ORCHESTRATION_UPDATE).execute(update_request)
    assert update_result.response_text == "aggregated answer"
    assert update_result.orchestration_id == state.orchestration_id

    updated = await agent._orchestration_store.get_orchestration(state.orchestration_id)
    assert updated is not None
    assert updated.status == "completed"
    assert updated.final_response == "aggregated answer"


@pytest.mark.asyncio
async def test_aggregate_orchestration_uses_analysis_prompt_without_tool_catalog(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    history_key = "u-chat::s-chat"
    agent._context_assembler.append_user_message(history_key, "看下代码架构")
    agent._context_assembler.append_user_message(history_key, "搞错了，不用做了")
    agent._context_assembler.append_assistant_message(history_key, "[Worker:abc] Started (Explore)")

    calls: dict[str, object] = {}

    async def _fake_build_system_prompt(  # type: ignore[no-untyped-def]
        *,
        user_id=None,
        session_id=None,
        user_message="",
        task_category="chat",
        scenario="chat",
        tools=None,
        recent_tool_errors=None,
        include_tool_catalog=True,
        persona_id=None,
    ):
        calls["build_system_prompt"] = {
            "user_id": user_id,
            "session_id": session_id,
            "user_message": user_message,
            "task_category": task_category,
            "scenario": scenario,
            "include_tool_catalog": include_tool_catalog,
            "persona_id": persona_id,
        }
        return "persona-system-prompt"

    async def _fake_call_llm(*, system_prompt, messages, disable_thinking=True, thinking_depth=None, **kwargs):  # type: ignore[no-untyped-def]
        _ = (thinking_depth, kwargs)
        calls["call_llm"] = {
            "system_prompt": system_prompt,
            "messages": messages,
            "disable_thinking": disable_thinking,
        }
        return "这是面向用户的最终回答"

    monkeypatch.setattr(agent._context_service, "build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(agent._prompt_service, "call_llm", _fake_call_llm)

    state = TaskOrchestrationState(
        orchestration_id="orch_test",
        user_id="u-chat",
        session_id="s-chat",
        root_user_message="看下~/code/magi下的代码，分析下代码架构",
        planner="task_agent",
        metadata={"persona_id": "persona-aggregate"},
        subtasks=[
            SubtaskDefinition(
                subtask_id="subtask_1",
                description="Analyze backend modules",
                subagent_type="CodeExplore",
                prompt="Inspect backend",
                status="completed",
                worker_result=WorkerResult.from_dict(
                    {
                        "result_status": "success",
                        "summary": "后端采用分层多 agent 架构。",
                        "findings": [
                            {
                                "title": "runtime",
                                "detail": "bootstrap/backend.py 负责初始化",
                                "path": "/tmp/bootstrap/backend.py",
                                "why_it_matters": "这是主入口",
                            }
                        ],
                        "evidence": [{"path": "/tmp/bootstrap/backend.py", "detail": "bootstrap entry"}],
                        "gaps": [],
                        "next_steps": [],
                        "failure_reason": None,
                        "subtasks": [],
                    }
                ),
                failure_reason=None,
                attempt_count=1,
            ),
        ],
    )

    response = await agent._planning_service.aggregate_orchestration(state)
    assert response == "这是面向用户的最终回答"
    assert calls["build_system_prompt"] == {
        "user_id": "u-chat",
        "session_id": "s-chat",
        "user_message": "看下~/code/magi下的代码，分析下代码架构",
        "task_category": "analysis",
        "scenario": "analysis",
        "include_tool_catalog": False,
        "persona_id": "persona-aggregate",
    }

    llm_call = calls["call_llm"]
    assert isinstance(llm_call, dict)
    assert "persona-system-prompt" in llm_call["system_prompt"]
    assert "# Aggregation Task" in llm_call["system_prompt"]
    assert "## Internal Evidence Dossier" not in llm_call["system_prompt"]
    assert "You must explicitly absorb the key findings, evidence, and trade-offs" in llm_call["system_prompt"]
    assert '"completed_subtasks"' not in llm_call["system_prompt"]
    assert "# Tool Use Guidance" not in llm_call["system_prompt"]
    assert llm_call["disable_thinking"] is False
    messages = llm_call["messages"]
    assert isinstance(messages, list)
    assert messages[0] == {"role": "user", "content": "看下代码架构"}
    assert messages[-2] == {"role": "user", "content": "搞错了，不用做了"}
    assert "## Original User Request" in messages[-1]["content"]
    assert "## Internal Evidence Dossier" in messages[-1]["content"]
    assert "### Completed Analyses" in messages[-1]["content"]


@pytest.mark.asyncio
async def test_aggregate_orchestration_uses_fast_failure_status_when_all_subtasks_fail(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    agent._context_assembler.append_user_message("u-chat::s-chat", "帮我安排杭州行程")
    calls: dict[str, object] = {}

    async def _fake_build_system_prompt(  # type: ignore[no-untyped-def]
        *,
        user_id=None,
        session_id=None,
        user_message="",
        task_category="chat",
        scenario="chat",
        tools=None,
        recent_tool_errors=None,
        include_tool_catalog=True,
        persona_id=None,
    ):
        _ = (tools, recent_tool_errors)
        return "persona-system-prompt"

    async def _fake_call_llm(*, system_prompt, messages, disable_thinking=True, thinking_depth=None, **kwargs):  # type: ignore[no-untyped-def]
        _ = thinking_depth
        calls["call_llm"] = {
            "system_prompt": system_prompt,
            "messages": messages,
            "disable_thinking": disable_thinking,
            "event_context": kwargs.get("event_context"),
        }
        return "我刚才尝试查询地铁和低强度路线，但搜索工具失败了。请先配置搜索提供商后我再继续。"

    monkeypatch.setattr(agent._context_service, "build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(agent._prompt_service, "call_llm", _fake_call_llm)

    state = TaskOrchestrationState(
        orchestration_id="orch_failed",
        user_id="u-chat",
        session_id="s-chat",
        root_user_message="帮我安排杭州行程",
        planner="task_agent",
        subtasks=[
            SubtaskDefinition(
                subtask_id="subtask_1",
                description="查询杭州西站到市区地铁接驳",
                subagent_type="general-purpose",
                prompt="Search metro route",
                status="failed",
                failure_reason="ALL_TOOLS_FAILED",
                failure_details={
                    "tool_failures": [
                        {
                            "tool_name": "web-search",
                            "error_code": "PROVIDER_CHALLENGE",
                            "error": "DuckDuckGo challenge",
                            "diagnostics": {
                                "next_action": "ask_user_to_configure_search_provider",
                                "user_message_template": "DuckDuckGo hit an anti-bot check this time.",
                            },
                        }
                    ]
                },
                attempt_count=1,
            )
        ],
    )

    response = await agent._planning_service.aggregate_orchestration(state)

    assert response.startswith("我刚才尝试查询")
    llm_call = calls["call_llm"]
    assert isinstance(llm_call, dict)
    assert "# Interrupted Task Status" in llm_call["system_prompt"]
    assert "# Aggregation Task" not in llm_call["system_prompt"]
    assert "Response Contract" not in llm_call["system_prompt"]
    assert llm_call["disable_thinking"] is True
    assert llm_call["event_context"]["request_kind"] == "task_agent:failure_status"
    messages = llm_call["messages"]
    assert isinstance(messages, list)
    assert "## Attempted Steps And Failures" in messages[-1]["content"]
    assert "Tool failure: web-search | PROVIDER_CHALLENGE" in messages[-1]["content"]
    assert "Next action: ask_user_to_configure_search_provider" in messages[-1]["content"]


@pytest.mark.asyncio
async def test_chat_task_agent_routes_large_explore_to_explore_task_agent(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    captured = {}

    class _FakeManager:
        async def add_fact_to_agent(self, agent_type, agent_id, fact):  # type: ignore[no-untyped-def]
            captured["agent_type"] = agent_type
            captured["agent_id"] = agent_id
            captured["fact"] = fact
            return True

    agent._task_agent_manager = _FakeManager()

    user_fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EventTypes.USER_MESSAGE,
        payload={"content": "看下~/code/magi下的代码，分析下代码架构", "user_id": "u-chat", "session_id": "s-chat"},
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id="corr_x",
    )
    merged = await agent.merge_facts([user_fact])
    context = await agent.build_context(merged)
    agent._context_assembler.append_user_message("u-chat::s-chat", "看下代码架构")
    request = ExecutionRequest(
        mode=ExecutionMode.ORCHESTRATION_LAUNCH,
        context=context,
        intent=IntentDecision(
            intent="repo_analysis",
            difficulty="normal",
            execution_mode=ExecutionMode.ORCHESTRATION_LAUNCH,
            route_decision=RouteDecision(
                profile="explore",
                graph_shape="plan_fanout",
                complexity="large",
            ),
            orchestration_plan=OrchestrationPlan(
                mode="decompose",
                default_leaf_type="CodeExplore",
                allow_parallel=True,
            ),
        ),
        tool_selection=ToolSelection(),
    )
    request = await agent._handler_registry.get(ExecutionMode.ORCHESTRATION_LAUNCH).build_request(request)
    result = await agent._handler_registry.get(ExecutionMode.ORCHESTRATION_LAUNCH).execute(request)

    assert result.skip_emit is True
    assert captured["agent_type"] == TaskAgentType.EXPLORE


@pytest.mark.asyncio
async def test_chat_planning_service_falls_back_to_research_subtasks(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    async def _empty_response(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return ""

    monkeypatch.setattr(agent._prompt_service, "call_llm", _empty_response)

    plan = await agent._planning_service.generate_subtask_plan(
        user_message="搜一下最近7天杭州有什么重要的新闻，给我来10条并附上链接",
        history=[{"role": "user", "content": "搜一下最近7天杭州有什么重要的新闻，给我来10条并附上链接"}],
        orchestration_plan=OrchestrationPlan(
            mode="decompose",
            planner="task_agent",
            default_leaf_type="general-purpose",
            allow_parallel=True,
        ),
        user_id="u-chat",
        session_id="s-chat",
    )

    assert len(plan.subtasks) == 2
    assert all(item.subagent_type == "general-purpose" for item in plan.subtasks)
    assert plan.subtasks[0].description == "Search official and local-source coverage"
    assert "Normalized date range:" in plan.subtasks[0].prompt
    assert "title, date, source, canonical link" in plan.subtasks[0].prompt


@pytest.mark.asyncio
async def test_chat_planning_service_adds_fetch_subtask_only_for_detail_requests(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())

    async def _empty_response(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return ""

    monkeypatch.setattr(agent._prompt_service, "call_llm", _empty_response)

    plan = await agent._planning_service.generate_subtask_plan(
        user_message="搜一下最近7天杭州有什么重要的新闻，给我来10条，并展开第3条详情",
        history=[{"role": "user", "content": "搜一下最近7天杭州有什么重要的新闻，给我来10条，并展开第3条详情"}],
        orchestration_plan=OrchestrationPlan(
            mode="decompose",
            planner="task_agent",
            default_leaf_type="general-purpose",
            allow_parallel=True,
        ),
        user_id="u-chat",
        session_id="s-chat",
    )

    assert len(plan.subtasks) == 3
    assert plan.subtasks[-1].description == "Fetch and verify article details"


@pytest.mark.asyncio
async def test_chat_planning_service_uses_json_mode_and_extended_timeout(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    captured: dict[str, Any] = {}

    async def _fake_call_llm(**kwargs):  # type: ignore[no-untyped-def]
        captured.update(kwargs)
        return (
            '{"summary":"planned","subtasks":['
            '{"description":"Search official and local-source coverage","subagent_type":"general-purpose","prompt":"Search official sources","parallel_group":"group_a"},'
            '{"description":"Search major media and commercial-source coverage","subagent_type":"general-purpose","prompt":"Search media sources","parallel_group":"group_a"}'
            ']}'
        )

    monkeypatch.setattr(agent._prompt_service, "call_llm", _fake_call_llm)

    plan = await agent._planning_service._plan_with_task_agent(
        user_message="搜一下最近7天杭州有什么重要的新闻，给我来10条",
        history=[],
        orchestration_plan=OrchestrationPlan(
            mode="decompose",
            planner="task_agent",
            default_leaf_type="general-purpose",
            allow_parallel=True,
        ),
        request_profile="research",
    )

    assert plan is not None
    assert captured["json_mode"] is True
    assert captured["timeout_seconds"] == 180.0
    assert captured["disable_thinking"] is False
    assert str(captured["messages"][0]["content"]).startswith("# Planning Brief")
    assert "## Date Range Hint" in str(captured["messages"][0]["content"])


@pytest.mark.asyncio
async def test_chat_task_agent_renders_explore_dossier_with_analysis_prompt(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    agent._context_assembler.append_user_message("u-chat::s-chat", "看下代码架构")
    agent._context_assembler.append_assistant_message("u-chat::s-chat", "好的，我先拆分下。")
    calls = {}

    async def _fake_build_system_prompt(  # type: ignore[no-untyped-def]
        *,
        scenario="chat",
        user_id=None,
        session_id=None,
        user_message="",
        task_category="chat",
        tools=None,
        recent_tool_errors=None,
        include_tool_catalog=True,
        persona_id=None,
        persona_routing_hint=None,
        **kwargs,
    ):
        _ = (tools, recent_tool_errors, persona_routing_hint, kwargs)
        calls["build_system_prompt"] = {
            "scenario": scenario,
            "user_id": user_id,
            "session_id": session_id,
            "user_message": user_message,
            "task_category": task_category,
            "include_tool_catalog": include_tool_catalog,
            "persona_id": persona_id,
        }
        return "analysis-system-prompt"

    async def _fake_call_llm(*, system_prompt, messages, disable_thinking=True, thinking_depth=None, **kwargs):  # type: ignore[no-untyped-def]
        _ = (thinking_depth, kwargs)
        calls["call_llm"] = {
            "system_prompt": system_prompt,
            "messages": messages,
            "disable_thinking": disable_thinking,
        }
        return "这是最终分析回答"

    monkeypatch.setattr(agent._context_service, "build_system_prompt", _fake_build_system_prompt)
    monkeypatch.setattr(agent._prompt_service, "call_llm", _fake_call_llm)

    latest_fact = FactRecord(
        agent_id="chat:u-chat",
        event_type=EXPLORE_TASK_COMPLETED,
        payload={
            "user_id": "u-chat",
            "session_id": "s-chat",
            "root_user_message": "看下~/code/magi下的代码，分析下代码架构",
            "markdown_dossier": "# Request\n看下~/code/magi下的代码，分析下代码架构\n\n## Backend Modules\n- bootstrap/backend.py",
            "orchestration_id": "orch_x",
        },
        agent_type="chat",
        agent_instance_id="u-chat",
        correlation_id="corr_dossier",
    )

    merged = await agent.merge_facts([latest_fact])
    context = await agent.build_context(merged)
    context.active_persona_id = "persona-explore"
    request = ExecutionRequest(
        mode=ExecutionMode.EXPLORE_TASK_RENDER,
        context=context,
        intent=IntentDecision(
            intent="explore_task_completed",
            difficulty="normal",
            execution_mode=ExecutionMode.EXPLORE_TASK_RENDER,
        ),
        tool_selection=ToolSelection(),
    )
    request = await agent._handler_registry.get(ExecutionMode.EXPLORE_TASK_RENDER).build_request(request)
    result = await agent._handler_registry.get(ExecutionMode.EXPLORE_TASK_RENDER).execute(request)

    assert result.response_text == "这是最终分析回答"
    assert calls["build_system_prompt"] == {
        "scenario": "analysis",
        "user_id": "u-chat",
        "session_id": "s-chat",
        "user_message": "看下~/code/magi下的代码，分析下代码架构",
        "task_category": "analysis",
        "include_tool_catalog": False,
        "persona_id": "persona-explore",
    }
    call_llm = calls["call_llm"]
    assert call_llm["system_prompt"] == "analysis-system-prompt"
    assert call_llm["disable_thinking"] is True
    assert "探索报告" in call_llm["messages"][-1]["content"]
    assert "# Request" in call_llm["messages"][-1]["content"]


def test_chat_prompt_service_formats_dense_explore_render_text() -> None:
    from magi.chat.task_agent.prompt_service import ChatPromptService

    service = ChatPromptService(
        llm_adapter=_FakeLLMAdapter(),
    )

    raw = "第一段总览。1. 项目概况与布局整体说明2. 技术栈说明- FastAPI- React3. 总结"
    formatted = service.format_explore_render_response(raw)

    assert "\n\n1. 项目概况与布局" in formatted
    assert "\n- FastAPI" in formatted
    assert "\n- React" in formatted


def test_chat_prompt_service_unwraps_markdown_fenced_explore_response() -> None:
    from magi.chat.task_agent.prompt_service import ChatPromptService

    service = ChatPromptService(
        llm_adapter=_FakeLLMAdapter(),
    )

    raw = "```markdown\n# 苹果股价分析报告\n\n| 指标 | 数据 |\n|---|---|\n| 股价 | $192 |\n```\n\n补充说明"
    formatted = service.format_explore_render_response(raw)

    assert formatted.startswith("# 苹果股价分析报告")
    assert "```markdown" not in formatted
    assert "| 股价 | $192 |" in formatted
    assert formatted.endswith("补充说明")


@pytest.mark.asyncio
async def test_plan_with_task_agent_logs_empty_response(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    warnings: list[str] = []

    async def _fake_call_llm(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return ""

    def _fake_warning(message, *args):  # type: ignore[no-untyped-def]
        warnings.append(message % args)

    monkeypatch.setattr(agent._prompt_service, "call_llm", _fake_call_llm)
    monkeypatch.setattr(planning_service_module.logger, "warning", _fake_warning)

    result = await agent._planning_service._plan_with_task_agent(
        user_message="Analyze repo architecture",
        history=[],
        orchestration_plan=OrchestrationPlan(
            default_leaf_type="CodeExplore",
            allow_parallel=True,
        ),
        request_profile="repo_architecture",
    )

    assert result is None
    assert any("Task-agent planning returned empty response" in item for item in warnings)


@pytest.mark.asyncio
async def test_plan_with_task_agent_logs_non_executable_plan(monkeypatch) -> None:
    agent = ChatTaskAgent(agent_id="u-chat", llm_adapter=_FakeLLMAdapter())
    warnings: list[str] = []

    async def _fake_call_llm(**kwargs):  # type: ignore[no-untyped-def]
        _ = kwargs
        return '{"summary":"planned","subtasks":[]}'

    def _fake_warning(message, *args):  # type: ignore[no-untyped-def]
        warnings.append(message % args)

    monkeypatch.setattr(agent._prompt_service, "call_llm", _fake_call_llm)
    monkeypatch.setattr(planning_service_module.logger, "warning", _fake_warning)

    result = await agent._planning_service._plan_with_task_agent(
        user_message="Analyze repo architecture",
        history=[],
        orchestration_plan=OrchestrationPlan(
            default_leaf_type="CodeExplore",
            allow_parallel=True,
        ),
        request_profile="repo_architecture",
    )

    assert result is None
    assert any("Task-agent planning returned non-executable plan" in item for item in warnings)
