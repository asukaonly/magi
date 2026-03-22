"""Background runtime worker entrypoint."""

from __future__ import annotations

import asyncio
import signal

from .bootstrap import initialize_agent_runtime, shutdown_agent_runtime
from .core.container import wire_container
from .core.logger import get_logger
from .process_roles import ProcessRole

logger = get_logger(__name__)


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    """Install signal handlers that stop the runtime worker."""
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop_event.set)
        except NotImplementedError:
            logger.warning("Signal handler registration is unavailable", signal=sig.name)


async def run_runtime_worker() -> None:
    """Run the background runtime worker until interrupted."""
    wire_container()
    await initialize_agent_runtime(role=ProcessRole.RUNTIME_WORKER)

    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)

    try:
        await stop_event.wait()
    finally:
        await shutdown_agent_runtime()


def main() -> None:
    """Run the runtime worker entrypoint."""
    asyncio.run(run_runtime_worker())


__all__ = ["main", "run_runtime_worker"]
