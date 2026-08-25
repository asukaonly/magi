"""Tool-surface expansion after runtime discovery results."""

from __future__ import annotations

from typing import Any

from ..tool_metadata import ToolEffectClass, resolve_tool_capability_metadata
from .step_models import FunctionCallingStepState


def apply_tool_expansion_from_results(
    host: Any,
    *,
    state: FunctionCallingStepState,
    tool_results: list[Any],
) -> list[str]:
    if state.tool_expansion_count >= host._MAX_TOOL_EXPANSIONS_PER_TURN:
        return []
    raw_append_tools = _collect_requested_tool_names(tool_results)
    if not raw_append_tools:
        return []

    additions = _filter_known_additions(
        host,
        raw_append_tools=raw_append_tools,
        known_names=set(state.selected_tool_names),
        max_additions=int(host._MAX_TOOLS_PER_EXPANSION),
    )
    additions = _ensure_validation_companion(
        host,
        additions=additions,
        selected_names=set(state.selected_tool_names),
        max_additions=int(host._MAX_TOOLS_PER_EXPANSION),
    )
    if not additions:
        return []

    state.selected_tool_names.extend(additions)
    state.tools = host._build_tools_parameter(state.selected_tool_names)
    state.tool_expansion_count += 1
    return additions


def _collect_requested_tool_names(tool_results: list[Any]) -> list[str]:
    raw_append_tools: list[str] = []
    for result in tool_results:
        if not getattr(result, "success", False):
            continue
        data = getattr(result, "data", None)
        if not isinstance(data, dict):
            continue
        expansion = data.get("tool_expansion")
        if not isinstance(expansion, dict):
            continue
        append_tools = expansion.get("append_tools")
        if isinstance(append_tools, list):
            raw_append_tools.extend(str(item or "").strip() for item in append_tools)
    return raw_append_tools


def _ensure_validation_companion(
    host: Any,
    *,
    additions: list[str],
    selected_names: set[str],
    max_additions: int,
) -> list[str]:
    if not additions or "verify" in selected_names:
        return additions
    validation_required = {
        name
        for name in additions
        if resolve_tool_capability_metadata(host.tool_registry, name).effect_class
        in {ToolEffectClass.LOCAL_WRITE, ToolEffectClass.UNKNOWN}
    }
    if not validation_required:
        return additions
    verify_name = _normalize_known_tool_name(host, "verify")
    if verify_name is None or verify_name in additions:
        return additions
    if max_additions < 2:
        return []
    # Verification is a policy companion, so it displaces the lowest-ranked
    # read-only capability when the bounded expansion is already full. A tool
    # that created the validation obligation must never be the displaced item.
    admitted = list(additions)
    if len(admitted) >= max_additions:
        drop_index = next(
            (
                index
                for index in range(len(admitted) - 1, -1, -1)
                if admitted[index] not in validation_required
            ),
            len(admitted) - 1,
        )
        admitted.pop(drop_index)
    return [*admitted, verify_name]


def _filter_known_additions(
    host: Any,
    *,
    raw_append_tools: list[str],
    known_names: set[str],
    max_additions: int,
) -> list[str]:
    additions: list[str] = []
    for raw_name in raw_append_tools:
        if len(additions) >= max_additions:
            break
        normalized = _normalize_known_tool_name(host, raw_name)
        if normalized is None or normalized in known_names:
            continue
        known_names.add(normalized)
        additions.append(normalized)
    return additions


def _normalize_known_tool_name(host: Any, raw_name: str) -> str | None:
    name = str(raw_name or "").strip()
    if not name:
        return None
    skill_name = name.lstrip("/")
    resolve_tool_name = getattr(host.tool_registry, "resolve_tool_name", None)
    normalized = (
        resolve_tool_name(name)
        if callable(resolve_tool_name) and not name.startswith("/")
        else skill_name
    )
    if _is_registered_tool_or_skill(host, normalized=normalized, skill_name=skill_name):
        return normalized
    return None


def _is_registered_tool_or_skill(
    host: Any,
    *,
    normalized: str,
    skill_name: str,
) -> bool:
    get_tool_info = getattr(host.tool_registry, "get_tool_info", None)
    is_skill = getattr(host.tool_registry, "is_skill", None)
    known_tool = callable(get_tool_info) and get_tool_info(normalized) is not None
    known_skill = callable(is_skill) and is_skill(skill_name)
    return bool(known_tool or known_skill)


__all__ = ["apply_tool_expansion_from_results"]
