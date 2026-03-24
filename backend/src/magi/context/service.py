"""Context-layer owner for prompt package assembly."""

from __future__ import annotations

import inspect
from typing import Any

from .assembler import PromptContextAssembler, PromptContextRenderer
from .contracts import PromptPackage
from .policy import ContextPolicy
from .scenarios import Scenario


class ContextAssemblyService:
    """Own prompt-context retrieval, assembly, and final system prompt rendering."""

    def __init__(
        self,
        *,
        agent_id: str,
        agent_type: str,
        prompt_context_assembler: PromptContextAssembler,
        prompt_context_renderer: PromptContextRenderer,
        retrieval_memory_provider,
        memory=None,
        other_memory=None,
        session_workspace_provider=None,
        policy: ContextPolicy | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._agent_type = agent_type
        self._prompt_context_assembler = prompt_context_assembler
        self._prompt_context_renderer = prompt_context_renderer
        self._retrieval_memory_provider = retrieval_memory_provider
        self._memory = memory
        self._other_memory = other_memory
        self._session_workspace_provider = session_workspace_provider
        self._policy = policy or ContextPolicy()

    async def build_prompt_package(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        user_message: str = "",
        task_category: str,
        tools: list[str] | None = None,
        scenario: str = Scenario.CHAT,
        recent_tool_errors: list[dict[str, Any]] | None = None,
        workspace_path: str | None = None,
    ) -> PromptPackage:
        policy = self._policy.decide(
            user_message=user_message,
            task_category=task_category,
        )
        retrieved_memory_payload = self._empty_retrieval_payload()
        if policy.retrieve_implicit_memory and policy.retrieval_query and self._retrieval_memory_provider is not None:
            retrieved_memory_payload = await self._retrieval_memory_provider(
                user_id=user_id,
                session_id=session_id,
                query=policy.retrieval_query,
                task_category=task_category,
                allowed_layers=policy.allowed_layers,
            )

        resolved_workspace_path = await self._resolve_workspace_path(
            user_id=user_id,
            session_id=session_id,
            workspace_path=workspace_path,
        )
        prompt_context = await self._prompt_context_assembler.assemble(
            agent_id=self._agent_id,
            agent_type=self._agent_type,
            scenario=scenario,
            task_category=task_category,
            user_id=user_id,
            self_memory=self._memory,
            other_memory=self._other_memory,
            tool_result={"tools": list(tools or [])},
            retrieved_memory_payload=retrieved_memory_payload,
            state_transition_override=None,
            persona_name=self._memory.personality_name if self._memory else "default",
            workspace_path=resolved_workspace_path,
        )
        system_prompt = self._prompt_context_renderer.render_system_prompt(prompt_context)
        recent_tool_errors_block = self.build_recent_tool_errors_block(recent_tool_errors or [])
        if recent_tool_errors_block:
            system_prompt = f"{system_prompt}\n\n{recent_tool_errors_block}"
        return PromptPackage(
            prompt_context=prompt_context,
            system_prompt=system_prompt,
            recent_tool_errors_block=recent_tool_errors_block,
        )

    async def build_prompt_context(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        user_message: str = "",
        task_category: str,
        tools: list[str] | None = None,
        scenario: str = Scenario.CHAT,
        recent_tool_errors: list[dict[str, Any]] | None = None,
        workspace_path: str | None = None,
    ):
        package = await self.build_prompt_package(
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
            task_category=task_category,
            tools=tools,
            scenario=scenario,
            recent_tool_errors=recent_tool_errors,
            workspace_path=workspace_path,
        )
        return package.prompt_context

    async def build_system_prompt(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        user_message: str = "",
        task_category: str,
        tools: list[str] | None = None,
        scenario: str = Scenario.CHAT,
        recent_tool_errors: list[dict[str, Any]] | None = None,
        workspace_path: str | None = None,
    ) -> str:
        package = await self.build_prompt_package(
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
            task_category=task_category,
            tools=tools,
            scenario=scenario,
            recent_tool_errors=recent_tool_errors,
            workspace_path=workspace_path,
        )
        return package.system_prompt

    async def _resolve_workspace_path(
        self,
        *,
        user_id: str,
        session_id: str | None,
        workspace_path: str | None,
    ) -> str | None:
        normalized_workspace_path = str(workspace_path or "").strip()
        if normalized_workspace_path:
            return normalized_workspace_path
        if self._session_workspace_provider is None or not str(session_id or "").strip():
            return None
        resolved = self._session_workspace_provider(user_id=user_id, session_id=str(session_id))
        if inspect.isawaitable(resolved):
            resolved = await resolved
        normalized_resolved_workspace_path = str(resolved or "").strip()
        return normalized_resolved_workspace_path or None

    @staticmethod
    def build_recent_tool_errors_block(recent_tool_errors: list[dict[str, Any]]) -> str:
        lines: list[str] = []
        for item in recent_tool_errors[:3]:
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("tool_name") or "unknown")
            error_code = str(item.get("error_code") or "UNKNOWN")
            error_message = str(item.get("error_message") or "").strip()
            config_path = str(item.get("config_path") or "").strip()
            next_action = str(item.get("next_action") or "").strip()
            line = f"- {tool_name}: {error_code}"
            if error_message:
                line += f" | {error_message}"
            if config_path:
                line += f" | config_path={config_path}"
            if next_action:
                line += f" | next_action={next_action}"
            lines.append(line)
        if not lines:
            return ""
        return "\n".join(
            [
                "# Recent Tool Errors",
                "Use these concrete failures as the source of truth for follow-up answers. Do not invent alternative config paths or switch tools unless the user explicitly asks to do so.",
                *lines,
            ]
        )

    @staticmethod
    def _empty_retrieval_payload() -> dict[str, Any]:
        return {
            "l0_workbench": [],
            "l2_entity_cards": [],
            "l3_reflection_memory": [],
            "l4_procedural_memory": [],
            "preference_memory": {},
        }
