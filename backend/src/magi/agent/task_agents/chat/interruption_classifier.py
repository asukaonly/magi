"""Rules-first interruption classification for chat task-agent runs."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum

from ....config.models import LLMScenario
from ..common import TaskAgentLLMService


MODEL_CLASSIFICATION_TIMEOUT_SECONDS = 8.0


class InterruptionDisposition(str, Enum):
    """How a new user turn should affect the active run."""

    INTERRUPT = "interrupt"
    AUGMENT = "augment"
    DEFER = "defer"


@dataclass(slots=True)
class StepState:
    """Execution-step constraints that affect interruption handling."""

    atomic: bool = False
    side_effecting: bool = False


@dataclass(slots=True)
class InterruptionContext:
    """Input to the interruption classifier."""

    user_text: str
    root_user_message: str = ""
    pending_turns: list[str] = field(default_factory=list)
    step_state: StepState = field(default_factory=StepState)


class InterruptionClassifier:
    """Classify how a newly arrived user turn should affect the active run."""

    def __init__(
        self,
        *,
        llm_adapter=None,
        llm_pool=None,
    ) -> None:
        self._llm_adapter = llm_adapter
        self._llm_pool = llm_pool
        self._llm_service = TaskAgentLLMService(
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
            scenario=LLMScenario.CONTEXT_DECIDER,
            logger_name="chat_interrupt",
        )

    _INTERRUPT_PATTERNS = (
        "stop",
        "cancel",
        "abort",
        "change the goal",
        "change goal",
        "new goal",
        "new plan",
        "switch to",
        "don't do that",
        "dont do that",
        "never mind",
        "不用做了",
        "先停",
        "停一下",
        "停止",
        "取消",
        "搞错了",
    )
    _AUGMENT_PATTERNS = (
        "also",
        "additionally",
        "by the way",
        "for context",
        "one more thing",
        "more context",
        "more detail",
        "in addition",
        "instead of",
        "only happens after",
        "only happens when",
        "happens after",
        "happens when",
        "staging endpoint",
        "staging environment",
        "staging env",
        "另外",
        "补充",
        "顺便",
        "还有",
    )

    def classify(self, context: InterruptionContext) -> InterruptionDisposition:
        """Return the disposition for the new user turn."""
        if context.step_state.atomic or context.step_state.side_effecting:
            return InterruptionDisposition.DEFER
        if self._looks_like_interrupt(context.user_text):
            return InterruptionDisposition.INTERRUPT
        if self._looks_like_augment(context.user_text):
            return InterruptionDisposition.AUGMENT
        return InterruptionDisposition.DEFER

    async def aclassify(self, context: InterruptionContext) -> InterruptionDisposition:
        """Classify using a fast model first, then fall back to rules."""
        if context.step_state.atomic or context.step_state.side_effecting:
            return InterruptionDisposition.DEFER
        if self._can_use_model_classifier():
            disposition = await self._classify_with_model(context)
            if disposition is not None:
                return disposition
        return self.classify(context)

    def _looks_like_interrupt(self, user_text: str) -> bool:
        normalized_text = user_text.lower()
        return any(pattern in normalized_text for pattern in self._INTERRUPT_PATTERNS)

    def _looks_like_augment(self, user_text: str) -> bool:
        normalized_text = user_text.lower()
        return any(pattern in normalized_text for pattern in self._AUGMENT_PATTERNS)

    def _can_use_model_classifier(self) -> bool:
        if self._llm_pool is not None:
            return True
        return bool(getattr(self._llm_adapter, "provider_name", None))

    async def _classify_with_model(self, context: InterruptionContext) -> InterruptionDisposition | None:
        payload = {
            "active_request": context.root_user_message,
            "pending_user_messages": [item for item in context.pending_turns if str(item).strip()],
            "new_user_message": context.user_text,
        }
        try:
            response = await self._llm_service.call(
                system_prompt=(
                    "You classify how a new user chat message should affect an already-running task. "
                    "Return JSON only with one field: disposition. "
                    "Choose interrupt when the user wants to stop, cancel, replace, or abandon the active task. "
                    "Choose augment when the new message adds constraints, clarifications, or extra context to the same task. "
                    "Choose defer when the intent is unclear or should not change the active task yet. "
                    'Valid dispositions are: "interrupt", "augment", "defer".'
                ),
                messages=[{"role": "user", "content": json.dumps(payload, ensure_ascii=False)}],
                disable_thinking=True,
                json_mode=True,
                timeout_seconds=MODEL_CLASSIFICATION_TIMEOUT_SECONDS,
            )
        except Exception:
            return None
        return self._parse_model_disposition(response)

    def _parse_model_disposition(self, raw_response: str) -> InterruptionDisposition | None:
        text = str(raw_response or "").strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            normalized = text.strip().lower()
            return InterruptionDisposition(normalized) if normalized in InterruptionDisposition._value2member_map_ else None
        if not isinstance(parsed, dict):
            return None
        normalized = str(parsed.get("disposition") or "").strip().lower()
        return InterruptionDisposition(normalized) if normalized in InterruptionDisposition._value2member_map_ else None
