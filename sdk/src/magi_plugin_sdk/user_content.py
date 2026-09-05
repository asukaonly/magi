"""Shared contracts for plugin-owned user-content deletion."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Literal

if TYPE_CHECKING:
    from .sensors import PluginRuntimePaths


@dataclass(frozen=True, slots=True)
class UserContentClearRequest:
    """Describe one host-owned full user-content clear generation.

    The generation is issued by the host's existing global clear boundary. It
    is not a plugin-local counter and plugins must not advance it themselves.
    """

    clear_generation: int | None = None
    reason: str = "user_clear_all_data"
    connection_id: str | None = None

    def __post_init__(self) -> None:
        if self.connection_id is None:
            if (
                isinstance(self.clear_generation, bool)
                or not isinstance(self.clear_generation, int)
                or self.clear_generation < 1
            ):
                raise ValueError("Global clear generation must be a positive integer")
        elif not self.connection_id.strip() or self.clear_generation is not None:
            raise ValueError("Connection clear requires an identity and no global generation")
        normalized_reason = str(self.reason or "").strip()
        if not normalized_reason:
            raise ValueError("reason must not be empty")
        object.__setattr__(self, "reason", normalized_reason)


@dataclass(frozen=True, slots=True)
class UserContentClearContext:
    """Give one plugin or sensor the local-only clear contract.

    A clear hook may remove locally retained collected content, derived
    content, buffered events, and unfinished user-content work. It must keep
    the installed package, configuration, credentials, connected-account
    state, and source-only cursors or watermarks. The hook must not perform
    network I/O.
    """

    request: UserContentClearRequest
    runtime_paths: "PluginRuntimePaths"
    plugin_id: str
    sensor_id: str | None = None
    plugin_settings: Mapping[str, Any] = field(default_factory=dict)
    connection_id: str | None = None

    network_access_allowed: ClassVar[Literal[False]] = False
    preserve_configuration: ClassVar[Literal[True]] = True
    preserve_credentials: ClassVar[Literal[True]] = True
    preserve_accounts: ClassVar[Literal[True]] = True
    preserve_source_progress: ClassVar[Literal[True]] = True

    def __post_init__(self) -> None:
        if self.request.connection_id is not None and self.connection_id != self.request.connection_id:
            raise ValueError("Clear context must match the requested connection")
        normalized_plugin_id = str(self.plugin_id or "").strip()
        if not normalized_plugin_id:
            raise ValueError("plugin_id must not be empty")
        normalized_sensor_id = (
            str(self.sensor_id).strip() if self.sensor_id is not None else None
        )
        if self.sensor_id is not None and not normalized_sensor_id:
            raise ValueError("sensor_id must not be empty")
        object.__setattr__(self, "plugin_id", normalized_plugin_id)
        object.__setattr__(self, "sensor_id", normalized_sensor_id)
        object.__setattr__(
            self,
            "plugin_settings",
            _freeze_snapshot(dict(self.plugin_settings)),
        )


def _freeze_snapshot(value: Any) -> Any:
    """Recursively copy JSON-like settings into immutable containers."""

    if isinstance(value, Mapping):
        return MappingProxyType(
            {key: _freeze_snapshot(item) for key, item in value.items()}
        )
    if isinstance(value, list | tuple):
        return tuple(_freeze_snapshot(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze_snapshot(item) for item in value)
    return deepcopy(value)


__all__ = ["UserContentClearContext", "UserContentClearRequest"]
