"""Hardcoded safety fuse against LLM glitches and prompt injection.

This is **not** part of the permission model. These are patterns for
which no legitimate developer workflow exists, so we refuse to run
them regardless of mode (including ``PermissionMode.OFF``) and
regardless of any persistent user rule.

Design rule: if a developer could plausibly want to do it — even once
a year — it does **not** belong here. It belongs in the risk
classifier at ``HIGH`` or ``DESTRUCTIVE``.

Additions to this list are a security-sensitive change. Keep the
criteria tight.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

__all__ = [
    "KillListEntry",
    "KillListMatch",
    "KILL_LIST",
    "check_kill_list",
]


@dataclass(slots=True, frozen=True)
class KillListEntry:
    """One rule on the kill list."""

    key: str
    description: str
    #: Tools this rule applies to (empty = all tools).
    tool_names: tuple[str, ...]
    #: Predicate run over the tool arguments; returns ``True`` to kill.
    predicate: Callable[[dict[str, Any]], bool]


@dataclass(slots=True, frozen=True)
class KillListMatch:
    entry: KillListEntry
    reason: str


# ---------------------------------------------------------------------------
# Shell-command predicates
# ---------------------------------------------------------------------------


_SHELL_TOOLS: tuple[str, ...] = (
    "bash",
    "powershell",
    "shell",
    "execute_command",
    "run_command",
)


def _command_text(arguments: dict[str, Any]) -> str:
    """Pull the command string out of whatever arg shape the tool uses."""
    for key in ("command", "cmd", "script", "input"):
        value = arguments.get(key)
        if isinstance(value, str):
            return value
    return ""


# rm -rf / (or equivalent: rm -rf --no-preserve-root /)
_RE_RM_ROOT = re.compile(
    r"""
    \brm\s+                         # rm
    (?:-[A-Za-z]*[rRf][A-Za-z]*\s+)+ # one or more flags including -r/-R and -f (any order)
    (?:--no-preserve-root\s+)?      # optional explicit override
    (?:/|/\*|/\s*$|/\s*;|~/?\s*$)   # the target: bare root or ~
    """,
    re.VERBOSE,
)


def _match_rm_root(args: dict[str, Any]) -> bool:
    cmd = _command_text(args)
    if not cmd:
        return False
    # Normalise trailing whitespace; add sentinel newline so "/" at EOL matches.
    probe = cmd.strip() + "\n"
    return bool(_RE_RM_ROOT.search(probe))


_RE_REMOVE_ITEM = re.compile(r"\bRemove-Item\b(?P<arguments>[^|;&]*)", re.IGNORECASE)
_RE_POWERSHELL_ROOT = re.compile(
    r"(?<!\S)[\"']?(?:[A-Za-z]:[\\/]|~[\\/]?|\$HOME[\\/]?)[\"']?(?=\s|$)",
    re.IGNORECASE,
)


def _match_remove_item_root(args: dict[str, Any]) -> bool:
    """Match recursive forced deletion of a Windows or user root."""
    command = _command_text(args)
    for match in _RE_REMOVE_ITEM.finditer(command):
        arguments = match.group("arguments")
        if not re.search(r"(?:^|\s)-Recurse(?:\s|$)", arguments, re.IGNORECASE):
            continue
        if not re.search(r"(?:^|\s)-Force(?:\s|$)", arguments, re.IGNORECASE):
            continue
        if _RE_POWERSHELL_ROOT.search(arguments):
            return True
    return False


# dd if=... of=/dev/{disk,sd*,nvme*,rdisk*}
_RE_DD_DEVICE = re.compile(
    r"""
    \bdd\b.*?                       # dd
    \bof=                           # of=
    (?:/dev/(?:disk|sd|nvme|rdisk|hd|mmcblk)[A-Za-z0-9]*) # block device
    """,
    re.VERBOSE | re.DOTALL,
)


def _match_dd_device(args: dict[str, Any]) -> bool:
    cmd = _command_text(args)
    return bool(_RE_DD_DEVICE.search(cmd))


# mkfs.* or `mkfs -t <fs>` on /dev/{disk,sd*,nvme*,rdisk*}
_RE_MKFS_DEVICE = re.compile(
    r"""
    \bmkfs(?:\.[A-Za-z0-9]+)?\b     # mkfs or mkfs.ext4 etc
    (?:\s+[^\s/]+)*?                # optional flags / fs-type args
    \s+/dev/(?:disk|sd|nvme|rdisk|hd|mmcblk)[A-Za-z0-9]*
    """,
    re.VERBOSE,
)


def _match_mkfs_device(args: dict[str, Any]) -> bool:
    cmd = _command_text(args)
    return bool(_RE_MKFS_DEVICE.search(cmd))


# Classic fork-bomb: :(){ :|:& };:
_RE_FORK_BOMB = re.compile(r":\(\s*\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:")


def _match_fork_bomb(args: dict[str, Any]) -> bool:
    cmd = _command_text(args)
    return bool(_RE_FORK_BOMB.search(cmd))


# curl|sh / wget|sh: piping a remote script straight into a shell.
_RE_CURL_PIPE_SHELL = re.compile(
    r"""
    \b(?:curl|wget|fetch)\b         # curl / wget / fetch
    [^|;&]*?                        # any args (no pipe boundary)
    \|\s*                           # pipe
    (?:sudo\s+)?                    # optional sudo
    (?:sh|bash|zsh|ksh|dash|fish)\b # shell interpreter
    """,
    re.VERBOSE,
)


def _match_curl_pipe_shell(args: dict[str, Any]) -> bool:
    cmd = _command_text(args)
    return bool(_RE_CURL_PIPE_SHELL.search(cmd))


# Writes to system-owned paths we never want to touch from an agent.
_SYSTEM_PATH_PREFIXES: tuple[str, ...] = (
    "/System/",
    "/usr/bin/",
    "/usr/sbin/",
    "/sbin/",
    "/bin/",
    "/Library/Apple/",
    "C:\\Windows\\System32\\",
    "C:/Windows/System32/",
)


def _match_shell_system_write(args: dict[str, Any]) -> bool:
    cmd = _command_text(args)
    if not cmd:
        return False
    # Only match when a redirect or write command targets a system path.
    # Accepted indicators: `> /System/...`, `>> /System/...`,
    # `tee /System/...`, `cp ... /System/...`.
    if not re.search(r">>?\s*/(?:System|usr/s?bin|sbin|bin)/", cmd):
        if not re.search(
            r"\b(?:tee|cp|mv|install|ln)\b[^\n]*?\s/(?:System|usr/s?bin|sbin|bin)/",
            cmd,
        ):
            return False
    return True


# File-tool predicates: protect system paths for dedicated write / edit tools.


_FILE_WRITE_TOOLS: tuple[str, ...] = (
    "file_write",
    "write_file",
    "file_edit",
    "edit_file",
    "apply_patch",
    "str_replace_editor",
)


def _match_file_tool_system_path(args: dict[str, Any]) -> bool:
    path = args.get("path") or args.get("file_path") or args.get("filename") or ""
    if not isinstance(path, str) or not path:
        return False
    return path.startswith(_SYSTEM_PATH_PREFIXES)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


KILL_LIST: tuple[KillListEntry, ...] = (
    KillListEntry(
        key="rm_rf_root",
        description="rm -rf targeting the filesystem root or $HOME root",
        tool_names=_SHELL_TOOLS,
        predicate=_match_rm_root,
    ),
    KillListEntry(
        key="remove_item_root",
        description="Remove-Item recursively and forcibly targeting a drive or user root",
        tool_names=_SHELL_TOOLS,
        predicate=_match_remove_item_root,
    ),
    KillListEntry(
        key="dd_to_block_device",
        description="dd writing to a raw block device (of=/dev/...)",
        tool_names=_SHELL_TOOLS,
        predicate=_match_dd_device,
    ),
    KillListEntry(
        key="mkfs_on_device",
        description="mkfs formatting a raw block device",
        tool_names=_SHELL_TOOLS,
        predicate=_match_mkfs_device,
    ),
    KillListEntry(
        key="fork_bomb",
        description="classic :(){ :|:& };: fork bomb",
        tool_names=_SHELL_TOOLS,
        predicate=_match_fork_bomb,
    ),
    KillListEntry(
        key="curl_pipe_shell",
        description="piping a remote download directly into a shell",
        tool_names=_SHELL_TOOLS,
        predicate=_match_curl_pipe_shell,
    ),
    KillListEntry(
        key="shell_write_to_system_path",
        description="shell redirect or copy targeting OS-owned path",
        tool_names=_SHELL_TOOLS,
        predicate=_match_shell_system_write,
    ),
    KillListEntry(
        key="file_tool_system_path",
        description="direct write/edit via a file tool to an OS-owned path",
        tool_names=_FILE_WRITE_TOOLS,
        predicate=_match_file_tool_system_path,
    ),
)


def check_kill_list(
    *,
    tool_name: str,
    arguments: dict[str, Any],
) -> KillListMatch | None:
    """Return the first matching :class:`KillListEntry`, or ``None``."""
    for entry in KILL_LIST:
        if entry.tool_names and tool_name not in entry.tool_names:
            continue
        try:
            if entry.predicate(arguments):
                return KillListMatch(entry=entry, reason=entry.description)
        except Exception:  # defensive: a broken predicate must not open the gate
            continue
    return None
