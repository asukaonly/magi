"""Context-layer owner for prompt package assembly."""

from __future__ import annotations

from dataclasses import dataclass
import inspect
from typing import Any, Callable

from ..core.logger import get_logger
from ..personality.models import EmotionalState
from ..personality.turn_planner import PersonaRoutingHint
from .assembler import PromptContextAssembler, PromptContextRenderer
from .contracts import PromptPackage
from .policy import ContextPolicy
from .scenarios import Scenario

logger = get_logger(__name__)


@dataclass(slots=True)
class _ResolvedPromptPersona:
    persona_id: str
    persona_name: str
    config: Any


class _PromptPersonaMemory:
    """Prompt-only self-memory facade for non-active personas."""

    def __init__(self, *, persona_id: str, persona_name: str, config: Any) -> None:
        self.persona_id = persona_id
        self.personality_name = persona_name
        self._config = config

    async def get_core_personality(self) -> Any:
        return self._config

    async def get_emotional_state(self) -> EmotionalState:
        return EmotionalState()

    async def get_relationship(self, user_id: str) -> dict[str, Any]:
        _ = user_id
        return {}

    async def get_milestones(self, limit: int = 200) -> list[dict[str, Any]]:
        _ = limit
        return []


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
        session_workspace_provider=None,
        persona_lookup: Callable[[str], Any] | None = None,
        policy: ContextPolicy | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._agent_type = agent_type
        self._prompt_context_assembler = prompt_context_assembler
        self._prompt_context_renderer = prompt_context_renderer
        self._retrieval_memory_provider = retrieval_memory_provider
        self._memory = memory
        self._session_workspace_provider = session_workspace_provider
        self._persona_lookup = persona_lookup
        self._policy = policy or ContextPolicy()

    async def build_prompt_package(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        user_message: str = "",
        attachments: list[dict[str, Any]] | None = None,
        task_category: str,
        tools: list[str] | None = None,
        scenario: str = Scenario.CHAT,
        recent_tool_errors: list[dict[str, Any]] | None = None,
        workspace_path: str | None = None,
        include_tool_catalog: bool = True,
        persona_id: str | None = None,
        persona_routing_hint: PersonaRoutingHint | None = None,
        allow_implicit_memory: bool = True,
    ) -> PromptPackage:
        policy = self._policy.decide(
            user_message=user_message,
            task_category=task_category,
        )
        resolved_workspace_path = await self._resolve_workspace_path(
            user_id=user_id,
            session_id=session_id,
            workspace_path=workspace_path,
        )
        retrieved_memory_payload = self._empty_retrieval_payload()
        if (
            allow_implicit_memory
            and policy.retrieve_implicit_memory
            and policy.retrieval_query
            and self._retrieval_memory_provider is not None
        ):
            retrieved_memory_payload = await self._retrieval_memory_provider(
                user_id=user_id,
                session_id=session_id,
                query=policy.retrieval_query,
                task_category=task_category,
                context_text=user_message,
                workspace_path=resolved_workspace_path,
                allowed_layers=policy.allowed_layers,
            )
        (
            prompt_memory,
            prompt_persona_name,
            resolved_persona_id,
        ) = await self._resolve_prompt_persona(persona_id)
        prompt_context = await self._prompt_context_assembler.assemble(
            agent_id=self._agent_id,
            agent_type=self._agent_type,
            scenario=scenario,
            task_category=task_category,
            user_id=user_id,
            self_memory=prompt_memory,
            tool_result={"tools": list(tools or [])},
            retrieved_memory_payload=retrieved_memory_payload,
            persona_name=prompt_persona_name,
            user_message=user_message,
            workspace_path=resolved_workspace_path,
            attachments=list(attachments or []),
            persona_routing_hint=persona_routing_hint,
        )
        if resolved_persona_id:
            prompt_context.metadata["persona_id"] = resolved_persona_id
        system_prompt = self._prompt_context_renderer.render_system_prompt(
            prompt_context,
            include_tool_catalog=include_tool_catalog,
        )
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
        attachments: list[dict[str, Any]] | None = None,
        task_category: str,
        tools: list[str] | None = None,
        scenario: str = Scenario.CHAT,
        recent_tool_errors: list[dict[str, Any]] | None = None,
        workspace_path: str | None = None,
        include_tool_catalog: bool = True,
        persona_id: str | None = None,
        persona_routing_hint: PersonaRoutingHint | None = None,
        allow_implicit_memory: bool = True,
    ):
        package = await self.build_prompt_package(
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
            attachments=attachments,
            task_category=task_category,
            tools=tools,
            scenario=scenario,
            recent_tool_errors=recent_tool_errors,
            workspace_path=workspace_path,
            include_tool_catalog=include_tool_catalog,
            persona_id=persona_id,
            persona_routing_hint=persona_routing_hint,
            allow_implicit_memory=allow_implicit_memory,
        )
        return package.prompt_context

    async def build_system_prompt(
        self,
        *,
        user_id: str,
        session_id: str | None = None,
        user_message: str = "",
        attachments: list[dict[str, Any]] | None = None,
        task_category: str,
        tools: list[str] | None = None,
        scenario: str = Scenario.CHAT,
        recent_tool_errors: list[dict[str, Any]] | None = None,
        workspace_path: str | None = None,
        include_tool_catalog: bool = True,
        persona_id: str | None = None,
        persona_routing_hint: PersonaRoutingHint | None = None,
        allow_implicit_memory: bool = True,
    ) -> str:
        package = await self.build_prompt_package(
            user_id=user_id,
            session_id=session_id,
            user_message=user_message,
            attachments=attachments,
            task_category=task_category,
            tools=tools,
            scenario=scenario,
            recent_tool_errors=recent_tool_errors,
            workspace_path=workspace_path,
            include_tool_catalog=include_tool_catalog,
            persona_id=persona_id,
            persona_routing_hint=persona_routing_hint,
            allow_implicit_memory=allow_implicit_memory,
        )
        return package.system_prompt

    async def _resolve_prompt_persona(
        self,
        persona_id: str | None,
    ) -> tuple[Any, str, str | None]:
        base_memory = self._memory
        base_persona_name = str(getattr(base_memory, "personality_name", "") or "").strip()
        normalized_persona_id = str(persona_id or "").strip()
        if not normalized_persona_id:
            return base_memory, base_persona_name, None

        if (
            base_memory is not None
            and str(getattr(base_memory, "persona_id", "") or "").strip() == normalized_persona_id
        ):
            return base_memory, base_persona_name, normalized_persona_id

        resolved = await self._lookup_persona_for_prompt(normalized_persona_id)
        if resolved is None:
            logger.warning(
                "Prompt persona lookup failed; falling back to active persona | persona_id=%s",
                normalized_persona_id,
            )
            return base_memory, base_persona_name, None
        return (
            _PromptPersonaMemory(
                persona_id=resolved.persona_id,
                persona_name=resolved.persona_name,
                config=resolved.config,
            ),
            resolved.persona_name,
            resolved.persona_id,
        )

    async def _lookup_persona_for_prompt(self, persona_id: str) -> _ResolvedPromptPersona | None:
        try:
            if self._persona_lookup is not None:
                raw = self._persona_lookup(persona_id)
                if inspect.isawaitable(raw):
                    raw = await raw
                return self._coerce_resolved_prompt_persona(persona_id, raw)

            from ..personality.persona_repository import PersonaRepository
            from ..utils.runtime import get_runtime_paths

            repo = PersonaRepository(str(get_runtime_paths().persona_registry_db_path))
            await repo.init()
            record = await repo.get(persona_id, include_deleted=True)
            return _ResolvedPromptPersona(
                persona_id=record.persona_id,
                persona_name=record.slug,
                config=record.config,
            )
        except Exception as exc:
            logger.debug("Failed to resolve prompt persona", persona_id=persona_id, error=str(exc))
            return None

    @staticmethod
    def _coerce_resolved_prompt_persona(
        persona_id: str,
        raw: Any,
    ) -> _ResolvedPromptPersona | None:
        if raw is None:
            return None
        if isinstance(raw, dict):
            config = raw.get("config") or raw.get("personality_config")
            persona_name = str(raw.get("slug") or raw.get("persona_name") or "").strip()
            resolved_id = str(raw.get("persona_id") or persona_id).strip()
        else:
            config = getattr(raw, "config", None) or getattr(raw, "personality_config", None)
            persona_name = str(
                getattr(raw, "slug", None) or getattr(raw, "persona_name", None) or ""
            ).strip()
            resolved_id = str(getattr(raw, "persona_id", None) or persona_id).strip()
        if config is None or not resolved_id or not persona_name:
            return None
        return _ResolvedPromptPersona(
            persona_id=resolved_id,
            persona_name=persona_name,
            config=config,
        )

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
