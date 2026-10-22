"""Private runtime metrics composition from data-owner operations."""
import asyncio
import time
from typing import Any

from ..api.runtime_dependencies import get_api_runtime_dependencies
from ..memory.provider import get_unified_memory
from ..scheduler.provider import require_scheduler_service


async def runtime_metrics(params: dict[str, Any] | None) -> dict[str, Any]:
    if params:
        raise ValueError("Runtime metrics does not accept parameters")

    async def model():
        store = get_api_runtime_dependencies().llm_usage_store
        if store is None:
            raise RuntimeError("Usage metrics owner is unavailable")
        return await store.get_runtime_metrics(since=time.time() - 3600)

    async def memory():
        return await get_unified_memory().get_runtime_metrics()

    async def scheduler():
        return await require_scheduler_service().repository.get_runtime_metrics()

    results = await asyncio.gather(model(), memory(), scheduler(), return_exceptions=True)
    return {name: None if isinstance(result, Exception) else result
            for name, result in zip(("model_execution", "memory", "scheduler"), results, strict=True)}
