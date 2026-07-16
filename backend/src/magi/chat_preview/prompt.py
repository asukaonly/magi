"""Build persona-preview prompts through the normal chat prompt pipeline."""

from __future__ import annotations

from typing import Any

from magi.context.assembler import PromptContextAssembler
from magi.context.renderer import PromptContextRenderer
from magi.context.scenarios import Scenario
from magi.context.service import ContextAssemblyService
from magi.personality.loader import PersonalityConfig


async def build_preview_system_prompt(
    *,
    persona_config: PersonalityConfig,
    user_message: str,
) -> str:
    """Return the same persona-aware system prompt used by a first chat turn.

    The service is intentionally ephemeral: it has no chat session, memory
    provider, journal service, profile service, or tool catalog. Those normal
    first-turn inputs therefore stay empty without introducing preview-only
    prompt rules or persistence paths.
    """
    persona_id = "onboarding-preview"

    def resolve_persona(_persona_id: str) -> dict[str, Any]:
        return {
            "persona_id": persona_id,
            "slug": persona_config.name,
            "config": persona_config,
        }

    service = ContextAssemblyService(
        agent_id="chat-preview",
        agent_type="chat",
        prompt_context_assembler=PromptContextAssembler(),
        prompt_context_renderer=PromptContextRenderer(),
        retrieval_memory_provider=None,
        memory=None,
        session_workspace_provider=None,
        persona_lookup=resolve_persona,
    )
    package = await service.build_prompt_package(
        user_id="default_user",
        user_message=user_message,
        task_category="chat",
        tools=[],
        scenario=Scenario.CHAT,
        include_tool_catalog=False,
        persona_id=persona_id,
    )
    return package.system_prompt


__all__ = ["build_preview_system_prompt"]
