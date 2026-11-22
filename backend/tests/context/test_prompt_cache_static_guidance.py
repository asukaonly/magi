"""Tests for P1-C1: static chat guidance lives above SYSTEM_PROMPT_CACHE_BOUNDARY."""

from __future__ import annotations

import hashlib

import pytest

from magi.agent.execution.function_calling.responses import FunctionCallingResponseMixin
from magi.chat.task_agent.chat_task_agent import ChatTaskAgent
from magi.agent.task_agents.handlers import (
    CapabilitySelection,
    ChatRuntimeContext,
    GenericFactPayload,
    IncomingFactKind,
    TurnAdmissionDecision,
)

pytestmark = pytest.mark.usefixtures("bound_chat_reader")
from magi.agent.task_agents.handlers.handler_helpers import (
    MEMORY_QUERY_GUIDANCE_BLOCK,
    PERSONAL_COMMITMENTS_GUIDANCE_BLOCK,
    PICTURE_STICKERS_GUIDANCE_BLOCK,
)
from magi.config.constants import SYSTEM_PROMPT_CACHE_BOUNDARY
from magi.context.renderer import PromptContextRenderer
from magi.context.schema import (
    IdentityConstraintContext,
    ProfileMemoryContext,
    PromptAssemblyContext,
    RuntimeSystemContext,
    SelfMemoryContext,
    ToolCatalogContext,
)
from magi.llm import LLMAdapter
from magi.personality.turn_planner import PersonaTurnPlan


class _StubAdapter(LLMAdapter):
    def __init__(self) -> None:
        self._model = "stub-model"

    @property
    def model_name(self) -> str:
        return self._model

    @property
    def provider_name(self) -> str:
        return "openai"

    async def generate(self, prompt: str, max_tokens=None, temperature=0.7, **kwargs):
        return "ok"

    async def generate_stream(self, prompt: str, max_tokens=None, temperature=0.7, **kwargs):
        yield "ok"

    async def chat(self, messages, max_tokens=None, temperature=0.7, **kwargs):
        return "ok"

    async def chat_stream(self, messages, max_tokens=None, temperature=0.7, **kwargs):
        yield "ok"


def _make_context(user_message: str, sticker_catalog: list[dict] | None = None) -> ChatRuntimeContext:
    return ChatRuntimeContext(
        latest_fact=None,
        recent_facts=[],
        batch_facts=[],
        agent_id="u-cache",
        agent_type="chat",
        runtime_key="chat:u-cache",
        user_id="u-cache",
        session_id="s-cache",
        history_key="u-cache::s-cache",
        history=[{"role": "user", "content": user_message}],
        conversation_history=[{"role": "user", "content": user_message}],
        recent_tool_errors=[],
        sticker_catalog=list(sticker_catalog or []),
        latest_user_message=user_message,
        incoming_fact_kind=IncomingFactKind.USER_MESSAGE,
        latest_payload=GenericFactPayload(),
    )


@pytest.mark.asyncio
async def test_consecutive_turns_have_identical_cached_head_and_reduced_working_context() -> None:
    agent = ChatTaskAgent(agent_id="u-cache", llm_adapter=_StubAdapter())
    tools = ["memory_query", "personal_task_query", "prepare_chat_attachments", "web-search"]
    admission = TurnAdmissionDecision(run_kind="unified_agent_run", execution_mode=None, tools=tools)
    capabilities = CapabilitySelection(tools=tools, reasoning="chat capabilities")

    req_1 = await agent.build_execution_request(
        _make_context("今天聊聊近况吧", sticker_catalog=[]),
        admission,
        capabilities,
    )
    req_2 = await agent.build_execution_request(
        _make_context("今天有点难受，好累啊", sticker_catalog=[{"sticker_id": "st_1", "name": "抱抱"}]),
        admission,
        capabilities,
    )

    assert req_1.system_prompt.endswith(SYSTEM_PROMPT_CACHE_BOUNDARY)
    assert req_2.system_prompt.endswith(SYSTEM_PROMPT_CACHE_BOUNDARY)

    head_1, _, tail_1 = req_1.system_prompt.partition(SYSTEM_PROMPT_CACHE_BOUNDARY)
    head_2, _, tail_2 = req_2.system_prompt.partition(SYSTEM_PROMPT_CACHE_BOUNDARY)
    assert tail_1 == ""
    assert tail_2 == ""
    assert hashlib.sha256(head_1.encode("utf-8")).hexdigest() == hashlib.sha256(
        head_2.encode("utf-8")
    ).hexdigest()

    for block in (
        "# Tool Use Guidance",
        MEMORY_QUERY_GUIDANCE_BLOCK,
        PERSONAL_COMMITMENTS_GUIDANCE_BLOCK,
        PICTURE_STICKERS_GUIDANCE_BLOCK,
        "# Attachment Preparation Guidance",
    ):
        assert block in head_1
        assert block not in req_1.working_context
        assert block not in req_2.working_context

    # Dynamic sticker catalog stays in working_context only when populated.
    assert "st_1" not in head_2
    assert "st_1" in req_2.working_context
    assert "## Picture sticker catalog" not in req_1.working_context

    # Baseline working_context shrinks by >= 55% vs keeping the static guidance blocks in working_context.
    static_chars_moved = (
        len(MEMORY_QUERY_GUIDANCE_BLOCK)
        + len(PERSONAL_COMMITMENTS_GUIDANCE_BLOCK)
        + len(PICTURE_STICKERS_GUIDANCE_BLOCK)
        + 860  # Tool Use Guidance block
    )
    legacy_working_chars = len(req_1.working_context) + static_chars_moved
    reduction_ratio = (legacy_working_chars - len(req_1.working_context)) / legacy_working_chars
    assert reduction_ratio >= 0.55


def test_emotional_register_suppresses_tool_imperatives_without_mutating_cached_head() -> None:
    def _ctx(register: str) -> PromptAssemblyContext:
        return PromptAssemblyContext(
            identity_constraints=IdentityConstraintContext(
                system_definition="System",
                core_truths_and_boundaries="Boundaries",
            ),
            self_memory=SelfMemoryContext(
                persona_turn_plan=PersonaTurnPlan(
                    persona_name="Seven",
                    identity_core={"identity_statement": "Direct"},
                    idiolect={"sentence_style": "concise"},
                    register=register,
                ),
            ),
            profile_memory=ProfileMemoryContext(user_id="u1"),
            runtime_system=RuntimeSystemContext(
                current_date="2026-01-01",
                timezone="UTC",
                os_name="Darwin",
                os_version="24.0",
                cwd="/tmp",
                agent_id="chat",
                agent_type="chat",
            ),
            tool_catalog=ToolCatalogContext(selected_tools=["memory_query"]),
        )

    renderer = PromptContextRenderer()
    casual_layers = renderer.render_prompt_layers(_ctx("casual"))
    emotional_layers = renderer.render_prompt_layers(_ctx("emotional"))

    assert casual_layers.system_prompt == emotional_layers.system_prompt
    assert "## Turn Tool Guidance Override" not in casual_layers.working_context
    assert "## Turn Tool Guidance Override" in emotional_layers.working_context


def test_final_response_guidance_detects_memory_query_guidance_in_system_prompt() -> None:
    class _Mixin(FunctionCallingResponseMixin):
        pass

    guidance = _Mixin()._build_final_response_guidance(
        [{"role": "user", "content": "What did I read yesterday?"}],
        system_prompt=f"# System\n\n{MEMORY_QUERY_GUIDANCE_BLOCK}\n\n{SYSTEM_PROMPT_CACHE_BOUNDARY}",
    )
    assert "Treat memory_query results as the source of truth" in guidance
