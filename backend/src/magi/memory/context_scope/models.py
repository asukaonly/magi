"""Contracts for identity-based memory context scopes."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Sequence

ContextDimension = Literal["project", "activity", "place", "person", "time"]
SUPPORTED_CONTEXT_DIMENSIONS: tuple[ContextDimension, ...] = (
    "project",
    "activity",
    "place",
    "person",
    "time",
)

_CONTEXT_ID_RE = re.compile(r"^ctx_(project|activity|place|person|time)_[0-9a-f]{64}$")


class ContextScopeError(ValueError):
    """Raised when a context scope does not use the stable identity contract."""

    def __init__(self, message: str, *, code: str = "context_scope_invalid") -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, order=True, slots=True)
class ContextCondition:
    """One stable context identity required for a scoped claim to apply."""

    dimension: ContextDimension
    context_id: str

    def to_dict(self) -> dict[str, str]:
        return {"dimension": self.dimension, "context_id": self.context_id}


@dataclass(frozen=True, slots=True)
class ContextResolutionSignals:
    """Trusted local signals used to resolve the current retrieval context."""

    workspace_path: str | None = None
    user_text: str = ""
    task_category: str = ""

    @property
    def is_empty(self) -> bool:
        return not any(
            (
                str(self.workspace_path or "").strip(),
                self.user_text.strip(),
                self.task_category.strip(),
            )
        )


@dataclass(frozen=True, slots=True)
class ContextOption:
    """A selectable context identity returned by the product API."""

    context_id: str
    dimension: ContextDimension
    label: str
    binding_kind: str
    binding_id: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "context_id": self.context_id,
            "dimension": self.dimension,
            "label": self.label,
        }


def normalize_context_resolution_signals(
    signals: object | None,
) -> ContextResolutionSignals | None:
    """Validate and normalize trusted retrieval context signals."""
    if signals is None or isinstance(signals, ContextResolutionSignals):
        return signals
    if not isinstance(signals, Mapping):
        raise ContextScopeError("Context resolution signals must be an object")
    return ContextResolutionSignals(
        workspace_path=str(signals.get("workspace_path") or "").strip() or None,
        user_text=str(signals.get("user_text") or ""),
        task_category=str(signals.get("task_category") or ""),
    )


def normalize_context_scope(
    scope: object | None,
) -> dict[str, list[dict[str, str]]]:
    """Validate and canonicalize a stable context scope.

    Empty scopes are global. Non-empty scopes must contain only an ``all_of``
    list of stable identities. Display labels and legacy free-text dimensions
    are deliberately rejected so identity never depends on UI wording.
    """
    if scope is None:
        return {}
    if not isinstance(scope, Mapping):
        raise ContextScopeError("Context scope must be an object")
    if not scope:
        return {}
    if set(scope) != {"all_of"}:
        raise ContextScopeError("Context scope must contain only an all_of condition list")
    raw_conditions = scope.get("all_of")
    if not isinstance(raw_conditions, Sequence) or isinstance(
        raw_conditions, (str, bytes, bytearray)
    ):
        raise ContextScopeError("Context scope all_of must be a list")
    if not raw_conditions:
        raise ContextScopeError("Context scope all_of must not be empty")
    if len(raw_conditions) > len(SUPPORTED_CONTEXT_DIMENSIONS):
        raise ContextScopeError("Context scope contains too many conditions")

    conditions: list[ContextCondition] = []
    seen_dimensions: set[str] = set()
    for raw_condition in raw_conditions:
        if not isinstance(raw_condition, Mapping) or set(raw_condition) != {
            "dimension",
            "context_id",
        }:
            raise ContextScopeError("Each context condition must contain dimension and context_id")
        dimension = str(raw_condition.get("dimension") or "").strip()
        context_id = str(raw_condition.get("context_id") or "").strip()
        if dimension not in SUPPORTED_CONTEXT_DIMENSIONS:
            raise ContextScopeError(f"Unsupported context dimension: {dimension}")
        match = _CONTEXT_ID_RE.fullmatch(context_id)
        if match is None:
            raise ContextScopeError("Context id is malformed")
        if match.group(1) != dimension:
            raise ContextScopeError(
                "Context id does not match its dimension",
                code="context_scope_dimension_mismatch",
            )
        if dimension in seen_dimensions:
            raise ContextScopeError(f"Context scope contains more than one {dimension} condition")
        seen_dimensions.add(dimension)
        conditions.append(
            ContextCondition(
                dimension=dimension,  # type: ignore[arg-type]
                context_id=context_id,
            )
        )

    return {"all_of": [condition.to_dict() for condition in sorted(conditions)]}


def canonical_context_scope(scope: Mapping[str, Any] | None) -> str:
    """Serialize a stable context scope for storage and hashing."""
    normalized = normalize_context_scope(scope)
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def context_conditions(
    scope: Mapping[str, Any] | None,
) -> tuple[ContextCondition, ...]:
    """Return normalized conditions from a stable context scope."""
    normalized = normalize_context_scope(scope)
    return tuple(
        ContextCondition(
            dimension=item["dimension"],  # type: ignore[arg-type]
            context_id=item["context_id"],
        )
        for item in normalized.get("all_of", [])
    )


def merge_context_scopes(
    *scopes: Mapping[str, Any] | None,
) -> dict[str, list[dict[str, str]]]:
    """Merge compatible scopes, failing closed on conflicting dimensions."""
    by_dimension: dict[str, ContextCondition] = {}
    for scope in scopes:
        for condition in context_conditions(scope):
            existing = by_dimension.get(condition.dimension)
            if existing is not None and existing.context_id != condition.context_id:
                raise ContextScopeError(
                    f"Conflicting {condition.dimension} contexts cannot be merged"
                )
            by_dimension[condition.dimension] = condition
    if not by_dimension:
        return {}
    return {"all_of": [condition.to_dict() for condition in sorted(by_dimension.values())]}


__all__ = [
    "ContextCondition",
    "ContextDimension",
    "ContextOption",
    "ContextResolutionSignals",
    "ContextScopeError",
    "SUPPORTED_CONTEXT_DIMENSIONS",
    "canonical_context_scope",
    "context_conditions",
    "merge_context_scopes",
    "normalize_context_resolution_signals",
    "normalize_context_scope",
]
