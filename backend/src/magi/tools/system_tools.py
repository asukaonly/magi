"""Resident system (runtime-control) tools — ADR-0005 §4.

These tools drive the agent's own execution state (plan mode, todo, ask-user,
detach, tool discovery) rather than doing capability work. Per ADR-0002 they
are *runtime-control* tools; per ADR-0005 they are RESIDENT on the main chat
LLM's tool loop instead of being routed.

Consequences:
* The router (``ContextDecider``) excludes them from its prompt — it only
  filters capability tools, so it does not waste budget reasoning about them.
* They are appended to the main LLM's tool list by ``TurnRouteResolver`` after
  the execution shape is derived — so they never turn a tool-less ``reply`` into
  a ``tool_loop``.
* The model can therefore always switch its own state mid-loop (enter plan
  mode, ask the user, detach to background) without depending on the router
  having pre-selected the control tool.

Residency is defined as: every tool in the ``control`` category, plus a small
explicit allowlist of ``system``-category tools that are control-in-spirit
(they change execution context) but are not categorised as
``control``.
"""
from __future__ import annotations

from typing import Any

# Tools that behave like runtime-control (change execution context, discover
# tools, or hand work off to a background orchestrator) and should be resident
# even though they are not categorised as ``control``.
#
# ``batch_create`` is the entry point for the deterministic batch orchestrator:
# it changes the execution shape by spawning long-running background runs, the
# same way ``detach_to_background`` does. It must always be reachable by the
# main LLM so the model can hand off a large repetitive job mid-loop instead of
# processing items one-by-one and hitting the per-turn iteration cap — without
# depending on the router having pre-selected it.
_EXPLICIT_RESIDENT_TOOLS: tuple[str, ...] = (
    "detach_to_background",
    "batch_create",
)


def resolve_resident_system_tools(tool_registry: Any) -> list[str]:
    """Return resident system tool names that exist in ``tool_registry``.

    Tolerates registries whose ``list_tools`` does not accept a ``category``
    keyword (e.g. minimal test stubs) by treating the control set as empty.
    """
    resident: list[str] = []

    try:
        control_tools = list(tool_registry.list_tools(category="control"))
    except TypeError:
        control_tools = []
    for name in control_tools:
        if name not in resident:
            resident.append(name)

    try:
        registered = set(tool_registry.list_tools())
    except Exception:
        registered = set()
    for name in _EXPLICIT_RESIDENT_TOOLS:
        if name in registered and name not in resident:
            resident.append(name)

    return resident


__all__ = ["resolve_resident_system_tools"]
