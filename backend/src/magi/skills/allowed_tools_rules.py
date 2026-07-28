"""Parser and matcher for the Claude Code Skills ``allowed-tools`` field.

Per the Claude Code spec the field is a pre-approval list, *not* a hard
restriction. Each entry has the shape ``Tool`` or ``Tool(pattern)``:

* ``Read`` — pre-approves every call to the ``Read`` tool.
* ``Bash(git add *)`` — pre-approves Bash calls whose ``command``
  argument matches the glob ``git add *``.
* ``Bash(npx agent-browser:*)`` — same idea; the colon is just part of
  the glob, the spec doesn't give ``:`` any special meaning.

Accepted source formats from YAML:

* a list of strings: ``[Read, "Bash(git add *)"]``
* a space-separated string: ``Bash(git add *) Bash(git commit *)``
* a comma-separated string: ``Bash(npm:*), Bash(git:*)``
* any mix of the above (whitespace and commas are equivalent separators).

The parser is balanced-paren-aware so embedded spaces inside
``Bash(git add *)`` do not split the token.
"""

from __future__ import annotations

import fnmatch
import logging
import re
from dataclasses import dataclass
from typing import Any, Iterable, List, Mapping, Optional, Sequence

logger = logging.getLogger(__name__)


# Tool names per Claude Code: alphanumeric, underscore, hyphen.
_TOOL_NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_-]*")


@dataclass(frozen=True)
class ToolRule:
    """A single parsed ``allowed-tools`` entry.

    ``pattern`` is ``None`` for bare ``Read``-style rules (match any
    invocation of the tool). Otherwise it is the raw pattern lifted out
    of ``Tool(pattern)``.
    """

    tool: str
    pattern: Optional[str]

    @property
    def display(self) -> str:
        return self.tool if self.pattern is None else f"{self.tool}({self.pattern})"


def parse_allowed_tools(raw: Any) -> List[ToolRule]:
    """Normalize a raw YAML value into a list of :class:`ToolRule`.

    Returns an empty list for ``None`` / unsupported types so the caller
    can treat "no rules" uniformly. Malformed tokens are skipped with a
    warning rather than aborting the whole parse — one broken entry
    shouldn't disable a skill's other (valid) rules.
    """
    if raw is None:
        return []
    if isinstance(raw, ToolRule):
        return [raw]
    tokens: List[str] = []
    if isinstance(raw, str):
        tokens = _tokenize(raw)
    elif isinstance(raw, (list, tuple)):
        for item in raw:
            if isinstance(item, str):
                tokens.extend(_tokenize(item))
            elif isinstance(item, ToolRule):
                tokens.append(item.display)
    else:
        logger.warning("allowed-tools must be a string or list; got %s", type(raw).__name__)
        return []

    rules: List[ToolRule] = []
    for token in tokens:
        rule = _parse_token(token)
        if rule is not None:
            rules.append(rule)
    return rules


def _tokenize(value: str) -> List[str]:
    """Split a raw string into tool tokens, respecting balanced parens.

    Whitespace and commas are equivalent separators outside parens.
    """
    tokens: List[str] = []
    current: List[str] = []
    depth = 0
    for ch in value:
        if ch == "(":
            depth += 1
            current.append(ch)
        elif ch == ")":
            depth = max(0, depth - 1)
            current.append(ch)
        elif depth == 0 and (ch.isspace() or ch == ","):
            if current:
                tokens.append("".join(current))
                current = []
        else:
            current.append(ch)
    if current:
        tokens.append("".join(current))
    return [t for t in (s.strip() for s in tokens) if t]


def _parse_token(token: str) -> Optional[ToolRule]:
    token = token.strip()
    if not token:
        return None
    if "(" not in token:
        if not _TOOL_NAME_PATTERN.fullmatch(token):
            logger.warning("ignoring invalid allowed-tools token: %r", token)
            return None
        return ToolRule(tool=token, pattern=None)
    open_idx = token.index("(")
    tool = token[:open_idx].strip()
    if not _TOOL_NAME_PATTERN.fullmatch(tool):
        logger.warning("ignoring invalid allowed-tools tool name: %r", token)
        return None
    if not token.endswith(")"):
        logger.warning("ignoring unbalanced allowed-tools token: %r", token)
        return None
    pattern = token[open_idx + 1 : -1].strip()
    return ToolRule(tool=tool, pattern=pattern or None)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _specifier_for(tool_name: str, arguments: Mapping[str, Any]) -> str:
    """Return the string that ``Tool(pattern)`` is matched against.

    The choice of "specifier" is tool-dependent and mirrors how
    Claude Code's permission rules behave:

    * ``Bash`` — the ``command`` argument.
    * ``Read`` / ``Write`` / ``Edit`` / ``Glob`` — the ``path`` /
      ``file_path`` / ``pattern`` argument depending on which is set.
    * Anything else — the value of any single string argument, else
      ``""``.

    If we cannot derive a sensible specifier, we return ``""`` and a
    bare rule (no pattern) will still match, while a patterned rule
    will only match the empty string.
    """
    if not arguments:
        return ""
    args = dict(arguments)
    if tool_name == "Bash" or tool_name == "bash":
        cmd = args.get("command") or args.get("cmd") or ""
        return str(cmd)
    for key in ("file_path", "path", "pattern", "query", "url"):
        if key in args and args[key] is not None:
            return str(args[key])
    string_values = [
        str(v) for v in args.values() if isinstance(v, str) and v
    ]
    if len(string_values) == 1:
        return string_values[0]
    return ""


def rule_matches(rule: ToolRule, tool_name: str, arguments: Mapping[str, Any]) -> bool:
    """Return True if ``rule`` pre-approves the given tool call.

    Tool-name match is **case-sensitive** to mirror Claude Code's
    behaviour. Patterns use ``fnmatch`` glob semantics (``*``, ``?``,
    ``[...]``) against the tool-specific specifier returned by
    :func:`_specifier_for`.
    """
    if rule.tool != tool_name:
        return False
    if rule.pattern is None:
        return True
    specifier = _specifier_for(tool_name, arguments)
    return fnmatch.fnmatchcase(specifier, rule.pattern)


def any_rule_matches(
    rules: Iterable[ToolRule],
    tool_name: str,
    arguments: Mapping[str, Any],
) -> bool:
    return any(rule_matches(r, tool_name, arguments) for r in rules)


def rules_to_strings(rules: Sequence[ToolRule]) -> List[str]:
    """Render rules back to their display strings (for logs, prologues, telemetry)."""
    return [r.display for r in rules]


__all__ = [
    "ToolRule",
    "parse_allowed_tools",
    "rule_matches",
    "any_rule_matches",
    "rules_to_strings",
]
