"""Per-turn execution shape derivation (ADR-0005).

The execution shape (reply / tool_loop / plan_fanout) is a pure function of
semantic signals — NOT a field the routing LLM emits. Making it derived is what
prevents graph_shape from ever contradicting the selected tool list.

P3 (ADR-0005): orchestration is a THREE-state signal, not a boolean:
  - "required": pre-planned multi-agent fanout (plan_fanout).
  - "maybe":    a single-agent tool loop that ALSO gets an injected `agent`
                tool, so the model can self-escalate to workers mid-loop.
  - "none":     no orchestration; shape falls back to tools/reply.

Shape values mirror ``RouteDecision.graph_shape`` / ``GRAPH_TEMPLATES`` keys so
the derived value drives the same GraphBuilder + execution_mode mapping.
"""
from __future__ import annotations

SHAPE_REPLY = "reply"
SHAPE_TOOL_LOOP = "tool_loop"
SHAPE_PLAN_FANOUT = "plan_fanout"

# orchestration intent (ADR-0005 P3) — emitted by the router LLM.
ORCH_NONE = "none"
ORCH_MAYBE = "maybe"
ORCH_REQUIRED = "required"


def derive_execution_shape(
    *,
    has_image_attachments: bool,
    orchestration: str,
    has_tools: bool,
) -> str:
    """Return the execution shape for this turn.

    Precedence:
      1. image attachments -> reply  (a tool loop can't run over an image turn)
      2. orchestration == "required" -> plan_fanout  (pre-planned fanout)
      3. orchestration == "maybe" -> tool_loop  (loop + injected `agent` tool so
         the model can self-escalate to workers mid-loop; ADR-0005 P3)
      4. tools selected -> tool_loop  (single-agent tool iteration)
      5. otherwise -> reply  (single-shot)

    ``reply`` is the *absence* of tools/orchestration, never an independent
    choice, so a turn that selected tools can never collapse into a tool-less
    reply.
    """
    if has_image_attachments:
        return SHAPE_REPLY
    if orchestration == ORCH_REQUIRED:
        return SHAPE_PLAN_FANOUT
    if orchestration == ORCH_MAYBE:
        return SHAPE_TOOL_LOOP
    if has_tools:
        return SHAPE_TOOL_LOOP
    return SHAPE_REPLY


__all__ = [
    "derive_execution_shape",
    "SHAPE_REPLY",
    "SHAPE_TOOL_LOOP",
    "SHAPE_PLAN_FANOUT",
    "ORCH_NONE",
    "ORCH_MAYBE",
    "ORCH_REQUIRED",
]
