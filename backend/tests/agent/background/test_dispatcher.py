from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from magi.agent.background.dispatcher import (
    BackgroundDecision,
    BackgroundDecisionContext,
    BackgroundDecisionSource,
    BackgroundDisposition,
    BackgroundDispatcher,
    BackgroundRuleOutcome,
)


# ----------------------------------------------------------------------
# Test doubles
# ----------------------------------------------------------------------


class _FakeLLMService:
    """Stand-in that records ``.call`` invocations and returns a scripted reply."""

    def __init__(
        self,
        *,
        response: str | None = None,
        exc: BaseException | None = None,
    ) -> None:
        self.response = response
        self.exc = exc
        self.calls: list[dict[str, Any]] = []

    async def call(self, **kwargs: Any) -> str:
        self.calls.append(kwargs)
        if self.exc is not None:
            raise self.exc
        return self.response or ""


def _patch_llm_service(
    dispatcher: BackgroundDispatcher, fake: _FakeLLMService
) -> None:
    dispatcher._llm_service = fake  # type: ignore[assignment]
    # _can_use_model_classifier() checks llm_pool / llm_adapter.provider_name.
    dispatcher._llm_pool = object()


# ----------------------------------------------------------------------
# Rule fast path
# ----------------------------------------------------------------------


def test_rule_yes_on_explicit_background_keyword() -> None:
    dispatcher = BackgroundDispatcher()

    outcome = dispatcher.classify_rule(
        BackgroundDecisionContext(user_text="帮我深度研究一下，跑完告诉我")
    )

    assert outcome is BackgroundRuleOutcome.YES


def test_rule_yes_on_long_running_tool() -> None:
    dispatcher = BackgroundDispatcher()

    outcome = dispatcher.classify_rule(
        BackgroundDecisionContext(
            user_text="analyse this",
            selected_tools=["deep_research"],
        )
    )

    assert outcome is BackgroundRuleOutcome.YES


def test_rule_no_on_explicit_foreground_keyword() -> None:
    dispatcher = BackgroundDispatcher()

    outcome = dispatcher.classify_rule(
        BackgroundDecisionContext(user_text="quick question: what is 2+2?")
    )

    assert outcome is BackgroundRuleOutcome.NO


def test_rule_unknown_on_neutral_message() -> None:
    dispatcher = BackgroundDispatcher()

    outcome = dispatcher.classify_rule(
        BackgroundDecisionContext(user_text="summarise the recent emails")
    )

    assert outcome is BackgroundRuleOutcome.UNKNOWN


def test_rule_unknown_on_conflicting_keywords() -> None:
    """Conflicting signals must defer to the LLM stage rather than guessing."""
    dispatcher = BackgroundDispatcher()

    outcome = dispatcher.classify_rule(
        BackgroundDecisionContext(
            user_text="quick question but run in background"
        )
    )

    assert outcome is BackgroundRuleOutcome.UNKNOWN


# ----------------------------------------------------------------------
# Planner override
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_planner_true_forces_background() -> None:
    dispatcher = BackgroundDispatcher()

    decision = await dispatcher.classify(
        BackgroundDecisionContext(
            user_text="quick ping",  # rule would say NO
            planner_flag=True,
        )
    )

    assert decision.disposition is BackgroundDisposition.BACKGROUND
    assert decision.source is BackgroundDecisionSource.PLANNER


@pytest.mark.asyncio
async def test_planner_false_forces_foreground() -> None:
    dispatcher = BackgroundDispatcher()

    decision = await dispatcher.classify(
        BackgroundDecisionContext(
            user_text="deep research please",  # rule would say YES via… nothing, actually UNKNOWN
            selected_tools=["deep_research"],  # rule would normally say YES
            planner_flag=False,
        )
    )

    assert decision.disposition is BackgroundDisposition.FOREGROUND
    assert decision.source is BackgroundDecisionSource.PLANNER


# ----------------------------------------------------------------------
# Full pipeline
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_short_circuits_on_rule_yes_without_llm() -> None:
    dispatcher = BackgroundDispatcher()
    fake = _FakeLLMService(response='{"background": false}')
    _patch_llm_service(dispatcher, fake)

    decision = await dispatcher.classify(
        BackgroundDecisionContext(user_text="跑完告诉我")
    )

    assert decision.disposition is BackgroundDisposition.BACKGROUND
    assert decision.source is BackgroundDecisionSource.RULE
    assert fake.calls == []  # LLM was NOT invoked


@pytest.mark.asyncio
async def test_classify_short_circuits_on_rule_no_without_llm() -> None:
    dispatcher = BackgroundDispatcher()
    fake = _FakeLLMService(response='{"background": true}')
    _patch_llm_service(dispatcher, fake)

    decision = await dispatcher.classify(
        BackgroundDecisionContext(user_text="quick question")
    )

    assert decision.disposition is BackgroundDisposition.FOREGROUND
    assert decision.source is BackgroundDecisionSource.RULE
    assert fake.calls == []


@pytest.mark.asyncio
async def test_classify_calls_llm_on_unknown_with_required_params() -> None:
    dispatcher = BackgroundDispatcher()
    fake = _FakeLLMService(response='{"background": true, "reason": "long task"}')
    _patch_llm_service(dispatcher, fake)

    decision = await dispatcher.classify(
        BackgroundDecisionContext(user_text="summarise the inbox")
    )

    assert decision.disposition is BackgroundDisposition.BACKGROUND
    assert decision.source is BackgroundDecisionSource.LLM
    assert decision.reason == "long task"
    assert len(fake.calls) == 1
    call = fake.calls[0]
    assert call["disable_thinking"] is True
    assert call["json_mode"] is True
    assert call["timeout_seconds"] == 3.0


@pytest.mark.asyncio
async def test_classify_llm_foreground_verdict() -> None:
    dispatcher = BackgroundDispatcher()
    fake = _FakeLLMService(response='{"background": false}')
    _patch_llm_service(dispatcher, fake)

    decision = await dispatcher.classify(
        BackgroundDecisionContext(user_text="summarise the inbox")
    )

    assert decision.disposition is BackgroundDisposition.FOREGROUND
    assert decision.source is BackgroundDecisionSource.LLM


@pytest.mark.asyncio
async def test_classify_degrades_to_foreground_on_llm_timeout() -> None:
    dispatcher = BackgroundDispatcher()
    fake = _FakeLLMService(exc=asyncio.TimeoutError())
    _patch_llm_service(dispatcher, fake)

    decision = await dispatcher.classify(
        BackgroundDecisionContext(user_text="summarise the inbox")
    )

    assert decision.disposition is BackgroundDisposition.FOREGROUND
    assert decision.source is BackgroundDecisionSource.FALLBACK
    assert decision.reason == "llm_error_or_timeout"


@pytest.mark.asyncio
async def test_classify_degrades_to_foreground_on_llm_error() -> None:
    dispatcher = BackgroundDispatcher()
    fake = _FakeLLMService(exc=RuntimeError("provider down"))
    _patch_llm_service(dispatcher, fake)

    decision = await dispatcher.classify(
        BackgroundDecisionContext(user_text="summarise the inbox")
    )

    assert decision.disposition is BackgroundDisposition.FOREGROUND
    assert decision.source is BackgroundDecisionSource.FALLBACK


@pytest.mark.asyncio
async def test_classify_degrades_when_no_llm_configured() -> None:
    dispatcher = BackgroundDispatcher()
    # Intentionally no LLM wired up.

    decision = await dispatcher.classify(
        BackgroundDecisionContext(user_text="summarise the inbox")
    )

    assert decision.disposition is BackgroundDisposition.FOREGROUND
    assert decision.source is BackgroundDecisionSource.FALLBACK
    assert decision.reason == "no_llm_available"


# ----------------------------------------------------------------------
# Response parsing
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_handles_malformed_llm_response() -> None:
    dispatcher = BackgroundDispatcher()
    fake = _FakeLLMService(response="not json at all")
    _patch_llm_service(dispatcher, fake)

    decision = await dispatcher.classify(
        BackgroundDecisionContext(user_text="summarise the inbox")
    )

    assert decision.disposition is BackgroundDisposition.FOREGROUND
    assert decision.source is BackgroundDecisionSource.FALLBACK


@pytest.mark.asyncio
async def test_classify_handles_missing_background_field() -> None:
    dispatcher = BackgroundDispatcher()
    fake = _FakeLLMService(response=json.dumps({"verdict": "background"}))
    _patch_llm_service(dispatcher, fake)

    decision = await dispatcher.classify(
        BackgroundDecisionContext(user_text="summarise the inbox")
    )

    assert decision.disposition is BackgroundDisposition.FOREGROUND
    assert decision.source is BackgroundDecisionSource.FALLBACK


# ----------------------------------------------------------------------
# Decision object ergonomics
# ----------------------------------------------------------------------


def test_background_decision_is_background_property() -> None:
    background = BackgroundDecision(
        disposition=BackgroundDisposition.BACKGROUND,
        source=BackgroundDecisionSource.RULE,
    )
    foreground = BackgroundDecision(
        disposition=BackgroundDisposition.FOREGROUND,
        source=BackgroundDecisionSource.FALLBACK,
    )

    assert background.is_background is True
    assert foreground.is_background is False
