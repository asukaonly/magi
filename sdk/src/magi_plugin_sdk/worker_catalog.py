"""Explicit contribution catalog and dispatch table for external workers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

SOURCE_METHODS = frozenset(
    {
        "collect_items",
        "discover_changes",
        "fetch_item",
        "build_output",
        "extract_metadata",
        "clear_user_content",
        "source_item_identity",
        "source_item_version_fingerprint",
        "idempotency_key",
        "l2_batch_policy",
        "request_activation_authorization",
        "flush_runtime_state",
        "t",
    }
)
SOURCE_ATTRIBUTES = (
    "source_type",
    "supports_pull_sync",
    "supports_state_flush",
    "supports_watch_mode",
    "memory_event_type",
)
TOOL_METHODS = frozenset(
    {
        "execute",
        "validate_parameters",
        "before_execution",
        "after_execution",
        "clear_user_content",
    }
)
CHANNEL_METHODS = frozenset(
    {
        "start",
        "stop",
        "send_message",
        "send_typing_indicator",
        "deliver",
        "deliver_chunk",
        "revise",
        "retract",
        "deliver_control_request",
    }
)
CHANNEL_ATTRIBUTES = (
    "channel_type",
    "supports_streaming",
    "supports_revision",
    "supports_attachments",
    "supports_control_requests",
    "inbound_clear_strategy",
)
CHANNEL_PORTS = {
    "session_mapper": (
        "resolve_or_create",
        "lookup",
        "lookup_by_session",
        "delete_mapping",
        "get_notification_cursor",
        "update_notification_cursor",
    ),
    "message_dispatcher": (
        "capture_inbound_context",
        "read_current_clear_generation",
        "dispatch_user_message",
    ),
    "attachment_store": ("store_attachment",),
    "control_port": ("handle_command",),
}
PLUGIN_METHODS = frozenset(
    {
        "invoke_operation",
        "read_settings_resource",
        "start_settings_action",
        "poll_settings_action",
        "cancel_settings_action",
        "build_temporal_summary_features",
        "clear_user_content",
        "shutdown",
    }
)


class WorkerCatalog:
    def __init__(self, plugin: Any) -> None:
        self.plugin = plugin
        self.targets: dict[str, tuple[Any, frozenset[str]]] = {
            "plugin": (plugin, PLUGIN_METHODS)
        }

    def describe(self) -> dict[str, Any]:
        plugin = self.plugin
        catalog: dict[str, Any] = {}
        for name in (
            "get_operations",
            "get_channel_fields",
            "get_settings_resources",
            "get_settings_actions",
            "get_summary_profiles",
            "get_extraction_profiles",
        ):
            catalog[name] = getattr(plugin, name)()
        for name, methods in (
            ("get_sources", SOURCE_METHODS),
            ("get_history_importers", frozenset({"parse"})),
        ):
            entries = []
            for index, (identifier, obj, spec) in enumerate(getattr(plugin, name)()):
                target = f"{name}:{index}"
                if name == "get_sources" and callable(
                    getattr(obj, "bind_plugin_context", None)
                ):
                    obj.bind_plugin_context(
                        plugin_id=plugin.plugin_id,
                        plugin_dir=plugin.plugin_dir,
                        connection=plugin.connection,
                        context=plugin.context,
                    )
                self.targets[target] = (obj, methods)
                attrs = (
                    {
                        key: getattr(obj, key)
                        for key in SOURCE_ATTRIBUTES
                        if hasattr(obj, key)
                    }
                    if name == "get_sources"
                    else {}
                )
                entries.append(
                    {
                        "id": identifier,
                        "target": target,
                        "spec": spec,
                        "attributes": attrs,
                        "methods": sorted(
                            method
                            for method in methods
                            if callable(getattr(obj, method, None))
                        ),
                    }
                )
            catalog[name] = entries
        tools = []
        for index, cls in enumerate(plugin.get_tools()):
            obj = cls()
            target = f"tool:{index}"
            self.targets[target] = (obj, TOOL_METHODS)
            tools.append({"target": target, "schema": obj.get_schema()})
        catalog["get_tools"] = tools
        providers = []
        for index, (kind, provider_id, implementation) in enumerate(
            plugin.get_providers()
        ):
            if kind not in {"web_search", "model", "external_agent"}:
                raise ValueError(
                    f"Remote provider kind has no public wire contract: {kind}"
                )
            target = f"provider:{index}"
            methods = (
                frozenset({"execute"})
                if kind == "web_search"
                else frozenset({"invoke", "stream"})
            )
            if any(
                not callable(getattr(implementation, method, None))
                for method in methods
            ):
                raise ValueError(
                    "Remote provider does not implement its public protocol"
                )
            self.targets[target] = (implementation, methods)
            providers.append(
                {
                    "kind": kind,
                    "id": provider_id,
                    "target": target,
                    "display_name": str(
                        getattr(implementation, "display_name", provider_id)
                    ),
                    "ready": bool(implementation.is_ready(dict(plugin.settings)))
                    if kind == "web_search"
                    else True,
                }
            )
        catalog["get_providers"] = providers
        channel = plugin.get_channel()
        catalog["get_channel"] = None
        if channel is not None:
            self.targets["channel"] = (channel, CHANNEL_METHODS)
            catalog["get_channel"] = {
                key: getattr(channel, key) for key in CHANNEL_ATTRIBUTES
            }
        # Executable hook contexts must be represented by public SDK types before
        # admission. Returning an unsupported object fails this worker, not host.
        hooks = []
        for index, (event_type, handler, matcher) in enumerate(plugin.get_hooks()):
            target = f"hook:{index}"
            self.targets[target] = (handler, frozenset({"__call__"}))
            hooks.append(
                {"target": target, "event_type": event_type, "matcher": matcher}
            )
        catalog["get_hooks"] = hooks
        skills = []
        root = Path(plugin.plugin_dir).resolve()
        for identifier, path in plugin.get_skills():
            resolved = Path(path).resolve()
            if (
                not resolved.is_relative_to(root)
                or not (resolved / "SKILL.md").is_file()
            ):
                raise ValueError("Plugin skill must be inside its package")
            skills.append((identifier, resolved))
        catalog["get_skills"] = skills
        return catalog

    def method(self, target: str, name: str) -> Any:
        obj, allowed = self.targets[target]
        if name not in allowed:
            raise PermissionError("Worker method is not in the dispatch allowlist")
        return getattr(obj, name)
