"""Action contribution contracts and registry."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel, Field

from .contracts import ExtensionFieldSpec, PluginContribution
from ..tools.schema import ParameterType, Tool, ToolExecutionContext, ToolParameter, ToolResult, ToolSchema


class ActionSpec(BaseModel):
    """Declarative metadata for an action capability."""

    action_id: str
    display_name: str
    description: str = ""
    surface: str = "actions"
    dangerous: bool = False
    required_permissions: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    fields: list[ExtensionFieldSpec] = Field(default_factory=list)
    tool_adapter_name: Optional[str] = None
    tool_adapter_description: Optional[str] = None


class ActionExecutionContext(BaseModel):
    """Execution context passed to action implementations."""

    user_id: Optional[str] = None
    session_id: Optional[str] = None
    runtime_key: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class BaseAction(ABC):
    """Base class for plugin-contributed actions."""

    def __init__(self) -> None:
        self.spec = self.build_spec()

    @abstractmethod
    def build_spec(self) -> ActionSpec:
        """Return action metadata."""

    @abstractmethod
    async def execute(
        self,
        parameters: dict[str, Any],
        context: ActionExecutionContext,
    ) -> dict[str, Any]:
        """Execute the action."""


class ActionRegistry:
    """Registry for action contributions."""

    def __init__(self) -> None:
        self._actions: dict[str, BaseAction] = {}
        self._plugin_ownership: dict[str, str] = {}

    def register(self, plugin_id: str, action: BaseAction) -> None:
        self._actions[action.spec.action_id] = action
        self._plugin_ownership[action.spec.action_id] = plugin_id

    def unregister(self, action_id: str) -> None:
        self._actions.pop(action_id, None)
        self._plugin_ownership.pop(action_id, None)

    def get_action(self, action_id: str) -> Optional[BaseAction]:
        return self._actions.get(action_id)

    def list_actions(self) -> list[BaseAction]:
        return list(self._actions.values())

    def list_contributions(self, plugin_id: Optional[str] = None) -> list[PluginContribution]:
        contributions: list[PluginContribution] = []
        for action_id, action in self._actions.items():
            owner = self._plugin_ownership.get(action_id, "")
            if plugin_id is not None and owner != plugin_id:
                continue
            contributions.append(
                PluginContribution(
                    plugin_id=owner,
                    contribution_id=action_id,
                    contribution_type="action",
                    display_name=action.spec.display_name,
                    description=action.spec.description,
                    surface="actions",
                    fields=list(action.spec.fields),
                    metadata={
                        "dangerous": action.spec.dangerous,
                        "required_permissions": list(action.spec.required_permissions),
                        "tool_adapter_name": action.spec.tool_adapter_name,
                    },
                )
            )
        return contributions


def build_action_tool_class(action: BaseAction) -> type[Tool] | None:
    """Build a tool adapter for an action when declared."""

    spec = action.spec
    if not spec.tool_adapter_name:
        return None

    parameters = []
    properties = dict(spec.input_schema.get("properties", {}))
    required = set(spec.input_schema.get("required", []))
    for name, schema in properties.items():
        parameters.append(
            ToolParameter(
                name=name,
                type=_json_schema_to_parameter_type(str(schema.get("type", "string"))),
                description=str(schema.get("description", "")),
                required=name in required,
                default=schema.get("default"),
                enum=schema.get("enum"),
            )
        )

    class _ActionToolAdapter(Tool):
        def _init_schema(self) -> None:
            self.schema = ToolSchema(
                name=str(spec.tool_adapter_name),
                description=str(spec.tool_adapter_description or spec.description),
                category="action",
                parameters=parameters,
                dangerous=spec.dangerous,
                metadata={"action_id": spec.action_id},
            )

        async def execute(
            self,
            parameters: dict[str, Any],
            context: ToolExecutionContext,
        ) -> ToolResult:
            result = await action.execute(
                parameters,
                ActionExecutionContext(
                    user_id=context.agent_id,
                    runtime_key=context.task_id,
                    metadata={"permissions": list(context.permissions)},
                ),
            )
            return ToolResult(success=True, data=result)

    _ActionToolAdapter.__name__ = f"{spec.action_id.replace('-', '_').title()}ActionToolAdapter"
    return _ActionToolAdapter


def _json_schema_to_parameter_type(value: str) -> ParameterType:
    mapping = {
        "string": ParameterType.STRING,
        "integer": ParameterType.INTEGER,
        "number": ParameterType.FLOAT,
        "boolean": ParameterType.BOOLEAN,
        "array": ParameterType.ARRAY,
        "object": ParameterType.OBJECT,
    }
    return mapping.get(value, ParameterType.STRING)
