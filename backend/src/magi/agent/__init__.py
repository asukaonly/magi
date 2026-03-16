"""Agent package public entrypoints."""


async def initialize_agent_runtime():
    from ..bootstrap import initialize_agent_runtime as _initialize_agent_runtime

    return await _initialize_agent_runtime()


async def shutdown_agent_runtime():
    from ..bootstrap import shutdown_agent_runtime as _shutdown_agent_runtime

    return await _shutdown_agent_runtime()

__all__ = [
    "initialize_agent_runtime",
    "shutdown_agent_runtime",
]
