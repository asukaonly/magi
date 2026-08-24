"""Resident system (runtime-control) tools — ADR-0005 §4.

These tools drive the agent's own execution state (plan mode, todo, ask-user,
detach, tool discovery) rather than doing capability work. Per ADR-0002 they
are *runtime-control* tools; per ADR-0005 they are RESIDENT on the main chat
LLM's tool loop instead of being routed.

The unified loop exposes these tools before the first model call. A resident
schema is availability, not authorization; invocation still crosses capability,
permission, effect, and budget guards.

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
    "agent",
    "find-relevant-tools",
    "memory_query",
    "trace_query",
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
