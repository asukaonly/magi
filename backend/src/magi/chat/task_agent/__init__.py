"""Chat task-agent package — the chat "driver" of the agent runtime (ADR-0003/0004).

Holds the complete chat driver: ``ChatTaskAgent`` + its factory, the
chat-store-coupled services (history / planning / postprocess / reply-context /
session-control / transcript), the run/session state machine (coordinator /
session_run_* / run_store* / session_turn_queue), and the conversational
services (prompt / fact-classifier / interruption / rhythm / streaming),
relocated out of the agent layer across P2 Tasks 2-6. It lives in the chat layer
(L14): ``magi.chat`` imports are intra-layer, and it consumes the generic agent
runtime (``magi.agent.*``, ``magi.context.*``, ...) downward (legal). The agent
core no longer imports chat for the task-agent; ``ChatTaskAgent`` is constructed
via an injected factory from the composition root and dispatched by type.
"""
