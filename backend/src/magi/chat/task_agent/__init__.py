"""Chat task-agent package — the chat "driver" of the agent runtime (ADR-0003/0004).

Holds ``ChatTaskAgent`` + its factory and the chat-store-coupled driver services
(history / planning / postprocess / reply-context / session-control / transcript),
relocated out of the agent layer across P2 Tasks 2-3. It lives in the chat layer
(L14): ``magi.chat`` imports are intra-layer, and it consumes the generic agent
runtime (``magi.agent.*``, ``magi.context.*``, ...) downward (legal). The agent
core no longer imports chat for the task-agent; ``ChatTaskAgent`` is constructed
via an injected factory from the composition root and dispatched by type.
"""
