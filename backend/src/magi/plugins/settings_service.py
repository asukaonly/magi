"""Plugin settings resources and actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import inspect
import secrets
from typing import Any

from .base import Plugin
from .operation_execution import (
    run_plugin_callback_operation,
    run_plugin_lifecycle_operation,
)
from .contracts import (
    ContributionType,
    PluginPackageState,
    PluginSettingsActionResult,
    PluginSettingsActionSpec,
    PluginSettingsResourcePayload,
)


@dataclass(frozen=True)
class PluginSettingsActionRun:
    """Host-owned envelope for one plugin settings action session response."""

    session_id: str
    result: PluginSettingsActionResult


def collect_plugin_settings_actions(plugin_instance: Plugin) -> list[PluginSettingsActionSpec]:
    actions: list[PluginSettingsActionSpec] = []
    for raw_action in plugin_instance.get_settings_actions():
        if isinstance(raw_action, PluginSettingsActionSpec):
            actions.append(raw_action)
        else:
            actions.append(PluginSettingsActionSpec.model_validate(raw_action))
    return actions


def settings_actions_for_contribution(
    actions: list[PluginSettingsActionSpec],
    *,
    contribution_id: str,
    contribution_type: ContributionType,
    surface: str,
) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for action in actions:
        if action.surface != surface:
            continue
        if action.contribution_id:
            if action.contribution_id != contribution_id:
                continue
        elif action.contribution_type != contribution_type:
            continue
        matched.append(action.model_dump(mode="json"))
    return sorted(matched, key=lambda item: int(item.get("order") or 0))


class PluginSettingsService:
    """Run plugin-owned settings resources and actions."""

    def __init__(
        self,
        *,
        get_package: Callable[[str], PluginPackageState | None],
        load_plugin: Callable[[str], PluginPackageState],
        get_loaded_plugin: Callable[[str], Plugin | None],
        update_plugin_settings: Callable[[str, dict[str, Any]], PluginPackageState],
    ) -> None:
        self._get_package = get_package
        self._load_plugin = load_plugin
        self._get_loaded_plugin = get_loaded_plugin
        self._update_plugin_settings = update_plugin_settings

    def read_plugin_settings_resource(
        self,
        plugin_id: str,
        resource_name: str,
    ) -> PluginSettingsResourcePayload:
        """Read a plugin-owned settings resource through the loaded plugin instance."""

        plugin_instance = self._ensure_loaded_plugin(plugin_id)
        resource_specs = {
            spec.resource_name: spec for spec in plugin_instance.get_settings_resources()
        }
        spec = resource_specs.get(resource_name)
        if spec is None:
            raise KeyError(resource_name)

        return PluginSettingsResourcePayload(
            plugin_id=plugin_id,
            resource_name=resource_name,
            resource_type=spec.resource_type,
            data=plugin_instance.read_settings_resource(resource_name),
        )

    async def start_plugin_settings_action(
        self,
        plugin_id: str,
        action_id: str,
        *,
        field_values: dict[str, Any] | None = None,
    ) -> PluginSettingsActionRun:
        """Start a plugin-owned settings action and return its session envelope."""

        spec, plugin_instance = await run_plugin_callback_operation(
            lambda: self._resolve_settings_action(plugin_id, action_id)
        )
        session_id = secrets.token_urlsafe(18)
        result = await self._call_settings_action_start(
            plugin_instance,
            action_id,
            session_id=session_id,
            field_values=field_values,
        )
        await self._persist_successful_action_updates(plugin_id, spec, result)
        return PluginSettingsActionRun(session_id=session_id, result=result)

    async def poll_plugin_settings_action(
        self,
        plugin_id: str,
        action_id: str,
        *,
        session_id: str,
        field_values: dict[str, Any] | None = None,
    ) -> PluginSettingsActionRun:
        """Poll a plugin-owned settings action session."""

        spec, plugin_instance = await run_plugin_callback_operation(
            lambda: self._resolve_settings_action(plugin_id, action_id)
        )
        result = await self._call_settings_action_poll(
            plugin_instance,
            action_id,
            session_id=session_id,
            field_values=field_values,
        )
        await self._persist_successful_action_updates(plugin_id, spec, result)
        return PluginSettingsActionRun(session_id=session_id, result=result)

    async def cancel_plugin_settings_action(
        self,
        plugin_id: str,
        action_id: str,
        *,
        session_id: str,
    ) -> PluginSettingsActionRun:
        """Cancel a plugin-owned settings action session."""

        plugin_instance = (
            await run_plugin_callback_operation(
                lambda: self._resolve_settings_action(plugin_id, action_id)
            )
        )[1]
        result = await run_plugin_callback_operation(
            lambda: plugin_instance.cancel_settings_action(
                action_id,
                session_id=session_id,
            )
        )
        if inspect.isawaitable(result):
            result = await result
        return PluginSettingsActionRun(
            session_id=session_id,
            result=self._coerce_settings_action_result(result),
        )

    def _ensure_loaded_plugin(self, plugin_id: str) -> Plugin:
        state = self._require_package(plugin_id)
        if not state.loaded:
            if not state.enabled:
                raise RuntimeError(
                    f"Plugin {plugin_id} must be enabled before accessing plugin settings"
                )
            self._load_plugin(plugin_id)

        plugin_instance = self._get_loaded_plugin(plugin_id)
        if plugin_instance is None:
            raise RuntimeError(f"Plugin {plugin_id} is not loaded")
        return plugin_instance

    def _resolve_settings_action(
        self,
        plugin_id: str,
        action_id: str,
    ) -> tuple[PluginSettingsActionSpec, Plugin]:
        state = self._require_package(plugin_id)
        plugin_instance = self._ensure_loaded_plugin(plugin_id)

        actions = {
            action.action_id: action for action in collect_plugin_settings_actions(plugin_instance)
        }
        spec = actions.get(action_id)
        if spec is None:
            raise KeyError(action_id)
        if spec.requires_enabled and not state.enabled:
            raise RuntimeError(f"Plugin {plugin_id} must be enabled before running {action_id}")
        return spec, plugin_instance

    async def _call_settings_action_start(
        self,
        plugin_instance: Plugin,
        action_id: str,
        *,
        session_id: str,
        field_values: dict[str, Any] | None,
    ) -> PluginSettingsActionResult:
        result = await run_plugin_callback_operation(
            lambda: plugin_instance.start_settings_action(
                action_id,
                session_id=session_id,
                field_values=field_values,
            )
        )
        if inspect.isawaitable(result):
            result = await result
        return self._coerce_settings_action_result(result)

    async def _call_settings_action_poll(
        self,
        plugin_instance: Plugin,
        action_id: str,
        *,
        session_id: str,
        field_values: dict[str, Any] | None,
    ) -> PluginSettingsActionResult:
        result = await run_plugin_callback_operation(
            lambda: plugin_instance.poll_settings_action(
                action_id,
                session_id=session_id,
                field_values=field_values,
            )
        )
        if inspect.isawaitable(result):
            result = await result
        return self._coerce_settings_action_result(result)

    @staticmethod
    def _coerce_settings_action_result(raw_result: Any) -> PluginSettingsActionResult:
        if isinstance(raw_result, PluginSettingsActionResult):
            return raw_result
        if isinstance(raw_result, dict):
            return PluginSettingsActionResult.model_validate(raw_result)
        raise RuntimeError("Plugin settings action returned an invalid response")

    async def _persist_successful_action_updates(
        self,
        plugin_id: str,
        spec: PluginSettingsActionSpec,
        result: PluginSettingsActionResult,
    ) -> None:
        if result.status != "succeeded" or not spec.persist_settings_on_success:
            return
        if not result.settings_updates:
            return
        await run_plugin_lifecycle_operation(
            lambda: self._update_plugin_settings(
                plugin_id,
                result.settings_updates,
            )
        )

    def _require_package(self, plugin_id: str) -> PluginPackageState:
        state = self._get_package(plugin_id)
        if state is None:
            raise KeyError(f"Unknown plugin package: {plugin_id}")
        return state
