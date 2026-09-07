"""Reviewable, source-bound plans for coordinated registry package upgrades."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Literal

from .contracts import PluginRegistryEntry


@dataclass(frozen=True)
class RegistryPackageChange:
    """One reviewed package, including retained dependencies and prior identity."""

    entry: PluginRegistryEntry
    action: Literal["install", "update", "reuse"]
    reason: str
    current_version: str | None
    current_package_sha256: str | None
    current_installed_package_sha256: str | None
    current_dependency_package_sha256: dict[str, str]
    dependency_package_sha256: dict[str, str]

    def to_dict(self) -> dict[str, object]:
        return {
            "entry": self.entry.model_dump(mode="json"),
            "action": self.action,
            "reason": self.reason,
            "current_version": self.current_version,
            "current_package_sha256": self.current_package_sha256,
            "current_installed_package_sha256": self.current_installed_package_sha256,
            "current_dependency_package_sha256": self.current_dependency_package_sha256,
            "dependency_package_sha256": self.dependency_package_sha256,
        }


@dataclass(frozen=True)
class RegistryInstallPlan:
    """Dependency-first changes whose fingerprint is submitted as install consent."""

    target_id: str
    update: bool
    registry_fingerprint: str
    changes: tuple[RegistryPackageChange, ...]

    @property
    def coordinated(self) -> bool:
        return any(
            item.action == "update" and item.entry.kind == "library" for item in self.changes
        )

    @property
    def fingerprint(self) -> str:
        if not self.coordinated:
            return self.registry_fingerprint
        encoded = json.dumps(self._payload(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def _payload(self) -> dict[str, object]:
        return {
            "format": "registry-install-plan-v1",
            "target_id": self.target_id,
            "update": self.update,
            "registry_fingerprint": self.registry_fingerprint,
            "coordinated": self.coordinated,
            "changes": [item.to_dict() for item in self.changes],
        }

    def to_dict(self) -> dict[str, object]:
        """Return review metadata without executing or importing package code."""
        return {**self._payload(), "fingerprint": self.fingerprint}
