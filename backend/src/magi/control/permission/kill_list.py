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
import shlex
from dataclasses import dataclass
from typing import Any, Callable

from magi_plugin_sdk.command_risk import powershell_removes_root

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
_POSIX_SHELL_TOOLS: tuple[str, ...] = (
    "bash",
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


def _match_rm_root(args: dict[str, Any]) -> bool:
    for stage in _shell_stages(_command_text(args)):
        for index, command in enumerate(stage):
            if command in {"rm", "/bin/rm", "/usr/bin/rm"} and any(
                target in {"/", "/*", "~", "~/", "~/*"}
                for target in stage[index + 1:]
            ):
                return True
    return False


def _match_remove_item_root(args: dict[str, Any]) -> bool:
    """Match a literal recursive PowerShell deletion of a filesystem root."""
    command = _command_text(args)
    if not command:
        return False
    return powershell_removes_root(command)


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


def _shell_stages(command: str) -> list[list[str]]:
    """Split literal shell stages while preserving quoted paths as operands."""
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|()<>\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        tokens = list(lexer)
    except ValueError:
        return []

    stages: list[list[str]] = []
    stage: list[str] = []
    for token in [*tokens, ";"]:
        if token and all(char in ";&|()\n" for char in token):
            if stage:
                stages.append(stage)
            stage = []
        else:
            stage.append(token)
    return stages


def _match_shell_system_write(args: dict[str, Any]) -> bool:
    return any(_stage_writes_system_path(stage) for stage in _shell_stages(_command_text(args)))


def _stage_writes_system_path(tokens: list[str]) -> bool:
    def protected(path: str) -> bool:
        return path.startswith(_SYSTEM_PATH_PREFIXES) or path in {
            prefix.rstrip("/") for prefix in _SYSTEM_PATH_PREFIXES
        }

    arguments: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token and all(char in "<>" for char in token):
            target = tokens[index + 1] if index + 1 < len(tokens) else ""
            if ">" in token and protected(target):
                return True
            index += 2
            continue
        arguments.append(token)
        index += 1

    for index, command in enumerate(arguments):
        if command in {"/bin/rm", "/usr/bin/rm"}:
            command = "rm"
        if command not in {"tee", "cp", "mv", "install", "ln", "rm"}:
            continue
        operands = arguments[index + 1:]
        if command in {"tee", "mv", "rm"} or (command == "install" and "-d" in operands):
            return any(protected(value) for value in operands)
        for position, value in enumerate(operands):
            if value in {"-t", "--target-directory"}:
                return position + 1 < len(operands) and protected(operands[position + 1])
            if value.startswith("--target-directory="):
                return protected(value.partition("=")[2])
            if value.startswith("-t") and len(value) > 2:
                return protected(value[2:])
        paths: list[str] = []
        position = 0
        while position < len(operands):
            value = operands[position]
            if value == "--":
                paths.extend(operands[position + 1:])
                break
            if value in {"-m", "--mode", "-o", "--owner", "-g", "--group", "-S", "--suffix"}:
                position += 2
                continue
            if not value.startswith("-"):
                paths.append(value)
            position += 1
        # Copying or linking an OS-owned source does not mutate that source.
        return bool(paths) and protected(paths[-1])
    return False


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
        tool_names=_POSIX_SHELL_TOOLS,
        predicate=_match_rm_root,
    ),
    KillListEntry(
        key="remove_item_root",
        description="PowerShell recursively removing a drive, share, or user root",
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
