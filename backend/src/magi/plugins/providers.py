"""Replaceable provider slots with connection ownership and revocation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

from magi_plugin_sdk.runtime import PluginConnection

ProviderKind = Literal["web_search", "model", "external_agent"]


@dataclass(frozen=True)
class _ProviderBinding:
    plugin_id: str
    connection_id: str
    implementation: Any


class PluginProviderRegistry:
    """Keep provider selection live so replacements and unloads take effect."""

    def __init__(self, *, get_connection: Callable[[str], PluginConnection | None]) -> None:
        self._get_connection = get_connection
        self._providers: dict[tuple[str, str], _ProviderBinding] = {}
        self._revision = 0

    @property
    def revision(self) -> tuple[Any, ...]:
        """Include connection readiness changes when invalidating provider caches."""
        connections = {entry.connection_id for entry in self._providers.values()}
        return (
            self._revision,
            *(
                (
                    (connection_id, connection.revision, connection.enabled)
                    if (connection := self._get_connection(connection_id)) is not None
                    else (connection_id, None, False)
                )
                for connection_id in sorted(connections)
            ),
        )

    def register(
        self,
        *,
        plugin_id: str,
        connection_id: str,
        kind: ProviderKind,
        provider_id: str,
        implementation: Any,
    ) -> Callable[[], None]:
        """Replace a named slot; only this registration may remove the new value."""
        if kind not in {"web_search", "model", "external_agent"} or not provider_id.strip():
            raise ValueError("Invalid plugin provider kind or identifier")
        methods = {
            "web_search": ("is_ready", "execute"),
            "external_agent": ("invoke", "stream"),
            "model": ("invoke", "stream"),
        }
        if any(
            not callable(getattr(implementation, method, None)) for method in methods.get(kind, ())
        ):
            raise ValueError(f"Provider does not implement the {kind} contract")
        key = (kind, provider_id)
        if key in self._providers:
            raise ValueError(f"Provider is already registered: {kind}:{provider_id}")
        binding = _ProviderBinding(plugin_id, connection_id, implementation)
        self._providers[key] = binding
        self._revision += 1

        def dispose() -> None:
            if self._providers.get(key) is binding:
                del self._providers[key]
                self._revision += 1

        return dispose

    def get(self, kind: ProviderKind, provider_id: str) -> Any | None:
        """Resolve only live providers belonging to enabled matching connections."""
        binding = self._providers.get((kind, provider_id))
        if binding is None:
            return None
        connection = self._get_connection(binding.connection_id)
        if (
            connection is None
            or not connection.enabled
            or connection.plugin_id != binding.plugin_id
        ):
            return None
        return binding.implementation

    def names(self, kind: ProviderKind) -> list[str]:
        """Return providers selectable for the requested service kind."""
        return [
            name
            for candidate_kind, name in self._providers
            if candidate_kind == kind and self.get(kind, name) is not None
        ]

    def describe(self, kind: ProviderKind) -> list[dict[str, str]]:
        """Expose live host-owned selection metadata without provider objects."""
        entries = []
        for provider_id in self.names(kind):
            connection = self.connection_for(kind, provider_id)
            entries.append(
                {
                    "provider_id": provider_id,
                    "plugin_id": connection.plugin_id,
                    "connection_id": connection.connection_id,
                    "display_name": f"{connection.display_name} / {provider_id.rsplit(':', 1)[-1]}",
                }
            )
        return sorted(entries, key=lambda item: item["provider_id"])

    def connection_for(self, kind: ProviderKind, provider_id: str) -> PluginConnection:
        """Return the current owner for host-side SDK adapters."""
        if self.get(kind, provider_id) is None:
            raise KeyError(provider_id)
        return self._get_connection(self._providers[(kind, provider_id)].connection_id)

    def bind_tool(self, tool: Any) -> Callable[[], None]:
        """Attach live selection to production search and external-agent tools."""
        name = tool.get_schema().name
        kind = {
            "web-search": "web_search",
            "delegate_to_external_coder": "external_agent",
        }.get(name)
        binder = getattr(tool, "bind_provider_registry", None)
        if kind is None or not callable(binder):
            return lambda: None
        return binder(self, kind=kind)


__all__ = ["PluginProviderRegistry", "ProviderKind"]
