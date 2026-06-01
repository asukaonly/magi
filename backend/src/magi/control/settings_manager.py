"""Runtime manager wrapping :class:`ControlSettings` + session overrides.

Kept separate from :mod:`.settings` (which only owns the data model)
so that the pure types stay import-safe and allocation-free.
"""

from __future__ import annotations

import threading
from typing import Any

from .settings import ControlSettings, PermissionMode, SessionControlOverride

__all__ = ["ControlSettingsManager"]


class ControlSettingsManager:
    """Thread-safe holder for the global :class:`ControlSettings` and
    per-session overrides.

    The manager exposes two callables — :meth:`settings_provider` and
    :meth:`session_override_provider` — that plug directly into
    :class:`~magi.agent.control.permission.gateway.PermissionGateway`.
    """

    def __init__(self, base: ControlSettings | None = None) -> None:
        self._lock = threading.Lock()
        self._base: ControlSettings = base or ControlSettings()
        self._overrides: dict[str, SessionControlOverride] = {}

    # ------------------------------------------------------------------
    # Base settings
    # ------------------------------------------------------------------

    def get(self) -> ControlSettings:
        with self._lock:
            return self._base

    def update(
        self,
        *,
        permission_mode: PermissionMode | None = None,
        plan_approval_required: bool | None = None,
    ) -> ControlSettings:
        with self._lock:
            current = self._base
            self._base = ControlSettings(
                permission_mode=permission_mode
                if permission_mode is not None
                else current.permission_mode,
                plan_approval_required=plan_approval_required
                if plan_approval_required is not None
                else current.plan_approval_required,
            )
            return self._base

    # ------------------------------------------------------------------
    # Session overrides
    # ------------------------------------------------------------------

    def set_session_override(
        self, session_id: str, override: SessionControlOverride | None
    ) -> None:
        with self._lock:
            if override is None:
                self._overrides.pop(session_id, None)
            else:
                self._overrides[session_id] = override

    def get_session_override(
        self, session_id: str | None
    ) -> SessionControlOverride | None:
        if not session_id:
            return None
        with self._lock:
            return self._overrides.get(session_id)

    # ------------------------------------------------------------------
    # Gateway hooks
    # ------------------------------------------------------------------

    def settings_provider(self) -> ControlSettings:
        return self.get()

    def session_override_provider(
        self, session_id: str | None
    ) -> SessionControlOverride | None:
        return self.get_session_override(session_id)

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "base": self._base.to_dict(),
                "overrides": {
                    sid: override.to_dict() for sid, override in self._overrides.items()
                },
            }
