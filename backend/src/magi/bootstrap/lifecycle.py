"""Shared module lifecycle primitives for backend startup/shutdown."""

from __future__ import annotations

import asyncio
import time
from collections import deque
from typing import Awaitable, Callable, Iterable, Sequence

from ..core.logger import get_logger

logger = get_logger(__name__)

AsyncHook = Callable[[], Awaitable[None]]


async def _noop() -> None:
    """Default no-op hook."""


class LifecycleInitDeferred(Exception):
    """Block a capability until its requirements can be met.

    The orchestrator retains ready modules and continues independent branches.
    Only dependents of the deferred module wait for a subsequent reconciliation.
    """


class LifecycleShutdownError(RuntimeError):
    """Report modules that could not release their runtime resources."""

    def __init__(self, failures: Sequence[tuple[str, Exception]]) -> None:
        self.failures = tuple(failures)
        names = ", ".join(name for name, _error in failures)
        super().__init__(f"Runtime modules failed to shut down: {names}")


class LifecycleModule:
    """Base lifecycle module with optional hook-based constructor."""

    def __init__(
        self,
        name: str,
        *,
        dependencies: Sequence[str] | None = None,
        init: AsyncHook | None = None,
        post_init: AsyncHook | None = None,
        shutdown: AsyncHook | None = None,
        critical: bool = True,
    ) -> None:
        self.name = name
        self.critical = critical
        self.dependencies = tuple(dependencies or ())
        self._init_hook = init
        self._post_init_hook = post_init
        self._shutdown_hook = shutdown

    async def init(self) -> None:
        """Initialize module resources."""
        if self._init_hook is None:
            await _noop()
            return
        await self._init_hook()

    async def post_init(self) -> None:
        """Finish initialization before dependent modules can start."""
        if self._post_init_hook is None:
            await _noop()
            return
        await self._post_init_hook()

    async def shutdown(self) -> None:
        """Release module resources."""
        if self._shutdown_hook is None:
            await _noop()
            return
        await self._shutdown_hook()


class ModuleLifecycleOrchestrator:
    """Run module init/post-init/shutdown phases in dependency-safe order."""

    def __init__(self, modules: Iterable[LifecycleModule]):
        self._modules = self._resolve_order(list(modules))
        self._owned: set[str] = set()
        self._states = {
            module.name: {"state": "pending", "reason": None, "blocked_by": []}
            for module in self._modules
        }

    def snapshot(self) -> dict[str, dict]:
        """Return detached module states without exposing lifecycle ownership."""
        return {
            name: {**state, "blocked_by": list(state["blocked_by"])}
            for name, state in self._states.items()
        }

    def is_ready(self, name: str) -> bool:
        return self._states[name]["state"] == "ready"

    def _closure(self, targets: set[str]) -> set[str]:
        by_name = {module.name: module for module in self._modules}
        unknown = targets - by_name.keys()
        if unknown:
            raise ValueError(f"Unknown lifecycle targets: {sorted(unknown)}")
        result = set(targets)
        pending = list(targets)
        while pending:
            for dependency in by_name[pending.pop()].dependencies:
                if dependency not in result:
                    result.add(dependency)
                    pending.append(dependency)
        return result

    async def startup(self, *, targets: set[str] | None = None) -> None:
        """Resume the dependency graph, retaining every already-ready module.

        Only a failed critical module aborts startup. Optional failure or deferred
        configuration blocks its dependents while independent capabilities start.
        The caller serializes lifecycle operations; transport can remain available.
        """
        selected = self._closure(targets) if targets is not None else set(self._states)
        for module in self._modules:
            if module.name not in selected or self.is_ready(module.name):
                continue
            state = self._states[module.name]
            if module.name in self._owned:
                # Failed cleanup must be retried by shutdown before another init.
                continue
            blocked = [name for name in module.dependencies if not self.is_ready(name)]
            if blocked:
                state.update(state="blocked", reason="dependencies_unavailable", blocked_by=blocked)
                continue
            state.update(state="starting", reason=None, blocked_by=[])
            self._owned.add(module.name)
            started = time.monotonic()
            try:
                await module.init()
                await module.post_init()
            except (Exception, asyncio.CancelledError) as exc:
                deferred = isinstance(exc, LifecycleInitDeferred)
                state.update(state="blocked" if deferred else "failed", reason=str(exc))
                try:
                    await module.shutdown()
                    self._owned.discard(module.name)
                except Exception:
                    state.update(state="failed", reason="cleanup_failed")
                    logger.exception("Partial module cleanup failed", module=module.name)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                if module.critical and not deferred:
                    await self.shutdown()
                    raise
                logger.warning("Runtime capability unavailable", module=module.name, reason=str(exc))
                continue
            state.update(state="ready", reason=None, blocked_by=[])
            logger.info("Lifecycle module ready", module=module.name,
                        elapsed_ms=round((time.monotonic() - started) * 1000, 1))

    async def shutdown(self, *, strict: bool = False, targets: set[str] | None = None) -> None:
        """Release owned modules in reverse dependency order.

        Successfully released modules are never stopped twice. A failed module
        and its dependencies retain ownership so a strict retry remains safe.
        """
        selected = set(self._states) if targets is None else set(targets)
        if targets is not None:
            self._closure(targets)
            for module in self._modules:
                if any(dependency in selected for dependency in module.dependencies):
                    selected.add(module.name)
        failures: list[tuple[str, Exception]] = []
        retained_dependencies: set[str] = set()
        for module in reversed(self._modules):
            if module.name not in selected or module.name not in self._owned or module.name in retained_dependencies:
                continue
            self._states[module.name].update(state="stopping")
            try:
                await module.shutdown()
            except Exception as exc:
                failures.append((module.name, exc))
                retained_dependencies.update(self._closure({module.name}))
                self._states[module.name].update(state="failed", reason="cleanup_failed")
                logger.warning("Lifecycle module shutdown failed", module=module.name, error=str(exc))
            else:
                self._owned.remove(module.name)
                self._states[module.name].update(state="pending", reason=None, blocked_by=[])
        if failures and strict:
            raise LifecycleShutdownError(failures)

    def _resolve_order(self, modules: list[LifecycleModule]) -> list[LifecycleModule]:
        module_by_name: dict[str, LifecycleModule] = {}
        for module in modules:
            if module.name in module_by_name:
                raise ValueError(f"Duplicate lifecycle module name: {module.name}")
            module_by_name[module.name] = module

        for module in modules:
            for dependency in module.dependencies:
                if dependency not in module_by_name:
                    raise ValueError(
                        f"Lifecycle module '{module.name}' depends on unknown module '{dependency}'"
                    )

        order_index = {module.name: index for index, module in enumerate(modules)}
        indegree = {module.name: len(module.dependencies) for module in modules}
        reverse_edges: dict[str, list[str]] = {module.name: [] for module in modules}
        for module in modules:
            for dependency in module.dependencies:
                reverse_edges[dependency].append(module.name)

        queue = deque(
            sorted(
                [module.name for module in modules if indegree[module.name] == 0],
                key=lambda name: order_index[name],
            )
        )

        ordered_names: list[str] = []
        while queue:
            current = queue.popleft()
            ordered_names.append(current)
            for dependent in sorted(reverse_edges[current], key=lambda name: order_index[name]):
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    queue.append(dependent)

        if len(ordered_names) != len(modules):
            unresolved = sorted(name for name, value in indegree.items() if value > 0)
            raise ValueError(
                f"Lifecycle dependency cycle detected among modules: {', '.join(unresolved)}"
            )

        return [module_by_name[name] for name in ordered_names]
