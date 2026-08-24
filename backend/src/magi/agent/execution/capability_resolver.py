"""Deterministic initial capability selection for unified agent runs."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

from ...tools.discovery_index import ToolDiscoveryIndex
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
    discovery_scores: dict[str, float] = field(default_factory=dict)

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "candidate_tools": list(self.candidate_tools),
            "initial_exposed_tools": list(self.initial_exposed_tools),
            "resident_tools": list(self.resident_tools),
            "pinned_tools": list(self.pinned_tools),
            "required_tools": list(self.required_tools),
            "continuity_pinned_tools": list(self.continuity_pinned_tools),
            "rejected_tools": [item.to_dict() for item in self.rejected_tools],
            "discovery_scores": dict(self.discovery_scores),
        }


class CapabilityResolver:
    """Build a bounded tool catalog without semantic intent classification."""

    def __init__(self, tool_registry: Any, *, top_k: int = 4, max_tools: int = 12) -> None:
        self._registry = tool_registry
        self._top_k = max(0, top_k)
        self._max_tools = max(1, max_tools)

    def resolve(
        self,
        *,
        user_message: str,
        explicit_tools: Iterable[str] = (),
        attachment_tools: Iterable[str] = (),
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
        required_requested = _dedupe([*explicit_tools, *attachment_tools])
        requested = _dedupe([*required_requested, *continuity])
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

        discovery_rows: list[dict[str, Any]] = []
        if self._top_k and str(user_message or "").strip():
            index = ToolDiscoveryIndex.from_registry(
                self._registry,
                enabled_features=enabled_features,
            )
            discovery_rows = index.search(
                query=user_message,
                limit=self._top_k,
                current_tools=[*resident, *pinned],
            )
        discovered = [
            str(row.get("name") or "")
            for row in discovery_rows
            if row.get("type") in {"tool", "skill"}
            and str(row.get("name") or "") in registered
        ]
        if (
            "verify" in registered
            and any(
                resolve_tool_capability_metadata(self._registry, name).effect_class
                in {ToolEffectClass.LOCAL_WRITE, ToolEffectClass.UNKNOWN}
                for name in [*pinned, *discovered]
            )
        ):
            discovered.append("verify")
        candidates = _dedupe([*resident, *requested, *discovered])

        # Resident and pinned capabilities cannot be displaced by general Top-K
        # results. If those required groups exceed the normal budget, retain them
        # and let the provider schema budget make the final fail-closed decision.
        required = _dedupe([*resident, *pinned])
        remaining = max(0, self._max_tools - len(required))
        optional = [name for name in discovered if name not in required][:remaining]
        exposed = _dedupe([*required, *optional])
        return CapabilityResolution(
            candidate_tools=tuple(candidates),
            initial_exposed_tools=tuple(exposed),
            resident_tools=tuple(resident),
            pinned_tools=tuple(pinned),
            required_tools=tuple(hard_required),
            continuity_pinned_tools=tuple(name for name in continuity if name in exposed),
            rejected_tools=rejected,
            discovery_scores={
                str(row.get("name")): float(row.get("score") or 0.0)
                for row in discovery_rows
                if row.get("type") in {"tool", "skill"} and row.get("name")
            },
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
