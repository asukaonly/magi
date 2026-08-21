"""Lexical Bash/PowerShell command risk classifier.

Three tiers:

* ``read_only`` - observed read-only utilities and read-only ``git`` subcommands.
* ``mutating``  - anything else that we can't prove is safe (default).
* ``destructive`` - known irreversible / wide-blast-radius patterns.

The classifier is intentionally small and lexical. It does NOT parse the shell
grammar. A determined adversary can bypass it (see ``$()`` / ``eval``); the
goal is to prevent typical agent mistakes, not to be a security boundary.
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from magi_plugin_sdk.permissions import ClassificationResult

RiskLevel = Literal["read_only", "mutating", "destructive"]


@dataclass(frozen=True)
class CommandGrade:
    level: RiskLevel
    reason: str


_READ_ONLY_HEADS = frozenset({
    "ls", "cat", "pwd", "echo", "which", "whoami", "env", "printenv",
    "date", "uname", "hostname", "id", "stat", "wc", "head", "tail",
    "grep", "egrep", "fgrep", "rg", "ripgrep",
    "ag", "ack",
    "awk", "cut", "sort", "uniq", "tr",
    "ps", "top", "htop", "df", "du", "lsof", "netstat", "ifconfig", "ip",
    "tree", "file",
    "true", "false", "type", "command", "alias", "history",
    "basename", "dirname", "realpath", "readlink",
    "diff", "cmp", "md5sum", "sha256sum", "sha1sum",
})

_READ_ONLY_GIT = frozenset({
    "status", "log", "diff", "show", "branch", "remote", "config",
    "blame", "describe", "shortlog", "tag", "ls-files", "ls-tree",
    "rev-parse", "rev-list", "reflog",
    "cat-file", "grep", "fsck", "annotate", "bisect", "name-rev",
})

_HEAD_SUBCMD_READ_ONLY = {
    "git": _READ_ONLY_GIT,
    "docker": frozenset({"ps", "images", "logs", "inspect", "version", "info", "stats", "history"}),
    "kubectl": frozenset({"get", "describe", "logs", "version", "explain", "config", "api-resources"}),
    "pip": frozenset({"list", "show", "freeze"}),
    "npm": frozenset({"list", "ls", "view", "outdated"}),
    "cargo": frozenset({"check", "tree", "search"}),
    "go": frozenset({"version", "env"}),
}

_DESTRUCTIVE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # Order matters: more specific patterns must precede broader ones so the
    # reported reason is the most useful one (e.g. 'find -exec rm' beats 'rm -rf').
    (re.compile(r"\bfind\b[^|;&]*\s-delete\b"), "find -delete"),
    (re.compile(r"\bfind\b[^|;&]*\s-exec\s+rm\b"), "find -exec rm"),
    (re.compile(r"\brm\b(?=(?:[^|;&]*\s)?-[a-zA-Z]*r)(?=(?:[^|;&]*\s)?-[a-zA-Z]*f)"), "rm -rf"),
    (re.compile(r"\bgit\s+push\b[^|;&]*--force(?:-with-lease)?\b"), "git push --force"),
    (re.compile(r"\bgit\s+push\b[^|;&]*\s-f\b"), "git push -f (force)"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "git reset --hard"),
    (re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f"), "git clean -f"),
    (re.compile(r"\bdd\b[^|;&]*\s(?:if|of)=/dev/"), "dd targeting /dev"),
    (re.compile(r"\bmkfs(\.[a-z0-9]+)?\b"), "mkfs"),
    (re.compile(r"\bshred\b"), "shred"),
    (re.compile(r"\bchmod\s+-R\s+0?777\b"), "chmod -R 777"),
    (re.compile(r":\(\)\s*\{\s*:\s*\|:.*&\s*\}"), "fork bomb"),
    (re.compile(r"\bshutdown\b"), "shutdown"),
    (re.compile(r"\breboot\b"), "reboot"),
    (re.compile(r"\bhalt\b"), "halt"),
    (re.compile(r"\bpoweroff\b"), "poweroff"),
    (re.compile(r"\bdrop\s+(?:database|table)\b", re.IGNORECASE), "drop database/table"),
    (re.compile(r"\bdocker\s+system\s+prune\b"), "docker system prune"),
    (re.compile(r"\bkubectl\s+delete\b[^|;&]*\s--all\b"), "kubectl delete --all"),
    (re.compile(r"\bRemove-Item\b[^|;&]*-Recurse\b[^|;&]*-Force\b", re.IGNORECASE),
     "Remove-Item -Recurse -Force"),
    (re.compile(r"\bRemove-Item\b[^|;&]*-Force\b[^|;&]*-Recurse\b", re.IGNORECASE),
     "Remove-Item -Force -Recurse"),
    (re.compile(r"\bFormat-Volume\b", re.IGNORECASE), "Format-Volume"),
    (re.compile(r"\bClear-RecycleBin\b[^|;&]*-Force\b", re.IGNORECASE),
     "Clear-RecycleBin -Force"),
    (re.compile(r"\bStop-Computer\b", re.IGNORECASE), "Stop-Computer"),
    (re.compile(r"\bRestart-Computer\b", re.IGNORECASE), "Restart-Computer"),
]

_SUBSHELL_SIGNALS = re.compile(r"\$\(|<\(|>\(|`|\beval\b|\bsource\b")
_REDIRECT_SIGNALS = re.compile(r"(?<![<>])>>?(?!\&)")


def _classify_token_head(tokens: list[str]) -> tuple[RiskLevel, str]:
    i = 0
    while i < len(tokens) and (
        tokens[i] == "sudo"
        or ("=" in tokens[i] and tokens[i].split("=")[0].isidentifier())
    ):
        i += 1
    if i >= len(tokens):
        return "mutating", "empty subcommand"
    head = tokens[i]
    rest = tokens[i + 1:]

    if head == "sed":
        only_n = any(arg == "-n" for arg in rest) and not any(
            arg.startswith("-i") for arg in rest
        )
        return ("read_only", "sed -n") if only_n else ("mutating", "sed mutating")

    if head == "make":
        if any(arg == "-n" for arg in rest):
            return "read_only", "make -n (dry run)"
        return "mutating", "make"

    if head == "find":
        # find without -delete / -exec mutating actions is read-only.
        # The destructive patterns above already catch -delete and -exec rm.
        return "read_only", "find read-only"

    # Programs invoked purely for version/help info are read-only.
    if rest and rest[0] in {"--version", "-V", "--help", "-h", "version"}:
        return "read_only", f"{head} {rest[0]}"

    if head in _READ_ONLY_HEADS:
        return "read_only", f"{head} read-only"

    if head in _HEAD_SUBCMD_READ_ONLY:
        if rest and rest[0] in _HEAD_SUBCMD_READ_ONLY[head]:
            return "read_only", f"{head} {rest[0]} read-only"
        return "mutating", f"{head} {rest[0] if rest else ''} mutating"

    return "mutating", f"unknown command {head!r}"


def _split_pipeline(command: str) -> list[str]:
    parts: list[str] = []
    buf: list[str] = []
    i = 0
    paren_depth = 0
    backtick = False
    while i < len(command):
        ch = command[i]
        nxt = command[i + 1] if i + 1 < len(command) else ""
        if ch == "(" and not backtick:
            paren_depth += 1
            buf.append(ch)
            i += 1
            continue
        if ch == ")" and not backtick:
            paren_depth = max(0, paren_depth - 1)
            buf.append(ch)
            i += 1
            continue
        if ch == "`":
            backtick = not backtick
            buf.append(ch)
            i += 1
            continue
        if paren_depth == 0 and not backtick:
            if ch == "&" and nxt == "&":
                parts.append("".join(buf))
                buf = []
                i += 2
                continue
            if ch == "|" and nxt == "|":
                parts.append("".join(buf))
                buf = []
                i += 2
                continue
            if ch == ";":
                parts.append("".join(buf))
                buf = []
                i += 1
                continue
            if ch == "|":
                parts.append("".join(buf))
                buf = []
                i += 1
                continue
        buf.append(ch)
        i += 1
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def _max_level(a: RiskLevel, b: RiskLevel) -> RiskLevel:
    order = {"read_only": 0, "mutating": 1, "destructive": 2}
    return a if order[a] >= order[b] else b


def classify_command(command: str) -> CommandGrade:
    """Classify a shell command string."""
    text = (command or "").strip()
    if not text:
        return CommandGrade("mutating", "empty command (defensive default)")

    for pat, reason in _DESTRUCTIVE_PATTERNS:
        if pat.search(text):
            return CommandGrade("destructive", reason)

    parts = _split_pipeline(text)
    level: RiskLevel = "read_only"
    best_reason = "all parts read-only"
    for part in parts:
        try:
            tokens = shlex.split(part, posix=True)
        except ValueError:
            tokens = part.split()
        if not tokens:
            continue
        sub_level, sub_reason = _classify_token_head(tokens)
        if _max_level(level, sub_level) != level:
            level = sub_level
            best_reason = sub_reason

    if level == "read_only" and _SUBSHELL_SIGNALS.search(text):
        return CommandGrade("mutating", "subshell/eval/source - opaque content")

    if level == "read_only" and _REDIRECT_SIGNALS.search(text):
        return CommandGrade("mutating", "redirect to file")

    return CommandGrade(level, best_reason)


# Heads that, even when a command is "mutating", warrant a HIGH bump in the
# permission classifier because their effects publish or persist beyond the
# workspace and are awkward to undo.
_HIGH_BUMP_HEADS = frozenset({
    "sudo",
    "apt", "apt-get", "brew", "yum", "dnf", "pacman",
    "npm", "yarn", "pnpm",
    "pip", "pip3", "pipx", "uv",
    "cargo", "gem",
})


def _classify_token_for_high_bump(tokens: list[str]) -> bool:
    """Return True when this stage should bump 'mutating' to HIGH risk."""
    i = 0
    while i < len(tokens) and "=" in tokens[i] and tokens[i].split("=")[0].isidentifier():
        i += 1
    if i >= len(tokens):
        return False
    head = tokens[i]
    rest = tokens[i + 1:]
    if head == "sudo":
        return True
    if head in _HIGH_BUMP_HEADS:
        # ``pip list``, ``npm ls`` etc. are read-only and never reach this
        # point (handled earlier as read_only). Any *other* subcommand of an
        # installer head is treated as side-effect-publishing.
        return not (
            rest and rest[0] in {"--version", "-V", "--help", "-h", "version"}
        )
    if head == "git":
        if not rest:
            return False
        sub = rest[0]
        if sub == "push":
            # plain ``git push`` publishes; ``git push --force`` is already
            # destructive (handled by _DESTRUCTIVE_PATTERNS).
            return True
    return False


def classify_for_permission(arguments: dict[str, Any]) -> ClassificationResult:
    """Bridge ``classify_command`` into the permission classifier's contract.

    Mapping:

    * ``read_only``  → ``RiskLevel.LOW``
    * ``mutating``   → ``RiskLevel.MEDIUM`` by default; bumped to ``HIGH``
      when any pipeline stage runs ``sudo``, ``git push`` (no ``--force``),
      or a package installer (``npm install``, ``pip install``, ``brew``,
      ``apt-get``, ``cargo``, ``yarn``, ``pnpm``, ``apt``, ``pipx``, ``uv``,
      ``gem``, ``yum``, ``dnf``, ``pacman``).
    * ``destructive`` → ``RiskLevel.DESTRUCTIVE``

    Imports the permission contracts lazily so this module stays usable in
    contexts that don't pull the agent.control package.
    """
    from magi_plugin_sdk.permissions import ClassificationResult, RiskSignal
    from magi_plugin_sdk.permissions import RiskLevel as PermissionRiskLevel

    command = ""
    for key in ("command", "cmd", "script", "input"):
        value = arguments.get(key)
        if isinstance(value, str):
            command = value
            break

    if not command.strip():
        return ClassificationResult(
            level=PermissionRiskLevel.LOW,
            signals=[RiskSignal(key="empty_command", description="empty command")],
            preview=None,
        )

    grade = classify_command(command)
    preview = command.strip().splitlines()[0][:200] if command.strip() else None
    signals = [RiskSignal(key=f"shell_{grade.level}", description=grade.reason)]

    if grade.level == "read_only":
        return ClassificationResult(
            level=PermissionRiskLevel.LOW, signals=signals, preview=preview,
        )
    if grade.level == "destructive":
        return ClassificationResult(
            level=PermissionRiskLevel.DESTRUCTIVE, signals=signals, preview=preview,
        )

    bumped = False
    for part in _split_pipeline(command):
        try:
            tokens = shlex.split(part, posix=True)
        except ValueError:
            tokens = part.split()
        if _classify_token_for_high_bump(tokens):
            bumped = True
            signals.append(RiskSignal(
                key="shell_publishes_or_installs",
                description=f"stage runs an installer / sudo / git push: {part.strip()[:80]}",
            ))
            break
    return ClassificationResult(
        level=PermissionRiskLevel.HIGH if bumped else PermissionRiskLevel.MEDIUM,
        signals=signals,
        preview=preview,
    )


__all__ = ["CommandGrade", "RiskLevel", "classify_command", "classify_for_permission"]
