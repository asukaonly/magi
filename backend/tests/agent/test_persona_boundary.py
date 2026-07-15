from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from magi.chat.task_agent.persona_boundary import (
    PersonaBoundarySummarizer,
    PersonaBoundarySummaryInput,
    PersonaBoundarySummaryMessage,
)
from magi.config.models import LLMScenario
from magi.llm.model_context import ModelContextProfile, ResolvedModel


@pytest.mark.asyncio
async def test_persona_summary_output_budget_tracks_active_model_capacity() -> None:
    summary_adapter = SimpleNamespace()
    core_adapter = SimpleNamespace()

    def resolve(scenario: LLMScenario) -> ResolvedModel:
        if scenario == LLMScenario.CONTEXT_COMPACT:
            return ResolvedModel(
                adapter=summary_adapter,
                context=ModelContextProfile(
                    provider_id="summary-provider",
                    model_id="large-summary-model",
                    context_window=1_000_000,
                    max_output_tokens=64_000,
                ),
            )
        return ResolvedModel(
            adapter=core_adapter,
            context=ModelContextProfile(
                provider_id="core-provider",
                model_id="small-core-model",
                context_window=32_000,
                max_output_tokens=8_000,
            ),
        )

    pool = SimpleNamespace(
        resolve=resolve,
        get=lambda scenario: resolve(scenario).adapter,
    )
    bridge = AsyncMock()
    bridge.chat = AsyncMock(return_value=SimpleNamespace(content="neutral summary"))
    summarizer = PersonaBoundarySummarizer(
        chat_store=None,
        scenario_llm_pool=pool,
        llm_adapter=None,
        persona_boundary_summary_generator=None,
    )
    summary_input = PersonaBoundarySummaryInput(
        session_id="session-1",
        active_persona_id="persona-b",
        messages=[
            PersonaBoundarySummaryMessage(
                message_id="message-1",
                role="assistant",
                content="Prior persona context",
                persona_id="persona-a",
                message_kind="assistant_final",
            )
        ],
    )

    with patch(
        "magi.chat.task_agent.persona_boundary.LLMProviderBridge",
        return_value=bridge,
    ):
        summary = await summarizer._generate(summary_input)

    assert summary == "neutral summary"
    assert bridge.chat.await_args.kwargs["max_tokens"] == 512
    assert "within 512 tokens" in bridge.chat.await_args.kwargs["system_prompt"]
