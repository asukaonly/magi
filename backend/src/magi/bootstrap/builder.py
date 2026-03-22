"""Bootstrap builder for assembling lifecycle modules from owning layers."""

from __future__ import annotations

from .context import RuntimeBootstrapContext
from .lifecycle import LifecycleModule
from .api_builder import build_api_runtime_modules
from .runtime_worker_builder import build_runtime_worker_modules
from ..process_roles import ProcessRole


def build_runtime_modules(
    context: RuntimeBootstrapContext,
    *,
    role: ProcessRole = ProcessRole.COMBINED,
) -> list[LifecycleModule]:
    """Build ordered runtime lifecycle modules from layer-owned contributions.

    The combined role preserves the current single-process topology while the
    dedicated API and runtime-worker roles expose the split bootstrap graphs.
    """
    if role is ProcessRole.API:
        return build_api_runtime_modules(context)
    if role is ProcessRole.RUNTIME_WORKER:
        return build_runtime_worker_modules(context)
    if role is ProcessRole.COMBINED:
        return build_runtime_worker_modules(context)

    raise ValueError(f"Unsupported process role: {role}")
