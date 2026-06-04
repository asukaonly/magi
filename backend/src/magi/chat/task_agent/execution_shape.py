"""Per-turn execution shape derivation (ADR-0005).

The execution shape (reply / tool_loop / plan_fanout) is a pure function of
semantic signals — NOT a field the routing LLM emits. Making it derived is what
prevents graph_shape from ever contradicting the selected tool list: the class
of bug where the router correctly picks a tool but a separately-emitted "reply"
shape causes the tool to be dropped before the main LLM ever sees it.

Shape values mirror ``RouteDecision.graph_shape`` / ``GRAPH_TEMPLATES`` keys so
the derived value drives the same GraphBuilder + execution_mode mapping.
"""
from __future__ import annotations

SHAPE_REPLY = "reply"
SHAPE_TOOL_LOOP = "tool_loop"
SHAPE_PLAN_FANOUT = "plan_fanout"


def derive_execution_shape(
    *,
    has_image_attachments: bool,
    needs_orchestration: bool,
    has_tools: bool,
) -> str:
    """Return the execution shape for this turn.

    Precedence:
      1. image attachments -> reply  (a tool loop can't run over an image turn)
      2. orchestration needed -> plan_fanout  (multi-agent decomposition)
      3. tools selected -> tool_loop  (single-agent tool iteration)
      4. otherwise -> reply  (single-shot)

    ``reply`` is therefore the *absence* of tools/orchestration, never an
    independent choice — so a turn that selected tools can never collapse into a
    tool-less reply.
    """
    if has_image_attachments:
        return SHAPE_REPLY
    if needs_orchestration:
        return SHAPE_PLAN_FANOUT
    if has_tools:
        return SHAPE_TOOL_LOOP
    return SHAPE_REPLY


__all__ = [
    "derive_execution_shape",
    "SHAPE_REPLY",
    "SHAPE_TOOL_LOOP",
    "SHAPE_PLAN_FANOUT",
]
