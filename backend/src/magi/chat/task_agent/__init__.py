"""Chat-driver service cluster (relocated from the agent layer in P2 Task 2).

These modules are chat-store-coupled chat-driver services. They live in the
chat layer (L14) so their ``magi.chat`` imports are intra-layer; importing
lower layers (``magi.agent``, ``magi.context``, ...) is downward and legal.
"""
