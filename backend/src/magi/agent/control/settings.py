"""Global + session-scoped control-plane settings.

The effective mode used by the :class:`PermissionGateway` is resolved
per-call via :func:`resolve_effective_settings` which applies the
session override on top of the global defaults.

Persistence of :class:`ControlSettings` itself is delegated to the
caller (L0 preference store / user profile) — this module only owns
the data model and the resolution rule. Session overrides live in
memory for the lifetime of the session.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
from typing import Any

__all__ = [
    "ControlSettings",
    "PermissionMode",
    "SessionControlOverride",
    "resolve_effective_settings",
]


class PermissionMode(str, Enum):
    """Three-tier permission gating level.

    * ``ALL``        — every ``dangerous=True`` tool invocation is asked.
    * ``HIGH_ONLY``  — default; ``high`` and ``destructive`` ask, lower
      levels pass silently.
    * ``OFF``        — YOLO mode. Everything passes except entries on the
      hardcoded kill-list (see :mod:`.permission.kill_list`).

    The ``destructive`` level is *only* asked under ``ALL`` and
    ``HIGH_ONLY``; under ``OFF`` it collapses to an observational tag
    (the gateway still records it in the trace). The kill-list applies
    regardless of this mode.
    """

    ALL = "all"
    HIGH_ONLY = "high_only"
    OFF = "off"


@dataclass(slots=True)
class ControlSettings:
    """Global control-plane configuration persisted per user."""

    permission_mode: PermissionMode = PermissionMode.HIGH_ONLY
    #: Whether :func:`exit_plan_mode` requires explicit user approval.
    #: Default ``False`` per product decision: the plan card still
    #: surfaces the plan, but the agent can continue without waiting.
    plan_approval_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "permission_mode": self.permission_mode.value,
            "plan_approval_required": self.plan_approval_required,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ControlSettings":
        if not payload:
            return cls()
        mode_raw = payload.get("permission_mode") or PermissionMode.HIGH_ONLY.value
        try:
            mode = PermissionMode(mode_raw)
        except ValueError:
            mode = PermissionMode.HIGH_ONLY
        return cls(
            permission_mode=mode,
            plan_approval_required=bool(payload.get("plan_approval_required", False)),
        )


@dataclass(slots=True)
class SessionControlOverride:
    """Per-session override of :class:`ControlSettings`.

    Only fields that the user explicitly set during this session are
    non-``None``; everything else falls back to the global settings.
    """

    permission_mode: PermissionMode | None = None
    plan_approval_required: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "permission_mode": (
                self.permission_mode.value if self.permission_mode else None
            ),
            "plan_approval_required": self.plan_approval_required,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "SessionControlOverride":
        if not payload:
            return cls()
        mode_raw = payload.get("permission_mode")
        mode: PermissionMode | None = None
        if mode_raw is not None:
            try:
                mode = PermissionMode(mode_raw)
            except ValueError:
                mode = None
        approval_raw = payload.get("plan_approval_required")
        approval: bool | None
        approval = bool(approval_raw) if approval_raw is not None else None
        return cls(permission_mode=mode, plan_approval_required=approval)


def resolve_effective_settings(
    *,
    base: ControlSettings,
    override: SessionControlOverride | None,
) -> ControlSettings:
    """Apply ``override`` on top of ``base`` and return a new instance."""
    if override is None:
        return replace(base)
    return replace(
        base,
        permission_mode=(
            override.permission_mode
            if override.permission_mode is not None
            else base.permission_mode
        ),
        plan_approval_required=(
            override.plan_approval_required
            if override.plan_approval_required is not None
            else base.plan_approval_required
        ),
    )
