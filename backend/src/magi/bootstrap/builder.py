"""Bootstrap builder for assembling lifecycle modules from owning layers."""

from __future__ import annotations

from .context import RuntimeBootstrapContext
from .lifecycle import LifecycleModule
from .runtime_worker_builder import build_runtime_worker_modules


def build_runtime_modules(
    context: RuntimeBootstrapContext,
) -> list[LifecycleModule]:
    """Build ordered runtime lifecycle modules for the IPC worker."""
    return build_runtime_worker_modules(context)
