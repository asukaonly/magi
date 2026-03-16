"""Agent package public entrypoints."""


async def initialize_chat_agent():
    from ..bootstrap import initialize_chat_agent as _initialize_chat_agent
    return await _initialize_chat_agent()


async def shutdown_chat_agent():
    from ..bootstrap import shutdown_chat_agent as _shutdown_chat_agent
    return await _shutdown_chat_agent()

__all__ = [
    "initialize_chat_agent",
    "shutdown_chat_agent",
]
