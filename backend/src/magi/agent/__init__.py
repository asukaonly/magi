"""Agent package public entrypoints."""

def get_agent_runtime():
    from ..bootstrap import get_agent_runtime as _get_agent_runtime
    return _get_agent_runtime()


def get_master_agent():
    from ..bootstrap import get_master_agent as _get_master_agent
    return _get_master_agent()


def get_memory_integration():
    from ..bootstrap import get_memory_integration as _get_memory_integration
    return _get_memory_integration()


def get_unified_memory():
    from ..bootstrap import get_unified_memory as _get_unified_memory
    return _get_unified_memory()


async def initialize_chat_agent():
    from ..bootstrap import initialize_chat_agent as _initialize_chat_agent
    return await _initialize_chat_agent()


async def shutdown_chat_agent():
    from ..bootstrap import shutdown_chat_agent as _shutdown_chat_agent
    return await _shutdown_chat_agent()

__all__ = [
    "get_agent_runtime",
    "get_master_agent",
    "get_memory_integration",
    "get_unified_memory",
    "initialize_chat_agent",
    "shutdown_chat_agent",
]
