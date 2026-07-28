"""Track tool pre-approvals contributed by currently-active skills.

When a skill declares ``allowed-tools`` in its frontmatter, the Claude
Code Skills spec says each entry **pre-approves** matching tool calls —
those calls skip the normal permission prompt while the skill is active.
The spec is explicit that this is *not* a hard restriction: tools not on
the list remain callable; they just go through the usual permission
flow (kill list, cached rules, user approval, …).

We implement that by:

1. Pushing the skill's parsed rules onto a per-task contextvar stack at
   the start of skill execution (both direct and fork modes).
2. Letting :mod:`magi.agent.execution.function_calling.permission`
   consult :func:`is_call_preapproved` before raising a prompt — when a
   call matches any active rule, the permission gateway is short-
   circuited with an "allowed" decision.
3. Letting the contextvar fall off the stack naturally when the asyncio
   task running the turn ends; there is no explicit pop required, which
   matches the desired "pre-approval is active for the rest of this
   turn" semantics.

Stacked entries union (not intersect): if any active skill pre-approves
a call, it is pre-approved — this matches the spec where the field is a
list of *granted* permissions rather than a whitelist of allowed tools.

The stack is a tuple of tuples-of-rules so contextvar values are
immutable — copy-on-push avoids cross-task state surprises.
"""

from __future__ import annotations

import contextvars
import logging
from contextlib import contextmanager
from typing import Iterable, Iterator, Mapping, Optional, Tuple

from .allowed_tools_rules import ToolRule, any_rule_matches, parse_allowed_tools

logger = logging.getLogger(__name__)


_active_preapproval: contextvars.ContextVar[Tuple[Tuple[ToolRule, ...], ...]] = (
    contextvars.ContextVar("magi_skill_preapproval", default=())
)


def current_preapproval_frames() -> Tuple[Tuple[ToolRule, ...], ...]:
    """Return the per-skill rule frames currently active in this task."""
    return _active_preapproval.get()


def is_call_preapproved(tool_name: str, arguments: Mapping[str, object] | None) -> bool:
    """``True`` if any active skill pre-approves this ``(tool, arguments)`` pair.

    A bare-name rule (``Read``) pre-approves any call to that tool; a
    patterned rule (``Bash(git add *)``) matches the specifier returned
    by :func:`magi.skills.allowed_tools_rules._specifier_for`.
    """
    frames = _active_preapproval.get()
    if not frames:
        return False
    args = dict(arguments or {})
    for frame in frames:
        if any_rule_matches(frame, tool_name, args):
            return True
    return False


def matched_rule(
    tool_name: str, arguments: Mapping[str, object] | None
) -> Optional[ToolRule]:
    """Return the first active rule that pre-approves the call, if any.

    Useful for telemetry and for permission-decision diagnostics.
    """
    frames = _active_preapproval.get()
    if not frames:
        return None
    args = dict(arguments or {})
    for frame in frames:
        for rule in frame:
            if rule.tool == tool_name and (
                rule.pattern is None
                or any_rule_matches([rule], tool_name, args)
            ):
                return rule
    return None


def push_skill_rules(
    rules: Optional[Iterable[ToolRule | str]],
) -> contextvars.Token:
    """Push a frame of pre-approval rules for an in-flight skill.

    Accepts already-parsed :class:`ToolRule` objects, raw strings (which
    will be reparsed), or ``None`` (no-op that still returns a token for
    symmetric ``try``/``finally`` shapes).
    """
    if rules is None:
        return _active_preapproval.set(_active_preapproval.get())
    frame: list[ToolRule] = []
    for entry in rules:
        if isinstance(entry, ToolRule):
            frame.append(entry)
        elif isinstance(entry, str):
            frame.extend(parse_allowed_tools(entry))
    if not frame:
        return _active_preapproval.set(_active_preapproval.get())
    new_frames = _active_preapproval.get() + (tuple(frame),)
    logger.debug(
        "skill pre-approval frame pushed depth=%d rules=%s",
        len(new_frames),
        [r.display for r in frame],
    )
    return _active_preapproval.set(new_frames)


def pop_skill_rules(token: contextvars.Token) -> None:
    """Undo a previous :func:`push_skill_rules`."""
    _active_preapproval.reset(token)


@contextmanager
def skill_preapproval(
    rules: Optional[Iterable[ToolRule | str]],
) -> Iterator[None]:
    """Scoped helper for tests and synchronous call sites."""
    token = push_skill_rules(rules)
    try:
        yield
    finally:
        pop_skill_rules(token)


# ---------------------------------------------------------------------------
# Back-compat shims (the previous "hard restriction" API used by older
# call sites). They are intentionally lenient now: the old "deny if not
# in list" behaviour is no longer the spec, so :func:`is_tool_allowed`
# always returns ``True`` and :func:`disallowed_reason` always returns
# ``None``. They remain so any straggler imports keep working.
# ---------------------------------------------------------------------------


def current_restrictions() -> Tuple[Tuple[ToolRule, ...], ...]:
    """Deprecated alias for :func:`current_preapproval_frames`."""
    return current_preapproval_frames()


def is_tool_allowed(tool_name: str) -> bool:  # noqa: ARG001 — back-compat shim
    """Pre-approval is additive; no hard deny exists. Always returns ``True``."""
    return True


def disallowed_reason(tool_name: str) -> Optional[str]:  # noqa: ARG001
    """Pre-approval cannot deny; always returns ``None``."""
    return None


def push_restriction(
    allowed_tools: Optional[Iterable[str | ToolRule]],
) -> contextvars.Token:
    """Deprecated alias for :func:`push_skill_rules`."""
    return push_skill_rules(allowed_tools)


def pop_restriction(token: contextvars.Token) -> None:
    """Deprecated alias for :func:`pop_skill_rules`."""
    pop_skill_rules(token)


@contextmanager
def skill_restriction(
    allowed_tools: Optional[Iterable[str | ToolRule]],
) -> Iterator[None]:
    """Deprecated alias for :func:`skill_preapproval`."""
    with skill_preapproval(allowed_tools):
        yield


__all__ = [
    "current_preapproval_frames",
    "is_call_preapproved",
    "matched_rule",
    "push_skill_rules",
    "pop_skill_rules",
    "skill_preapproval",
    # Back-compat
    "current_restrictions",
    "is_tool_allowed",
    "disallowed_reason",
    "push_restriction",
    "pop_restriction",
    "skill_restriction",
]
