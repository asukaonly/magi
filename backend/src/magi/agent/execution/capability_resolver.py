"""Deterministic initial capability selection for unified agent runs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from ...tools.system_tools import resolve_resident_system_tools
from .tool_metadata import ToolEffectClass, resolve_tool_capability_metadata


@dataclass(frozen=True, slots=True)
class CapabilityRejection:
    """One requested capability omitted by a stable runtime guard."""

    tool_name: str
    reason_code: str

    def to_dict(self) -> dict[str, str]:
        return {"tool_name": self.tool_name, "reason_code": self.reason_code}


@dataclass(frozen=True, slots=True)
class CapabilityResolution:
    """Auditable capability view assembled before the first model step."""

    candidate_tools: tuple[str, ...]
    initial_exposed_tools: tuple[str, ...]
    resident_tools: tuple[str, ...]
    pinned_tools: tuple[str, ...] = ()
    required_tools: tuple[str, ...] = ()
    continuity_pinned_tools: tuple[str, ...] = ()
    rejected_tools: tuple[CapabilityRejection, ...] = ()

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "candidate_tools": list(self.candidate_tools),
            "initial_exposed_tools": list(self.initial_exposed_tools),
            "resident_tools": list(self.resident_tools),
            "pinned_tools": list(self.pinned_tools),
            "required_tools": list(self.required_tools),
            "continuity_pinned_tools": list(self.continuity_pinned_tools),
            "rejected_tools": [item.to_dict() for item in self.rejected_tools],
        }


class CapabilityResolver:
    """Build a bounded, message-independent initial tool catalog."""

    def __init__(self, tool_registry: Any) -> None:
        self._registry = tool_registry

    def resolve(
        self,
        *,
        pinned_tools: Iterable[str] = (),
        required_tools: Iterable[str] = (),
        recent_tool_errors: Iterable[dict[str, Any]] = (),
        enabled_features: list[str] | None = None,
        model_supports_tool_calls: bool = True,
    ) -> CapabilityResolution:
        registered_tools = set(
            self._registry.list_tools(enabled_features=enabled_features)
        )
        get_skill_names = getattr(self._registry, "get_skill_names", None)
        registered_skills = (
            {str(name) for name in get_skill_names()}
            if callable(get_skill_names)
            else set()
        )
        registered = registered_tools | registered_skills
        resident = _ordered_registered(
            resolve_resident_system_tools(self._registry),
            registered,
        )
        continuity = _continuity_tools(recent_tool_errors, registered)
        pinned_requested = _dedupe(pinned_tools)
        required_requested = _dedupe(required_tools)
        requested = _dedupe([*pinned_requested, *required_requested, *continuity])
        hard_required = [name for name in required_requested if name in registered]
        if not model_supports_tool_calls:
            candidates = _dedupe([*resident, *requested])
            return CapabilityResolution(
                candidate_tools=tuple(candidates),
                initial_exposed_tools=(),
                resident_tools=(),
                pinned_tools=(),
                required_tools=tuple(hard_required),
                continuity_pinned_tools=(),
                rejected_tools=tuple(
                    CapabilityRejection(name, "model_tool_calls_unsupported")
                    for name in candidates
                ),
            )
        rejected = tuple(
            CapabilityRejection(name, "not_registered_or_disabled")
            for name in requested
            if name not in registered
        )
        pinned = [name for name in requested if name in registered and name not in resident]

        validation_tools: list[str] = []
        if "verify" in registered and any(
            resolve_tool_capability_metadata(self._registry, name).effect_class
            in {ToolEffectClass.LOCAL_WRITE, ToolEffectClass.UNKNOWN}
            for name in pinned
        ):
            validation_tools.append("verify")
        candidates = _dedupe([*resident, *requested, *validation_tools])

        # Resident, explicitly pinned, and validation capabilities cannot be
        # displaced. The active model's schema limits make the final fail-closed
        # decision instead of silently removing a capability required by policy.
        exposed = _dedupe([*resident, *pinned, *validation_tools])
        return CapabilityResolution(
            candidate_tools=tuple(candidates),
            initial_exposed_tools=tuple(exposed),
            resident_tools=tuple(resident),
            pinned_tools=tuple(pinned),
            required_tools=tuple(hard_required),
            continuity_pinned_tools=tuple(name for name in continuity if name in exposed),
            rejected_tools=rejected,
        )


def _continuity_tools(
    recent_tool_errors: Iterable[dict[str, Any]],
    registered: set[str],
) -> list[str]:
    """Pin only the most recent failed tool for one bounded follow-up view."""

    for item in recent_tool_errors:
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool_name") or item.get("name") or "").strip()
        if name and name in registered:
            return [name]
    return []


def _ordered_registered(names: Iterable[str], registered: set[str]) -> list[str]:
    return [name for name in _dedupe(names) if name in registered]


def _dedupe(names: Iterable[str]) -> list[str]:
    result: list[str] = []
    for raw_name in names:
        name = str(raw_name or "").strip()
        if name and name not in result:
            result.append(name)
    return result


__all__ = [
    "CapabilityRejection",
    "CapabilityResolution",
    "CapabilityResolver",
]
