"""Canonical completion and exposure metadata for registered tools."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .tool_effects import ToolEffectReplayPolicy


class ToolEffectClass(str, Enum):
    """The state boundary changed by a successful tool invocation."""

    READ_ONLY = "read_only"
    LOCAL_WRITE = "local_write"
    EXTERNAL_WRITE = "external_write"
    DESTRUCTIVE = "destructive"
    UNKNOWN = "unknown"

    @property
    def reusable_as_extra(self) -> bool:
        return self is ToolEffectClass.READ_ONLY


@dataclass(frozen=True, slots=True)
class ToolCapabilityMetadata:
    """Runtime governance metadata resolved from one registered tool schema."""

    name: str
    effect_class: ToolEffectClass
    replay_policy: ToolEffectReplayPolicy
    permission_class: str
    supports_dry_run: bool = False


def resolve_tool_capability_metadata(
    tool_registry: Any,
    tool_name: str,
) -> ToolCapabilityMetadata:
    """Resolve explicit schema metadata without tool-name heuristics."""

    tool = None
    getter = getattr(tool_registry, "get_tool", None)
    if callable(getter):
        tool = getter(tool_name)
    schema = None
    get_schema = getattr(tool, "get_schema", None)
    if callable(get_schema):
        schema = get_schema()
    raw_effect = getattr(schema, "effect_class", ToolEffectClass.UNKNOWN.value)
    if isinstance(raw_effect, ToolEffectClass):
        raw_effect = raw_effect.value
    try:
        effect_class = ToolEffectClass(str(raw_effect))
    except ValueError:
        effect_class = ToolEffectClass.UNKNOWN

    raw_replay = getattr(schema, "effect_replay_policy", ToolEffectReplayPolicy.UNKNOWN.value)
    if isinstance(raw_replay, ToolEffectReplayPolicy):
        raw_replay = raw_replay.value
    try:
        replay_policy = ToolEffectReplayPolicy(str(raw_replay))
    except ValueError:
        replay_policy = ToolEffectReplayPolicy.UNKNOWN

    # Existing read-only declarations are already an explicit, stronger
    # guarantee than the newly added effect_class default. Preserve that
    # guarantee while external plugin schemas adopt the new field.
    if effect_class is ToolEffectClass.UNKNOWN and replay_policy is ToolEffectReplayPolicy.READ_ONLY:
        effect_class = ToolEffectClass.READ_ONLY

    if bool(getattr(schema, "dangerous", False)):
        permission_class = "dangerous"
    elif bool(getattr(schema, "requires_auth", False)):
        permission_class = "authenticated"
    else:
        permission_class = "standard"
    raw_metadata = getattr(schema, "metadata", None)
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    return ToolCapabilityMetadata(
        name=str(getattr(schema, "name", None) or tool_name),
        effect_class=effect_class,
        replay_policy=replay_policy,
        permission_class=permission_class,
        supports_dry_run=bool(metadata.get("supports_dry_run", False)),
    )


__all__ = [
    "ToolCapabilityMetadata",
    "ToolEffectClass",
    "resolve_tool_capability_metadata",
]
