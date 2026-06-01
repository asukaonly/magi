"""Tool permission gateway and supporting primitives.

Public API:

* :class:`PermissionGateway`   — the enforcement entry point.
* :class:`RiskClassifier`      — risk assessment for ``(tool, args)``.
* :class:`PermissionRuleStore` — session + persistent rule cache.
* :mod:`.kill_list`            — hardcoded safety fuse.
* :class:`ControlSettings`     — re-exported from :mod:`..settings`.

The gateway itself is async and cancellable so it can be wired into
``FunctionCallingStepExecutor`` without blocking the tool loop.
"""

from __future__ import annotations

from ..settings import (
    ControlSettings,
    PermissionMode,
    SessionControlOverride,
    resolve_effective_settings,
)
from .classifier import RiskClassifier, RiskSignal
from .contracts import (
    PermissionDecision,
    PermissionOutcome,
    PermissionRequest,
    PermissionRule,
    PermissionScope,
    RiskLevel,
    ToolOrigin,
)
from .gateway import PermissionGateway
from .kill_list import KillListEntry, KillListMatch, check_kill_list
from .rules import PermissionRuleStore

__all__ = [
    "ControlSettings",
    "KillListEntry",
    "KillListMatch",
    "PermissionDecision",
    "PermissionGateway",
    "PermissionMode",
    "PermissionOutcome",
    "PermissionRequest",
    "PermissionRule",
    "PermissionRuleStore",
    "PermissionScope",
    "RiskClassifier",
    "RiskLevel",
    "RiskSignal",
    "SessionControlOverride",
    "ToolOrigin",
    "check_kill_list",
    "resolve_effective_settings",
]
