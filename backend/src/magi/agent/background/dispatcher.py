"""Decide whether an execution request should run in the background.

Per decision 6 in ``docs/dev/background-task-design.md``:

1. A planner/LLM-side ``run_in_background`` hint bypasses the pipeline
   entirely — if present, its value is honored verbatim.
2. Otherwise a rule fast path returns a **tri-state** verdict
   (``YES`` / ``NO`` / ``UNKNOWN``). Clear signals short-circuit the
   pipeline without an extra LLM hop.
3. Only ``UNKNOWN`` verdicts degrade to the LLM classifier. It runs
   with ``disable_thinking=true``, ``json_mode=true`` and a hard
   **3 s** budget.
4. Any LLM error / timeout degrades to ``FOREGROUND`` — the chat path
   remains the safe default.

The dispatcher has no chat-runtime coupling; ``BackgroundLaunchHandler``
(phase 3c) calls it and routes to :class:`BackgroundTaskManager`
accordingly.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import structlog

from ...config.models import LLMScenario
from ..task_agents.common import TaskAgentLLMService

__all__ = [
    "BackgroundDecision",
    "BackgroundDecisionContext",
    "BackgroundDecisionSource",
    "BackgroundDisposition",
    "BackgroundDispatcher",
    "BackgroundRuleOutcome",
]


logger = structlog.get_logger(__name__)


MODEL_CLASSIFICATION_TIMEOUT_SECONDS = 3.0


class BackgroundDisposition(str, Enum):
    """Final routing verdict produced by :class:`BackgroundDispatcher`."""

    FOREGROUND = "foreground"
    BACKGROUND = "background"


class BackgroundRuleOutcome(str, Enum):
    """Tri-state verdict produced by the rule fast path."""

    YES = "yes"
    NO = "no"
    UNKNOWN = "unknown"


class BackgroundDecisionSource(str, Enum):
    """Which stage of the pipeline produced a :class:`BackgroundDecision`."""

    PLANNER = "planner"
    RULE = "rule"
    LLM = "llm"
    FALLBACK = "fallback"


@dataclass(slots=True)
class BackgroundDecisionContext:
    """Input to :meth:`BackgroundDispatcher.classify`."""

    user_text: str
    selected_tools: list[str] = field(default_factory=list)
    planner_flag: bool | None = None  # ``run_in_background`` hint from planner.


@dataclass(slots=True)
class BackgroundDecision:
    """The routing verdict returned to the chat runtime."""

    disposition: BackgroundDisposition
    source: BackgroundDecisionSource
    reason: str | None = None

    @property
    def is_background(self) -> bool:
        return self.disposition is BackgroundDisposition.BACKGROUND


# ----------------------------------------------------------------------
# Rule keyword sets
# ----------------------------------------------------------------------

# Explicit "run this later / run this in the background" phrases in both
# CJK and English. Substring match (case-insensitive).
_BACKGROUND_KEYWORDS: tuple[str, ...] = (
    # English
    "run in background",
    "run this in background",
    "in the background",
    "background task",
    "run later",
    "do it later",
    "run async",
    "async task",
    "kick this off",
    "detach this",
    "don't wait",
    "dont wait",
    "no need to wait",
    "take your time",
    "take as long as",
    # Chinese
    "后台跑",
    "后台执行",
    "放后台",
    "跑到后台",
    "慢慢跑",
    "慢慢做",
    "慢慢查",
    "不用等",
    "不等了",
    "跑完告诉我",
    "跑完叫我",
    "跑完喊我",
    "跑完通知",
    "先搁那里",
    "放那儿跑",
)

# Explicit "I want this now / stay here / short answer" phrases that
# strongly suggest foreground.
_FOREGROUND_KEYWORDS: tuple[str, ...] = (
    "right now",
    "immediately",
    "quick question",
    "quickly",
    "just tell me",
    "one liner",
    "one-liner",
    "tl;dr",
    "马上",
    "立刻",
    "现在就",
    "快速",
    "简短",
    "一句话",
)

# Tools that are inherently long-running. Presence of any of these in
# ``selected_tools`` nudges toward background.
_LONG_RUNNING_TOOLS: frozenset[str] = frozenset(
    {
        "deep_research",
        "deep_research_multistep",
        "web_crawl",
        "repo_clone",
        "repo_index",
        "bulk_embed",
        "long_running_bash",
        "video_process",
        "transcribe_long",
    }
)


class BackgroundDispatcher:
    """Rule + LLM dispatcher for foreground/background routing."""

    def __init__(
        self,
        *,
        llm_adapter: Any | None = None,
        llm_pool: Any | None = None,
        timeout_seconds: float = MODEL_CLASSIFICATION_TIMEOUT_SECONDS,
    ) -> None:
        self._llm_adapter = llm_adapter
        self._llm_pool = llm_pool
        self._timeout_seconds = timeout_seconds
        self._llm_service = TaskAgentLLMService(
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
            scenario=LLMScenario.CONTEXT_DECIDER,
            logger_name="background_dispatcher",
        )

    # ------------------------------------------------------------------
    # Rule fast path
    # ------------------------------------------------------------------

    def classify_rule(
        self, context: BackgroundDecisionContext
    ) -> BackgroundRuleOutcome:
        """Return the tri-state verdict from the rule fast path alone."""
        text = context.user_text.lower()

        has_background_keyword = any(kw in text for kw in _BACKGROUND_KEYWORDS)
        has_foreground_keyword = any(kw in text for kw in _FOREGROUND_KEYWORDS)
        has_long_tool = any(
            tool in _LONG_RUNNING_TOOLS for tool in context.selected_tools
        )

        # Conflict → unknown; only the LLM can resolve mixed signals.
        if has_background_keyword and has_foreground_keyword:
            return BackgroundRuleOutcome.UNKNOWN
        if has_background_keyword:
            return BackgroundRuleOutcome.YES
        if has_foreground_keyword:
            return BackgroundRuleOutcome.NO
        if has_long_tool:
            return BackgroundRuleOutcome.YES
        return BackgroundRuleOutcome.UNKNOWN

    # ------------------------------------------------------------------
    # Full pipeline
    # ------------------------------------------------------------------

    async def classify(
        self, context: BackgroundDecisionContext
    ) -> BackgroundDecision:
        """Resolve ``context`` to a final :class:`BackgroundDecision`.

        Stage order:

        1. planner flag (explicit override),
        2. rule fast path (short-circuits on YES/NO),
        3. LLM classifier (3 s budget) on UNKNOWN,
        4. safe fallback to FOREGROUND on any failure.
        """
        if context.planner_flag is True:
            return BackgroundDecision(
                disposition=BackgroundDisposition.BACKGROUND,
                source=BackgroundDecisionSource.PLANNER,
                reason="planner_hint",
            )
        if context.planner_flag is False:
            return BackgroundDecision(
                disposition=BackgroundDisposition.FOREGROUND,
                source=BackgroundDecisionSource.PLANNER,
                reason="planner_hint",
            )

        rule = self.classify_rule(context)
        if rule is BackgroundRuleOutcome.YES:
            return BackgroundDecision(
                disposition=BackgroundDisposition.BACKGROUND,
                source=BackgroundDecisionSource.RULE,
            )
        if rule is BackgroundRuleOutcome.NO:
            return BackgroundDecision(
                disposition=BackgroundDisposition.FOREGROUND,
                source=BackgroundDecisionSource.RULE,
            )

        if not self._can_use_model_classifier():
            return BackgroundDecision(
                disposition=BackgroundDisposition.FOREGROUND,
                source=BackgroundDecisionSource.FALLBACK,
                reason="no_llm_available",
            )

        llm_decision = await self._classify_with_model(context)
        if llm_decision is not None:
            return llm_decision
        return BackgroundDecision(
            disposition=BackgroundDisposition.FOREGROUND,
            source=BackgroundDecisionSource.FALLBACK,
            reason="llm_error_or_timeout",
        )

    # ------------------------------------------------------------------
    # LLM fallback
    # ------------------------------------------------------------------

    def _can_use_model_classifier(self) -> bool:
        if self._llm_pool is not None:
            return True
        return bool(getattr(self._llm_adapter, "provider_name", None))

    async def _classify_with_model(
        self, context: BackgroundDecisionContext
    ) -> BackgroundDecision | None:
        payload = {
            "user_message": context.user_text,
            "selected_tools": list(context.selected_tools),
        }
        try:
            response = await self._llm_service.call(
                system_prompt=(
                    "You decide whether a user request should run as a"
                    " background task or stay in the foreground chat."
                    " Return JSON only with two fields:"
                    ' {"background": true|false, "reason": "<short>"}.'
                    " Choose background when the work is likely to take"
                    " more than a minute (deep research, crawling a site,"
                    " large code analysis) or the user explicitly asks"
                    " for it to run later. Otherwise choose foreground."
                ),
                messages=[
                    {
                        "role": "user",
                        "content": json.dumps(payload, ensure_ascii=False),
                    }
                ],
                disable_thinking=True,
                json_mode=True,
                timeout_seconds=self._timeout_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - degrade safe
            logger.debug(
                "background dispatcher LLM fallback failed",
                error=str(exc),
            )
            return None
        return self._parse_model_response(response)

    @staticmethod
    def _parse_model_response(raw_response: Any) -> BackgroundDecision | None:
        text = str(raw_response or "").strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
        except Exception:
            return None
        if not isinstance(parsed, dict):
            return None
        flag = parsed.get("background")
        if not isinstance(flag, bool):
            return None
        reason = parsed.get("reason")
        return BackgroundDecision(
            disposition=(
                BackgroundDisposition.BACKGROUND
                if flag
                else BackgroundDisposition.FOREGROUND
            ),
            source=BackgroundDecisionSource.LLM,
            reason=str(reason).strip() if isinstance(reason, str) and reason.strip() else None,
        )
