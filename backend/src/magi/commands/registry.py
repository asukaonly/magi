"""Canonical catalog for every user-visible slash command."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..skills.service_access import get_enabled_skill_names
from ..tools.registry import ToolRegistry
from .resolver import UserInvocableResolver, get_default_resolver


@dataclass(frozen=True, slots=True)
class CommandDescriptor:
    """One slash command and the runtime owner of its execution."""

    name: str
    kind: str
    execution_owner: str
    description: str = ""
    description_key: str | None = None
    category: str = ""
    visibility: str = "composer"
    dangerous: bool = False
    arguments_schema: tuple[dict[str, Any], ...] = ()
    context_mode: str | None = None
    reasoning_preference: str | None = None
    argument_hint: str | None = None
    tags: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "execution_owner": self.execution_owner,
            "description": self.description,
            "description_key": self.description_key,
            "category": self.category,
            "visibility": self.visibility,
            "dangerous": self.dangerous,
            "parameters": [dict(item) for item in self.arguments_schema],
            "context_mode": self.context_mode,
            "reasoning_preference": self.reasoning_preference,
            "argument_hint": self.argument_hint,
            "tags": list(self.tags),
        }


_BUILTIN_COMMANDS: tuple[CommandDescriptor, ...] = (
    CommandDescriptor(
        name="clear",
        kind="client",
        execution_owner="client",
        description_key="chat.commands.internal.clear",
        dangerous=True,
    ),
    CommandDescriptor(
        name="new-session",
        kind="client",
        execution_owner="client",
        description_key="chat.commands.internal.newSession",
    ),
    CommandDescriptor(
        name="cancel",
        kind="control",
        execution_owner="client",
        description_key="chat.commands.internal.cancel",
    ),
    CommandDescriptor(
        name="help",
        kind="client",
        execution_owner="client",
        description_key="chat.commands.internal.help",
    ),
    CommandDescriptor(
        name="auto",
        kind="control",
        execution_owner="client",
        description_key="chat.reasoning.auto.description",
        reasoning_preference="auto",
    ),
    CommandDescriptor(
        name="fast",
        kind="control",
        execution_owner="client",
        description_key="chat.reasoning.fast.description",
        reasoning_preference="fast",
    ),
    CommandDescriptor(
        name="deep",
        kind="control",
        execution_owner="client",
        description_key="chat.reasoning.deep.description",
        reasoning_preference="deep",
    ),
)


class CommandRegistry:
    """Assemble built-in, tool, and skill commands without duplicate catalogs."""

    def __init__(
        self,
        *,
        tool_registry: ToolRegistry,
        tool_resolver: UserInvocableResolver | None = None,
        skill_indexer_provider: Callable[[], Any] | None = None,
    ) -> None:
        self._tools = tool_registry
        self._tool_resolver = tool_resolver or get_default_resolver()
        self._skill_indexer_provider = skill_indexer_provider

    def list_descriptors(self) -> list[CommandDescriptor]:
        descriptors = [*_BUILTIN_COMMANDS, *self._tool_descriptors(), *self._skill_descriptors()]
        return sorted(descriptors, key=lambda item: (item.name, item.kind))

    def _tool_descriptors(self) -> list[CommandDescriptor]:
        result: list[CommandDescriptor] = []
        for name in self._tool_resolver.list_user_invocable(self._tools):
            info = self._tools.get_tool_info(name) or {}
            result.append(
                CommandDescriptor(
                    name=name,
                    kind="tool",
                    execution_owner="command_runner",
                    description=str(info.get("description") or ""),
                    category=str(info.get("category") or ""),
                    dangerous=bool(info.get("dangerous", False)),
                    arguments_schema=tuple(
                        dict(item)
                        for item in (info.get("parameters") or [])
                        if isinstance(item, dict)
                    ),
                )
            )
        return result

    def _skill_descriptors(self) -> list[CommandDescriptor]:
        if self._skill_indexer_provider is None:
            return []
        try:
            indexer = self._skill_indexer_provider()
            enabled = set(get_enabled_skill_names())
        except RuntimeError:
            return []
        result: list[CommandDescriptor] = []
        for name in indexer.get_skill_names():
            metadata = indexer.get_metadata(name)
            if (
                metadata is None
                or name not in enabled
                or not metadata.user_invocable
            ):
                continue
            context_mode = metadata.context or "inline"
            result.append(
                CommandDescriptor(
                    name=metadata.name,
                    kind="skill",
                    execution_owner=(
                        "background_driver" if context_mode == "fork" else "agent_run"
                    ),
                    description=metadata.description or "",
                    category=metadata.category or "",
                    context_mode=context_mode,
                    argument_hint=metadata.argument_hint,
                    tags=tuple(metadata.tags or ()),
                )
            )
        return result


__all__ = ["CommandDescriptor", "CommandRegistry"]
