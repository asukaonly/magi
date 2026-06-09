"""Rules-first interruption classification for chat task-agent runs.

Behaviour by design:

- Step state ``atomic`` or ``side_effecting`` → always DEFER. We never
  yank the rug out from under a write that is already in flight.
- ``aclassify`` calls the LLM classifier first (CONTEXT_DECIDER scenario,
  8s budget). On any failure or unparseable response, falls back to
  ``classify``.
- ``classify`` (synchronous) is intentionally narrow:
    * a strict cancel phrase (full normalized message ∈ phrase list)
      → INTERRUPT
    * everything else → DEFER

We deliberately do NOT keep substring tables for AUGMENT / STEER /
generic INTERRUPT detection. The previous implementation grew those
into 30+ phrases per bucket, was sensitive to user wording, and required
constant tuning. AUGMENT / STEER decisions now live in the LLM
classifier; when the LLM is unavailable, DEFER is the safe default
(the active run continues, the new message is queued).

The ``_STRICT_INTERRUPT_PHRASES`` set is loaded from the sibling
``interruption_phrases.yaml`` so QA / language reviewers can add
canonical cancel phrases without code edits.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from pathlib import Path

import yaml

from magi.config.models import LLMScenario
from magi.agent.task_agents.common import TaskAgentLLMService


MODEL_CLASSIFICATION_TIMEOUT_SECONDS = 8.0

# Matches any run of ASCII/CJK punctuation, whitespace, or other
# non-alphanumeric separators. Used to collapse a user message down to a
# canonical form for strict equality matching.
_STRICT_NORMALIZE_RE = re.compile(
    r"[\s\.,!\?;:\-_\"'`~@#\$%\^&\*\(\)\[\]\{\}<>/\\|"
    "，。！？、；：""''「」『』【】（）《》…—–～]+"
)

_PHRASES_FILE = Path(__file__).with_name("interruption_phrases.yaml")


@lru_cache(maxsize=1)
def _load_strict_interrupt_phrases() -> frozenset[str]:
    """Read canonical cancel phrases from the sibling YAML resource."""
    try:
        raw = yaml.safe_load(_PHRASES_FILE.read_text(encoding="utf-8")) or {}
    except FileNotFoundError:
        return frozenset()
    phrases: set[str] = set()
    for bucket in raw.values() if isinstance(raw, dict) else ():
        if isinstance(bucket, list):
            for entry in bucket:
                normalized = str(entry or "").strip()
                if normalized:
                    phrases.add(normalized)
    return frozenset(phrases)


class InterruptionDisposition(str, Enum):
    """How a new user turn should affect the active run."""

    INTERRUPT = "interrupt"
    AUGMENT = "augment"
    STEER = "steer"
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

    def classify(self, context: InterruptionContext) -> InterruptionDisposition:
        """Synchronous fallback: only strict cancel and atomic-state defer.

        AUGMENT / STEER / non-strict INTERRUPT decisions intentionally
        require the LLM classifier. When neither path can decide, we
        return DEFER — the safer default that preserves active-run
        progress while queueing the new message.
        """
        if context.step_state.atomic or context.step_state.side_effecting:
            return InterruptionDisposition.DEFER
        if self.looks_like_strict_interrupt(context.user_text):
            return InterruptionDisposition.INTERRUPT
        return InterruptionDisposition.DEFER

    async def aclassify(self, context: InterruptionContext) -> InterruptionDisposition:
        """LLM-first classifier; falls back to ``classify`` on failure."""
        if context.step_state.atomic or context.step_state.side_effecting:
            return InterruptionDisposition.DEFER
        if self._can_use_model_classifier():
            disposition = await self._classify_with_model(context)
            if disposition is not None:
                return disposition
        return self.classify(context)

    @classmethod
    def _strict_normalize(cls, user_text: str) -> str:
        """Lowercase and strip all punctuation/whitespace for strict matching."""
        return _STRICT_NORMALIZE_RE.sub("", user_text.lower())

    def looks_like_strict_interrupt(self, user_text: str) -> bool:
        """Return True only when the full normalized message equals a cancel phrase.

        Substring matching is intentionally NOT performed: long messages
        that merely mention a cancel keyword in passing must fall through
        to the LLM classifier instead of pre-emptively cancelling the
        active run.
        """
        normalized = self._strict_normalize(user_text)
        if not normalized:
            return False
        return normalized in _load_strict_interrupt_phrases()

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
                    "Choose augment when the new message re-scopes the task (changes the target, swaps a tool, "
                    "or otherwise invalidates progress already made). "
                    "Choose steer when the new message adds context or constraints to the same task without "
                    "changing its target (e.g. 'also include 2024 data', 'by the way, focus on Europe'). "
                    "Choose defer when the intent is unclear or should not change the active task yet. "
                    'Valid dispositions are: "interrupt", "augment", "steer", "defer".'
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
