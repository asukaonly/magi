"""Coordinate provisional registry libraries shared by install workflows."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
import logging
import threading
import uuid

logger = logging.getLogger(__name__)

DirectoryIdentity = tuple[int, int]
PathIdentity = tuple[int, int, int, int]


class ProvisionalDependencyConflictError(RuntimeError):
    """Raised when concurrent workflows request incompatible library packages."""


@dataclass(frozen=True, slots=True)
class ProvisionalLibraryRequirement:
    """Exact registry identity claimed by one install workflow."""

    plugin_id: str
    registry_source: str
    registry_repo_url: str
    package_sha256: str

    @property
    def provenance(self) -> tuple[str, str, str]:
        return (
            self.registry_source,
            self.registry_repo_url,
            self.package_sha256,
        )


@dataclass(frozen=True, slots=True)
class ProvisionalLibraryReceipt:
    """Identity captured when a workflow publishes a previously absent library."""

    requirement: ProvisionalLibraryRequirement
    dependency_package_sha256: tuple[tuple[str, str], ...]
    plugin_dir: str
    manifest_path: str
    destination_identity: DirectoryIdentity
    manifest_identity: PathIdentity


ProvisionalLibraryFinalizer = Callable[[], bool]
ProvisionalLibraryDetach = Callable[
    [ProvisionalLibraryReceipt],
    ProvisionalLibraryFinalizer | None,
]


@dataclass(slots=True)
class _ClaimState:
    requirement: ProvisionalLibraryRequirement
    workflow_ids: set[str] = field(default_factory=set)
    receipt: ProvisionalLibraryReceipt | None = None
    detach: ProvisionalLibraryDetach | None = field(default=None, repr=False)


@dataclass(slots=True)
class ProvisionalDependencyLease:
    """One workflow's shared claims over its library dependency closure."""

    workflow_id: str
    requirements: tuple[ProvisionalLibraryRequirement, ...]
    _coordinator: "ProvisionalDependencyCoordinator" = field(repr=False)
    _released: bool = field(default=False, repr=False)

    def register_created(
        self,
        receipt: ProvisionalLibraryReceipt,
        detach: ProvisionalLibraryDetach,
    ) -> None:
        """Record a publication and bind detach to its creating manager."""

        self._coordinator.register_created(self, receipt, detach)

    def release(self) -> list[str]:
        """Release all claims and clean newly orphaned libraries in reverse order."""

        return self._coordinator.release(self)


class ProvisionalDependencyCoordinator:
    """Reference-count in-flight use of exact registry library packages.

    The coordinator lock is intentionally held while the final claimant asks
    the plugin manager to remove an orphan. New claimants therefore cannot race
    between the zero-user decision and lifecycle-locked identity validation.
    Callers must never acquire this coordinator while holding the plugin
    manager lifecycle lock.
    """

    def __init__(self) -> None:
        self._claims: dict[str, _ClaimState] = {}
        self._lock = threading.RLock()

    def acquire(
        self,
        requirements: Iterable[ProvisionalLibraryRequirement],
    ) -> ProvisionalDependencyLease:
        """Atomically acquire shared claims for one dependency closure."""

        ordered = tuple(requirements)
        by_id: dict[str, ProvisionalLibraryRequirement] = {}
        for requirement in ordered:
            previous = by_id.get(requirement.plugin_id)
            if previous is not None and previous != requirement:
                raise ProvisionalDependencyConflictError(
                    f"Conflicting provisional dependency identity: {requirement.plugin_id}"
                )
            by_id[requirement.plugin_id] = requirement
        if len(by_id) != len(ordered):
            raise ValueError("Provisional dependency closure contains duplicate packages")

        workflow_id = uuid.uuid4().hex
        with self._lock:
            for requirement in ordered:
                state = self._claims.get(requirement.plugin_id)
                if state is not None and state.requirement != requirement:
                    raise ProvisionalDependencyConflictError(
                        "Concurrent install requested a different identity for "
                        f"provisional dependency: {requirement.plugin_id}"
                    )

            for requirement in ordered:
                state = self._claims.setdefault(
                    requirement.plugin_id,
                    _ClaimState(requirement=requirement),
                )
                state.workflow_ids.add(workflow_id)

        return ProvisionalDependencyLease(
            workflow_id=workflow_id,
            requirements=ordered,
            _coordinator=self,
        )

    def register_created(
        self,
        lease: ProvisionalDependencyLease,
        receipt: ProvisionalLibraryReceipt,
        detach: ProvisionalLibraryDetach,
    ) -> None:
        """Attach a receipt and its creating manager to an active shared claim."""

        requirement = receipt.requirement
        with self._lock:
            if lease._released:
                raise RuntimeError("Cannot register a library after its workflow was released")
            if requirement not in lease.requirements:
                raise ValueError(
                    f"Library receipt is outside this install workflow: {requirement.plugin_id}"
                )
            state = self._claims.get(requirement.plugin_id)
            if state is None or lease.workflow_id not in state.workflow_ids:
                raise RuntimeError("Provisional dependency claim is no longer active")
            if state.requirement != requirement:
                raise ProvisionalDependencyConflictError(
                    f"Library receipt changed provenance: {requirement.plugin_id}"
                )
            if state.receipt is not None and state.receipt != receipt:
                raise ProvisionalDependencyConflictError(
                    f"Library was published with conflicting identity: {requirement.plugin_id}"
                )
            if state.receipt is None:
                state.receipt = receipt
                state.detach = detach

    def release(
        self,
        lease: ProvisionalDependencyLease,
    ) -> list[str]:
        """Release a workflow and remove exact zero-consumer libraries.

        Requirements are recorded dependency-first, so reverse iteration removes
        library consumers before the libraries they depend on.
        """

        detached: list[tuple[str, ProvisionalLibraryFinalizer]] = []
        with self._lock:
            if lease._released:
                return []
            lease._released = True

            for requirement in reversed(lease.requirements):
                state = self._claims.get(requirement.plugin_id)
                if state is None:
                    continue
                state.workflow_ids.discard(lease.workflow_id)
                if state.workflow_ids:
                    continue

                receipt = state.receipt
                detach = state.detach
                try:
                    if receipt is not None and detach is not None:
                        finalizer = detach(receipt)
                        if finalizer is not None:
                            detached.append((requirement.plugin_id, finalizer))
                except Exception:
                    logger.warning(
                        "plugin.provisional_dependency_detach_failed plugin_id=%s",
                        requirement.plugin_id,
                        exc_info=True,
                    )
                finally:
                    self._claims.pop(requirement.plugin_id, None)

        removed: list[str] = []
        for plugin_id, finalizer in detached:
            try:
                if finalizer():
                    removed.append(plugin_id)
            except Exception:
                logger.warning(
                    "plugin.provisional_dependency_finalize_failed plugin_id=%s",
                    plugin_id,
                    exc_info=True,
                )
        return removed

    @property
    def active_claim_count(self) -> int:
        with self._lock:
            return sum(len(state.workflow_ids) for state in self._claims.values())


provisional_dependency_coordinator = ProvisionalDependencyCoordinator()


__all__ = [
    "DirectoryIdentity",
    "PathIdentity",
    "ProvisionalDependencyConflictError",
    "ProvisionalDependencyCoordinator",
    "ProvisionalDependencyLease",
    "ProvisionalLibraryDetach",
    "ProvisionalLibraryFinalizer",
    "ProvisionalLibraryReceipt",
    "ProvisionalLibraryRequirement",
    "provisional_dependency_coordinator",
]
