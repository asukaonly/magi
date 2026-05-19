"""Track tool-access restrictions imposed by currently-active skills.

When a skill declares ``allowed-tools`` in its frontmatter, the Claude Code
Skills spec requires that the *only* tools usable while that skill is in
effect are the declared ones. magi enforces this by:

1. Pushing the skill's allowed-tools set onto a per-task contextvar stack
   at the start of skill execution (both direct and fork modes).
2. Having ``tool_invocation_service.invoke`` consult the stack before
   every tool call and short-circuit with a structured failure when the
   call is outside the intersection of all active restrictions.
3. Letting the contextvar fall off the stack naturally when the asyncio
   task running the turn ends — there is no explicit pop required, which
   matches the desired "restriction is active for the rest of this turn"
   semantics.

Multiple stacked restrictions intersect (the model must satisfy *every*
active skill's allow-list), which mirrors how nested skills should
compose: the inner skill cannot escape the outer skill's whitelist.

The stack is intentionally a tuple of frozensets so contextvar values are
immutable — copying-on-push avoids surprises with cross-task state.
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from typing import FrozenSet, Iterable, Iterator, Optional, Tuple

logger = logging.getLogger(__name__)


_active_allowed_tools: contextvars.ContextVar[Tuple[FrozenSet[str], ...]] = (
    contextvars.ContextVar("magi_skill_allowed_tools", default=())
)


def current_restrictions() -> Tuple[FrozenSet[str], ...]:
    """Return the stack of allow-lists imposed by currently-active skills."""
    return _active_allowed_tools.get()


def is_tool_allowed(tool_name: str) -> bool:
    """Decide whether ``tool_name`` is callable under the current restriction stack.

    With no active skill the result is always ``True``. Otherwise the tool
    must appear in every active allow-list (intersection semantics).
    """
    stack = _active_allowed_tools.get()
    if not stack:
        return True
    return all(tool_name in allowed for allowed in stack)


def disallowed_reason(tool_name: str) -> Optional[str]:
    """Return a human-readable explanation when a tool is disallowed, else ``None``."""
    stack = _active_allowed_tools.get()
    if not stack:
        return None
    for index, allowed in enumerate(stack):
        if tool_name not in allowed:
            allowed_sorted = sorted(allowed)
            preview = ", ".join(allowed_sorted[:5])
            if len(allowed_sorted) > 5:
                preview += f", … (+{len(allowed_sorted) - 5} more)"
            return (
                f"Tool '{tool_name}' is not in the active skill's allowed-tools "
                f"whitelist (depth={index + 1}, allowed=[{preview}])."
            )
    return None


def push_restriction(allowed_tools: Optional[Iterable[str]]) -> contextvars.Token:
    """Push an allow-list onto the contextvar stack.

    ``allowed_tools=None`` is a no-op that still returns a token so the
    caller's ``with skill_restriction(...)`` paths stay symmetric.

    Returns the contextvar token; pass it to :func:`pop_restriction` to
    undo the push (rare — usually we let the task end clean it up).
    """
    if allowed_tools is None:
        return _active_allowed_tools.set(_active_allowed_tools.get())
    frozen = frozenset(allowed_tools)
    current = _active_allowed_tools.get()
    new_stack = current + (frozen,)
    logger.debug(
        "skill restriction pushed depth=%d allowed=%s",
        len(new_stack),
        sorted(frozen),
    )
    return _active_allowed_tools.set(new_stack)


def pop_restriction(token: contextvars.Token) -> None:
    """Undo a previous :func:`push_restriction`."""
    _active_allowed_tools.reset(token)


@contextmanager
def skill_restriction(allowed_tools: Optional[Iterable[str]]) -> Iterator[None]:
    """Scoped helper for tests and synchronous call sites."""
    token = push_restriction(allowed_tools)
    try:
        yield
    finally:
        pop_restriction(token)


__all__ = [
    "current_restrictions",
    "is_tool_allowed",
    "disallowed_reason",
    "push_restriction",
    "pop_restriction",
    "skill_restriction",
]
