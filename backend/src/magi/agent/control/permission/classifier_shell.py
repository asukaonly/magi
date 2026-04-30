"""Shell command risk rules for permission classification."""

from __future__ import annotations

import re
from typing import Any

from .classifier_models import ClassificationResult, RiskSignal
from .contracts import RiskLevel


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
        "sed",
        "jq",
        "tr",
        "cut",
        "tee",
        "tar",
        "xargs",
        "basename",
        "dirname",
        "readlink",
        "realpath",
        "git",
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

_PIPE_OR_SEP = re.compile(r"[|;&]+|\&\&|\|\|")


def _command_text(arguments: dict[str, Any]) -> str:
    for key in ("command", "cmd", "script", "input"):
        value = arguments.get(key)
        if isinstance(value, str):
            return value
    return ""


def _split_shell_pipeline(cmd: str) -> list[list[str]]:
    """Split a command line into argv-like token lists per stage."""
    stages: list[list[str]] = []
    for chunk in _PIPE_OR_SEP.split(cmd):
        tokens = [token for token in chunk.strip().split() if token]
        if tokens:
            stages.append(tokens)
    return stages


def _shell_stage_risk(tokens: list[str]) -> tuple[RiskLevel, list[RiskSignal]]:
    """Classify a single pipeline stage."""
    if not tokens:
        return RiskLevel.LOW, []

    head = tokens[0]
    basename = head.rsplit("/", 1)[-1]

    if basename == "sudo":
        return RiskLevel.DESTRUCTIVE, [
            RiskSignal(key="sudo", description="command runs under sudo")
        ]

    if basename in _DESTRUCTIVE_SHELL_TOKENS:
        if basename == "git":
            sub = tokens[1] if len(tokens) > 1 else ""
            if sub and sub in _GIT_WRITE_SUBCMDS:
                if sub == "push" and any(
                    token in {"-f", "--force", "--force-with-lease"} for token in tokens[2:]
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

        if basename == "rm" and any(
            flag.startswith("-") and any(char in flag for char in "rRf") for flag in tokens[1:]
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

    if basename == "sed" and any(
        token == "-i" or token.startswith("-i") for token in tokens[1:]
    ):
        return RiskLevel.HIGH, [
            RiskSignal(key="sed_in_place", description="sed -i writes files")
        ]

    if basename == "tar" and any(
        flag.startswith("-") and any(char in flag for char in "cxf") for flag in tokens[1:]
    ):
        return RiskLevel.MEDIUM, [
            RiskSignal(key="tar_write", description="tar create/extract writes files")
        ]

    if basename in _BENIGN_SHELL_TOKENS:
        return RiskLevel.LOW, []

    return RiskLevel.MEDIUM, [
        RiskSignal(key="unknown_binary", description=f"unknown command '{basename}'")
    ]


def _risk_order(level: RiskLevel) -> int:
    return level.order


def classify_shell(arguments: dict[str, Any]) -> ClassificationResult:
    """Classify shell-like tool arguments."""
    cmd = _command_text(arguments)
    if not cmd.strip():
        return ClassificationResult(
            level=RiskLevel.LOW,
            signals=[RiskSignal(key="empty_command", description="empty command")],
            preview=None,
        )

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


__all__ = ["classify_shell"]
