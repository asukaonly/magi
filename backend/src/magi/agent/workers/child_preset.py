"""Capability and reasoning bounds for child agent runs."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import json
from typing import Any

from ...config.models import ThinkingDepth
from ..execution.reasoning import ReasoningPolicy, ReasoningPreference, ReasoningState
from ..execution.tool_metadata import ToolEffectClass, resolve_tool_capability_metadata


class ChildRunPreset(str, Enum):
    """Small execution policies that do not classify user intent."""

    DEFAULT = "default"
    READ_ONLY = "read_only"
    WORKSPACE_WRITE = "workspace_write"
    REVIEW = "review"


@dataclass(frozen=True, slots=True)
class ChildPresetPolicy:
    """Runtime-enforced capability and reasoning recommendations."""

    preset: ChildRunPreset
    allowed_effects: frozenset[ToolEffectClass]
    preferred_initial_depth: ThinkingDepth
    maximum_depth: ThinkingDepth
    max_escalations: int


_POLICIES = {
    ChildRunPreset.DEFAULT: ChildPresetPolicy(
        preset=ChildRunPreset.DEFAULT,
        allowed_effects=frozenset({ToolEffectClass.READ_ONLY}),
        preferred_initial_depth=ThinkingDepth.LOW,
        maximum_depth=ThinkingDepth.HIGH,
        max_escalations=2,
    ),
    ChildRunPreset.READ_ONLY: ChildPresetPolicy(
        preset=ChildRunPreset.READ_ONLY,
        allowed_effects=frozenset({ToolEffectClass.READ_ONLY}),
        preferred_initial_depth=ThinkingDepth.LOW,
        maximum_depth=ThinkingDepth.HIGH,
        max_escalations=2,
    ),
    ChildRunPreset.WORKSPACE_WRITE: ChildPresetPolicy(
        preset=ChildRunPreset.WORKSPACE_WRITE,
        allowed_effects=frozenset(
            {ToolEffectClass.READ_ONLY, ToolEffectClass.LOCAL_WRITE}
        ),
        preferred_initial_depth=ThinkingDepth.MEDIUM,
        maximum_depth=ThinkingDepth.HIGH,
        max_escalations=1,
    ),
    ChildRunPreset.REVIEW: ChildPresetPolicy(
        preset=ChildRunPreset.REVIEW,
        allowed_effects=frozenset({ToolEffectClass.READ_ONLY}),
        preferred_initial_depth=ThinkingDepth.MEDIUM,
        maximum_depth=ThinkingDepth.HIGH,
        max_escalations=1,
    ),
}

_DEPTH_RANK = {
    ThinkingDepth.NONE: 0,
    ThinkingDepth.LOW: 1,
    ThinkingDepth.MEDIUM: 2,
    ThinkingDepth.HIGH: 3,
    ThinkingDepth.MAX: 4,
}


def parse_child_preset(value: Any) -> ChildRunPreset | None:
    """Parse the exact public preset contract."""

    try:
        return ChildRunPreset(str(value or "").strip())
    except ValueError:
        return None


def child_preset_policy(preset: ChildRunPreset) -> ChildPresetPolicy:
    return _POLICIES[preset]


def resolve_child_tools(tool_registry: Any, preset: ChildRunPreset) -> list[str]:
    """Resolve child capabilities from canonical effect metadata."""

    policy = child_preset_policy(preset)
    excluded = {"agent", "todo_write", "ask_user_question", "detach_to_background"}
    selected: list[str] = []
    for name in sorted(tool_registry.list_tools()):
        if name in excluded:
            continue
        metadata = resolve_tool_capability_metadata(tool_registry, name)
        if metadata.effect_class in policy.allowed_effects:
            selected.append(name)
    return selected


def resolve_child_reasoning_policy(
    *,
    preset: ChildRunPreset,
    parent_policy: ReasoningPolicy,
    parent_state: ReasoningState | None,
) -> ReasoningPolicy:
    """Bound a child recommendation by parent policy and remaining budget."""

    preset_policy = child_preset_policy(preset)
    maximum = _shallower(parent_policy.maximum_depth, preset_policy.maximum_depth)
    initial = _shallower(preset_policy.preferred_initial_depth, maximum)
    remaining_escalations = max(
        0,
        parent_policy.max_escalations
        - (parent_state.escalation_count if parent_state is not None else 0),
    )
    return ReasoningPolicy(
        preference=parent_policy.preference,
        initial_depth=initial,
        maximum_depth=maximum,
        max_escalations=min(preset_policy.max_escalations, remaining_escalations),
    )


def parent_reasoning_policy_from_env(env_vars: dict[str, Any]) -> ReasoningPolicy:
    value = _decode_mapping(env_vars.get("parent_reasoning_policy"))
    if isinstance(value, dict):
        return ReasoningPolicy.from_dict(value)
    preference = str(value or "").strip()
    if preference:
        try:
            return ReasoningPolicy.from_preference(ReasoningPreference(preference))
        except ValueError:
            pass
    return ReasoningPolicy()


def parent_reasoning_state_from_env(env_vars: dict[str, Any]) -> ReasoningState | None:
    value = _decode_mapping(env_vars.get("parent_reasoning_state"))
    if not isinstance(value, dict):
        return None
    try:
        return ReasoningState.from_dict(value)
    except (KeyError, TypeError, ValueError):
        return None


def _shallower(left: ThinkingDepth, right: ThinkingDepth) -> ThinkingDepth:
    return left if _DEPTH_RANK[left] <= _DEPTH_RANK[right] else right


def _decode_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value.strip().startswith("{"):
        return None
    try:
        decoded = json.loads(value)
    except json.JSONDecodeError:
        return None
    return decoded if isinstance(decoded, dict) else None


__all__ = [
    "ChildPresetPolicy",
    "ChildRunPreset",
    "child_preset_policy",
    "parent_reasoning_policy_from_env",
    "parent_reasoning_state_from_env",
    "parse_child_preset",
    "resolve_child_reasoning_policy",
    "resolve_child_tools",
]
