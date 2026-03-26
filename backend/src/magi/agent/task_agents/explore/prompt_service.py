"""Prompt and plain LLM helpers for ExploreTaskAgent."""
from __future__ import annotations

from ....config.models import LLMScenario, ThinkingDepth
from ..common import TaskAgentLLMService


class ExplorePromptService:
    """Owns ExploreTaskAgent plain LLM calls."""

    def __init__(self, *, llm_adapter=None, llm_pool=None) -> None:
        self._llm_service = TaskAgentLLMService(
            llm_adapter=llm_adapter,
            llm_pool=llm_pool,
            scenario=LLMScenario.CORE,
            logger_name="explore-task",
        )

    async def call_llm(
        self,
        *,
        system_prompt: str,
        messages: list[dict[str, str]],
        disable_thinking: bool = False,
        thinking_depth: ThinkingDepth | None = None,
        temperature: float = 0.3,
        json_mode: bool = False,
        timeout_seconds: float | None = None,
    ) -> str:
        return await self._llm_service.call(
            system_prompt=system_prompt,
            messages=messages,
            disable_thinking=disable_thinking,
            thinking_depth=thinking_depth,
            temperature=temperature,
            json_mode=json_mode,
            timeout_seconds=timeout_seconds,
        )
