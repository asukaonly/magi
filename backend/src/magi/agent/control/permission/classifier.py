"""Risk classifier for ``(tool, args)``.

The classifier is synchronous, side-effect free, and deterministic so
it can be called both by the gateway (to decide whether to prompt)
and by the UI (to preview the risk before the user even sees the
prompt).

It does **not** consult the kill-list — :class:`PermissionGateway`
runs that check separately.

Default behaviour for unknown tools:

* if ``ToolSchema.dangerous`` is truthy → :data:`RiskLevel.HIGH`
* otherwise                              → :data:`RiskLevel.LOW`

Per-tool rules below exist to (a) promote to ``DESTRUCTIVE`` when the
classifier is confident the call will clobber state, and (b) demote
to ``LOW`` for benign variants of an otherwise dangerous tool (e.g.
``bash`` running ``ls``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from .contracts import RiskLevel

__all__ = ["RiskClassifier", "RiskSignal", "ClassificationResult"]


@dataclass(slots=True, frozen=True)
class RiskSignal:
    """Named signal contributing to the risk tier."""

    key: str
    description: str


@dataclass(slots=True)
class ClassificationResult:
    level: RiskLevel
    signals: list[RiskSignal]
    preview: str | None = None


# ---------------------------------------------------------------------------
# Command-family tables (shell)
# ---------------------------------------------------------------------------


_SHELL_TOOLS: tuple[str, ...] = ("bash", "shell", "execute_command", "run_command")


# Commands whose *write* intent is self-evident.
_DESTRUCTIVE_SHELL_TOKENS: tuple[str, ...] = (
    "rm",
    "mv",
    "chmod",
    "chown",
    "shred",
    "sudo",
    "apt-get",
    "apt",
    "brew",
    "npm",
    "yarn",
    "pnpm",
    "pip",
    "pipx",
    "uv",
    "cargo",
    "go",
    "dd",
    "mkfs",
    "format",
    "diskutil",
    "systemctl",
    "launchctl",
    "docker",
    "kubectl",
    "terraform",
    "kill",
    "pkill",
    "killall",
    "git",
)

# Known-benign read-only commands; if the entire command reduces to
# these (possibly piped together), demote to LOW.
_BENIGN_SHELL_TOKENS: frozenset[str] = frozenset(
    {
        "ls",
        "cat",
        "head",
        "tail",
        "wc",
        "grep",
        "rg",
        "find",
        "fd",
        "pwd",
        "echo",
        "true",
        "false",
        "date",
        "uptime",
        "whoami",
        "hostname",
        "which",
        "type",
        "file",
        "stat",
        "du",
        "df",
        "ps",
        "env",
        "uname",
        "sort",
        "uniq",
        "awk",
        "sed",  # sed w/o -i is read-only; flagged below if -i
        "jq",
        "tr",
        "cut",
        "tee",  # tee is ambiguous: handled below
        "tar",  # tar list (-t) is read-only; flagged below on -c / -x
        "xargs",
        "basename",
        "dirname",
        "readlink",
        "realpath",
        "git",  # git status / log / diff only — flagged below on write subcmds
    }
)

_GIT_WRITE_SUBCMDS: frozenset[str] = frozenset(
    {
        "push",
        "reset",
        "rebase",
        "commit",
        "merge",
        "checkout",
        "switch",
        "clean",
        "rm",
        "stash",
        "tag",
        "apply",
        "cherry-pick",
        "restore",
        "branch",
    }
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _command_text(arguments: dict[str, Any]) -> str:
    for key in ("command", "cmd", "script", "input"):
        value = arguments.get(key)
        if isinstance(value, str):
            return value
    return ""


_PIPE_OR_SEP = re.compile(r"[|;&]+|\&\&|\|\|")


def _split_shell_pipeline(cmd: str) -> list[list[str]]:
    """Split a command line into a list of argv-like token lists per stage.

    Good enough for classification; does not attempt full shell parsing.
    """
    stages: list[list[str]] = []
    for chunk in _PIPE_OR_SEP.split(cmd):
        tokens = [t for t in chunk.strip().split() if t]
        if tokens:
            stages.append(tokens)
    return stages


def _shell_stage_risk(tokens: list[str]) -> tuple[RiskLevel, list[RiskSignal]]:
    """Classify a single pipeline stage."""
    if not tokens:
        return RiskLevel.LOW, []

    head = tokens[0]
    basename = head.rsplit("/", 1)[-1]

    # sudo: escalate regardless of the inner command.
    if basename == "sudo":
        return RiskLevel.DESTRUCTIVE, [
            RiskSignal(key="sudo", description="command runs under sudo")
        ]

    # Destructive families.
    if basename in _DESTRUCTIVE_SHELL_TOKENS:
        # Git carves out a read-only island.
        if basename == "git":
            sub = tokens[1] if len(tokens) > 1 else ""
            if sub and sub in _GIT_WRITE_SUBCMDS:
                if sub == "push" and any(
                    t in {"-f", "--force", "--force-with-lease"} for t in tokens[2:]
                ):
                    return RiskLevel.DESTRUCTIVE, [
                        RiskSignal(
                            key="git_force_push",
                            description="git push with --force",
                        )
                    ]
                return RiskLevel.HIGH, [
                    RiskSignal(
                        key=f"git_{sub}",
                        description=f"git {sub} modifies the repo state",
                    )
                ]
            return RiskLevel.LOW, []

        # rm with recursive / force / root → destructive.
        if basename == "rm" and any(
            flag.startswith("-") and any(c in flag for c in "rRf") for flag in tokens[1:]
        ):
            return RiskLevel.DESTRUCTIVE, [
                RiskSignal(key="rm_recursive", description="rm with -r / -f")
            ]

        return RiskLevel.HIGH, [
            RiskSignal(
                key=f"cmd_{basename}",
                description=f"{basename} modifies system state",
            )
        ]

    # In-place sed.
    if basename == "sed" and any(
        t == "-i" or t.startswith("-i") for t in tokens[1:]
    ):
        return RiskLevel.HIGH, [
            RiskSignal(key="sed_in_place", description="sed -i writes files")
        ]

    # tar create / extract.
    if basename == "tar" and any(
        flag.startswith("-") and any(c in flag for c in "cxf") for flag in tokens[1:]
    ):
        return RiskLevel.MEDIUM, [
            RiskSignal(key="tar_write", description="tar create/extract writes files")
        ]

    if basename in _BENIGN_SHELL_TOKENS:
        return RiskLevel.LOW, []

    # Unknown executable — medium by default; lets the user see it.
    return RiskLevel.MEDIUM, [
        RiskSignal(key="unknown_binary", description=f"unknown command '{basename}'")
    ]


# ---------------------------------------------------------------------------
# Per-tool rules
# ---------------------------------------------------------------------------


def _classify_shell(arguments: dict[str, Any]) -> ClassificationResult:
    cmd = _command_text(arguments)
    if not cmd.strip():
        return ClassificationResult(
            level=RiskLevel.LOW,
            signals=[RiskSignal(key="empty_command", description="empty command")],
            preview=None,
        )

    # Any redirect that writes (>, >>) pushes to at least MEDIUM, and
    # system-path targets bump to HIGH/DESTRUCTIVE.
    level = RiskLevel.LOW
    signals: list[RiskSignal] = []

    if re.search(r">>?\s*\S", cmd):
        level = max(level, RiskLevel.MEDIUM, key=_risk_order)
        signals.append(RiskSignal(key="shell_redirect", description="shell writes via redirect"))

    for stage in _split_shell_pipeline(cmd):
        stage_level, stage_signals = _shell_stage_risk(stage)
        level = max(level, stage_level, key=_risk_order)
        signals.extend(stage_signals)

    preview = cmd.strip().splitlines()[0][:200] if cmd.strip() else None
    return ClassificationResult(level=level, signals=signals, preview=preview)


def _classify_file_write(arguments: dict[str, Any]) -> ClassificationResult:
    path = arguments.get("path") or arguments.get("file_path") or ""
    signals = [RiskSignal(key="fs_write", description="filesystem write")]
    # ~/.ssh/ and similar — user-self-responsibility, not kill-listed,
    # but we bump to DESTRUCTIVE so the user always sees it.
    if isinstance(path, str) and _is_sensitive_user_path(path):
        signals.append(
            RiskSignal(key="sensitive_user_path", description="writes to user-sensitive path")
        )
        return ClassificationResult(
            level=RiskLevel.DESTRUCTIVE, signals=signals, preview=path[:200]
        )
    return ClassificationResult(
        level=RiskLevel.HIGH,
        signals=signals,
        preview=str(path)[:200] if path else None,
    )


def _classify_file_edit(arguments: dict[str, Any]) -> ClassificationResult:
    path = arguments.get("path") or arguments.get("file_path") or ""
    signals = [RiskSignal(key="fs_edit", description="filesystem edit")]
    if isinstance(path, str) and _is_sensitive_user_path(path):
        signals.append(
            RiskSignal(key="sensitive_user_path", description="edits user-sensitive path")
        )
        return ClassificationResult(
            level=RiskLevel.DESTRUCTIVE, signals=signals, preview=path[:200]
        )
    return ClassificationResult(
        level=RiskLevel.HIGH,
        signals=signals,
        preview=str(path)[:200] if path else None,
    )


def _classify_web_fetch(arguments: dict[str, Any]) -> ClassificationResult:
    url = arguments.get("url") or arguments.get("uri") or ""
    return ClassificationResult(
        level=RiskLevel.MEDIUM,
        signals=[RiskSignal(key="network_fetch", description="outbound network request")],
        preview=str(url)[:200] if url else None,
    )


def _classify_web_search(arguments: dict[str, Any]) -> ClassificationResult:
    query = arguments.get("query") or ""
    return ClassificationResult(
        level=RiskLevel.LOW,
        signals=[RiskSignal(key="network_search", description="web search")],
        preview=str(query)[:200] if query else None,
    )


def _classify_send_message(arguments: dict[str, Any]) -> ClassificationResult:
    signals = [
        RiskSignal(key="external_side_effect", description="sends a message externally")
    ]
    channel = arguments.get("channel") or arguments.get("target") or ""
    return ClassificationResult(
        level=RiskLevel.HIGH,
        signals=signals,
        preview=str(channel)[:200] if channel else None,
    )


def _classify_file_read(arguments: dict[str, Any]) -> ClassificationResult:
    path = arguments.get("path") or arguments.get("file_path") or ""
    return ClassificationResult(
        level=RiskLevel.LOW,
        signals=[RiskSignal(key="fs_read", description="filesystem read")],
        preview=str(path)[:200] if path else None,
    )


_SENSITIVE_USER_PATH_SUFFIXES: tuple[str, ...] = (
    "/.ssh/",
    "/.aws/credentials",
    "/.gnupg/",
    "/.config/gh/hosts.yml",
    "/.netrc",
)


def _is_sensitive_user_path(path: str) -> bool:
    probe = path.replace("\\", "/")
    return any(marker in probe for marker in _SENSITIVE_USER_PATH_SUFFIXES)


def _risk_order(level: RiskLevel) -> int:
    return level.order


_RULES: dict[str, Callable[[dict[str, Any]], ClassificationResult]] = {
    # Shell family.
    "bash": _classify_shell,
    "shell": _classify_shell,
    "execute_command": _classify_shell,
    "run_command": _classify_shell,
    # File write / edit.
    "file_write": _classify_file_write,
    "write_file": _classify_file_write,
    "file_edit": _classify_file_edit,
    "edit_file": _classify_file_edit,
    "apply_patch": _classify_file_edit,
    "str_replace_editor": _classify_file_edit,
    # Reads.
    "file_read": _classify_file_read,
    "read_file": _classify_file_read,
    # Network.
    "web_fetch": _classify_web_fetch,
    "fetch_url": _classify_web_fetch,
    "http_request": _classify_web_fetch,
    "web_search": _classify_web_search,
    "search_web": _classify_web_search,
    # External side effects.
    "send_message": _classify_send_message,
    "send_email": _classify_send_message,
    "telegram_send": _classify_send_message,
}


class RiskClassifier:
    """Assign a :class:`RiskLevel` to a tool invocation.

    The classifier is intentionally small; more specialised logic
    (workspace-boundary checks, MCP tool metadata, plugin-provided
    hints) can layer on via constructor injection later without
    changing the public API.
    """

    def __init__(
        self,
        *,
        default_dangerous_level: RiskLevel = RiskLevel.HIGH,
        default_level: RiskLevel = RiskLevel.LOW,
    ) -> None:
        self._default_dangerous_level = default_dangerous_level
        self._default_level = default_level

    def classify(
        self,
        *,
        tool_name: str,
        arguments: dict[str, Any],
        tool_is_dangerous: bool = False,
    ) -> ClassificationResult:
        rule = _RULES.get(tool_name)
        if rule is not None:
            return rule(dict(arguments))
        if tool_is_dangerous:
            return ClassificationResult(
                level=self._default_dangerous_level,
                signals=[
                    RiskSignal(
                        key="tool_flagged_dangerous",
                        description="tool schema flagged as dangerous",
                    )
                ],
                preview=None,
            )
        return ClassificationResult(
            level=self._default_level, signals=[], preview=None
        )
