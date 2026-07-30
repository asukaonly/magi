"""Bounded admission for plugin installation workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
import threading
import uuid

from pydantic import TypeAdapter, ValidationError

from .contracts import PluginIdentifier

MAX_ACTIVE_PLUGIN_INSTALLS = 8
_PLUGIN_IDENTIFIER_ADAPTER = TypeAdapter(PluginIdentifier)


class PluginInstallCapacityError(RuntimeError):
    """Raised when too many plugin installs are already active."""


class PluginInstallConflictError(RuntimeError):
    """Raised when the same plugin already has an active install."""


@dataclass(slots=True)
class PluginInstallAdmissionLease:
    """One active workflow reservation released exactly once."""

    plugin_id: str
    lease_id: str
    _coordinator: "PluginInstallAdmissionCoordinator" = field(repr=False)
    _released: bool = field(default=False, repr=False)
    _release_lock: threading.Lock = field(
        default_factory=threading.Lock,
        repr=False,
    )

    def release(self) -> None:
        with self._release_lock:
            if self._released:
                return
            self._released = True
        self._coordinator.release(self)


class PluginInstallAdmissionCoordinator:
    """Enforce one global queue bound and per-package single-flight."""

    def __init__(self, *, max_active: int = MAX_ACTIVE_PLUGIN_INSTALLS) -> None:
        self._max_active = max_active
        self._active: dict[str, PluginInstallAdmissionLease] = {}
        self._plugin_ids: set[str] = set()
        self._lock = threading.Lock()

    @staticmethod
    def validate_plugin_id(plugin_id: str) -> str:
        """Validate one target with the public plugin identifier contract."""

        try:
            return _PLUGIN_IDENTIFIER_ADAPTER.validate_python(plugin_id)
        except ValidationError as exc:
            raise ValueError("Invalid plugin id for installation admission") from exc

    def acquire(self, plugin_id: str) -> PluginInstallAdmissionLease:
        validated_plugin_id = self.validate_plugin_id(plugin_id)
        with self._lock:
            if validated_plugin_id in self._plugin_ids:
                raise PluginInstallConflictError(
                    f"A plugin installation is already active: {validated_plugin_id}"
                )
            if len(self._active) >= self._max_active:
                raise PluginInstallCapacityError("Too many plugin installations are already active")
            lease = PluginInstallAdmissionLease(
                plugin_id=validated_plugin_id,
                lease_id=uuid.uuid4().hex,
                _coordinator=self,
            )
            self._active[lease.lease_id] = lease
            self._plugin_ids.add(validated_plugin_id)
            return lease

    def release(self, lease: PluginInstallAdmissionLease) -> None:
        with self._lock:
            active = self._active.get(lease.lease_id)
            if active is not lease:
                return
            self._active.pop(lease.lease_id, None)
            self._plugin_ids.discard(lease.plugin_id)

    @property
    def active_count(self) -> int:
        with self._lock:
            return len(self._active)


plugin_install_admission = PluginInstallAdmissionCoordinator()


__all__ = [
    "MAX_ACTIVE_PLUGIN_INSTALLS",
    "PluginInstallAdmissionCoordinator",
    "PluginInstallAdmissionLease",
    "PluginInstallCapacityError",
    "PluginInstallConflictError",
    "plugin_install_admission",
]
