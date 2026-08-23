"""Dialect-aware Bash and PowerShell command risk classifiers.

Three tiers:

* ``read_only`` - observed read-only utilities and read-only ``git`` subcommands.
* ``mutating``  - anything else that we can't prove is safe (default).
* ``destructive`` - known irreversible / wide-blast-radius patterns.

The classifiers are intentionally lexical. They do NOT parse complete shell
grammars. Their purpose is to prevent typical agent mistakes and to provide a
conservative permission default. They are not a substitute for process
isolation and must not be treated as a security boundary.
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


# ---------------------------------------------------------------------------
# PowerShell dialect
# ---------------------------------------------------------------------------


_POWERSHELL_ALIASES: dict[str, str] = {
    # Read-only aliases.
    "cat": "get-content",
    "dir": "get-childitem",
    "echo": "write-output",
    "gal": "get-alias",
    "gc": "get-content",
    "gci": "get-childitem",
    "gcm": "get-command",
    "gi": "get-item",
    "gl": "get-location",
    "gp": "get-itemproperty",
    "gps": "get-process",
    "gsv": "get-service",
    "ls": "get-childitem",
    "ps": "get-process",
    "pwd": "get-location",
    "select": "select-object",
    "sort": "sort-object",
    "type": "get-content",
    "write": "write-output",
    # File-system mutators.
    "ac": "add-content",
    "clc": "clear-content",
    "copy": "copy-item",
    "cp": "copy-item",
    "del": "remove-item",
    "erase": "remove-item",
    "mi": "move-item",
    "move": "move-item",
    "mv": "move-item",
    "ni": "new-item",
    "rd": "remove-item",
    "ren": "rename-item",
    "ri": "remove-item",
    "rm": "remove-item",
    "rmdir": "remove-item",
    "sc": "set-content",
    "si": "set-item",
}

_POWERSHELL_READ_ONLY_HEADS = frozenset({
    "convertfrom-json",
    "convertto-json",
    "format-list",
    "format-table",
    "get-acl",
    "get-alias",
    "get-childitem",
    "get-ciminstance",
    "get-command",
    "get-content",
    "get-date",
    "get-filehash",
    "get-help",
    "get-item",
    "get-itemproperty",
    "get-location",
    "get-member",
    "get-process",
    "get-service",
    "get-wmiobject",
    "join-path",
    "out-string",
    "resolve-path",
    "select-object",
    "select-string",
    "split-path",
    "sort-object",
    "test-path",
    "write-host",
    "write-output",
})

_POWERSHELL_SCOPED_MUTATING_HEADS = frozenset({
    "add-content",
    "clear-content",
    "copy-item",
    "move-item",
    "new-item",
    "out-file",
    "remove-item",
    "rename-item",
    "set-content",
    "set-location",
})

_POWERSHELL_DESTRUCTIVE_HEADS = frozenset({
    "clear-disk",
    "clear-recyclebin",
    "format-volume",
    "initialize-disk",
    "remove-partition",
    "restart-computer",
    "stop-computer",
})


@dataclass(frozen=True)
class _PowerShellAnalysis:
    grade: CommandGrade
    permission_level: Literal["low", "medium", "high", "destructive"]
    removes_root: bool = False


_POWERSHELL_TOKEN = re.compile(
    r'''"(?:`.|[^"])*"|'(?:''|[^'])*'|&&|\|\||[|;&\r\n]|(?:`[\s\S]|[^\s|;&])+'''
)
_POWERSHELL_SEPARATORS = frozenset({"|", ";", "&&", "||", "\r", "\n"})


def _powershell_stages(command: str) -> list[list[str]]:
    """Tokenize command stages without treating quoted separators as syntax."""
    stages: list[list[str]] = []
    current: list[str] = []
    for token in _POWERSHELL_TOKEN.findall(command):
        if token in _POWERSHELL_SEPARATORS or (token == "&" and current):
            if current:
                stages.append(current)
                current = []
            continue
        current.append(token)
    if current:
        stages.append(current)
    return stages


def _powershell_stage_is_opaque(tokens: list[str]) -> bool:
    for token in tokens:
        quoted = len(token) >= 2 and token[0] == token[-1] and token[0] in {"'", '"'}
        if not quoted and any(marker in token for marker in ("`", "{", "}", "(", ")", ">", "<")):
            return True
    return False


def _unescape_powershell_token(token: str) -> str:
    return re.sub(r"`([\s\S])", r"\1", token)


def _canonical_powershell_head(head: str) -> str:
    probe = _unescape_powershell_token(head.strip().strip("'\"")).casefold()
    if "\\" in probe and ":" not in probe and not probe.startswith((".", "\\")):
        probe = probe.rsplit("\\", 1)[-1]
    return _POWERSHELL_ALIASES.get(probe, probe)


def _powershell_invocation(tokens: list[str]) -> tuple[str, list[str], bool]:
    if not tokens:
        return "", [], False
    opaque = False
    index = 0
    if tokens[index] in {"&", "."}:
        opaque = True
        index += 1
    if index + 2 < len(tokens) and tokens[index].startswith("$") and tokens[index + 1] == "=":
        opaque = True
        index += 2
    if index >= len(tokens):
        return "", [], True
    return _canonical_powershell_head(tokens[index]), tokens[index + 1 :], opaque


def _parameter_switch_enabled(token: str, parameter: str) -> bool:
    token = _unescape_powershell_token(token)
    if not token.startswith("-") or token.startswith("--"):
        return False
    name, separator, value = token[1:].partition(":")
    if not name or not parameter.casefold().startswith(name.casefold()):
        return False
    if separator and value.casefold() in {"$false", "false", "0"}:
        return False
    return True


def _whatif_enabled(token: str) -> bool:
    token = _unescape_powershell_token(token)
    if not token.startswith("-") or token.startswith("--"):
        return False
    name, separator, value = token[1:].partition(":")
    if not name or not "whatif".startswith(name.casefold()):
        return False
    return not separator or value.casefold() in {"$true", "true", "1"}


def _is_powershell_root_target(token: str) -> bool:
    raw_target = token.strip().strip(",")
    single_quoted = (
        len(raw_target) >= 2
        and raw_target.startswith("'")
        and raw_target.endswith("'")
    )
    target = raw_target.strip("'").strip('"')
    if single_quoted and target.startswith("$"):
        return False
    if target.casefold().startswith("filesystem::"):
        target = target[len("filesystem::") :]
    target = target.replace("/", "\\")
    lowered = target.casefold()
    if target == "\\":
        return True
    if re.fullmatch(r"[a-z]:\\(?:[?*][^\\]*)?", target, re.IGNORECASE):
        return True
    if re.fullmatch(r"~\\?(?:[?*][^\\]*)?", target):
        return True
    if re.fullmatch(
        r"(?:\$home|\$\{home\}|\$env:(?:userprofile|systemdrive))"
        r"\\?(?:[?*][^\\]*)?",
        lowered,
    ):
        return True
    return bool(
        re.fullmatch(r"\\\\[^\\]+\\[^\\]+(?:\\(?:[?*][^\\]*)?)?", target)
    )


def _is_protected_windows_path(token: str) -> bool:
    target = token.strip().strip(",").strip("'\"").replace("/", "\\").casefold()
    return bool(
        re.match(r"^(?:[a-z]:\\windows|\$env:(?:systemroot|windir))\\system32(?:\\|$)", target)
    )


def _has_dynamic_powershell_argument(arguments: list[str]) -> bool:
    """Return whether a mutation depends on runtime-computed arguments."""
    for argument in arguments:
        token = _unescape_powershell_token(argument).strip().strip("'\"")
        if token.startswith(("$", "@")) or "$(" in token:
            return True
    return False


def _remove_item_analysis(arguments: list[str]) -> tuple[bool, bool]:
    if any(_whatif_enabled(arg) for arg in arguments):
        return False, False
    combined_flags = {
        arg[1:].casefold()
        for arg in map(_unescape_powershell_token, arguments)
        if re.fullmatch(r"-[rf]+", arg, re.IGNORECASE)
    }
    recursive = any(
        _parameter_switch_enabled(arg, "recurse") for arg in arguments
    ) or any("r" in flags and "f" in flags for flags in combined_flags)
    forced = any(
        _parameter_switch_enabled(arg, "force") for arg in arguments
    ) or any("r" in flags and "f" in flags for flags in combined_flags)
    root_target = any(_is_powershell_root_target(arg) for arg in arguments)
    return recursive and forced, recursive and root_target


def _analyze_powershell(command: str) -> _PowerShellAnalysis:
    text = (command or "").strip()
    if not text:
        return _PowerShellAnalysis(
            grade=CommandGrade("mutating", "empty command (defensive default)"),
            permission_level="low",
        )

    level: RiskLevel = "read_only"
    permission_level: Literal["low", "medium", "high", "destructive"] = "low"
    best_reason = "all PowerShell stages are proven read-only"
    removes_root = False
    destructive_reason: str | None = None
    for tokens in _powershell_stages(text):
        lexical_opaque = _powershell_stage_is_opaque(tokens)
        head, arguments, invocation_opaque = _powershell_invocation(tokens)
        opaque = lexical_opaque or invocation_opaque
        if not head:
            level = _max_level(level, "mutating")
            permission_level = "high"
            best_reason = "opaque PowerShell stage"
            continue

        if head == "remove-item":
            broad_removal, root_removal = _remove_item_analysis(arguments)
            removes_root = removes_root or root_removal
            if broad_removal or root_removal:
                destructive_reason = (
                    "Remove-Item recursively targets a filesystem root"
                    if root_removal
                    else "Remove-Item -Recurse -Force"
                )
                continue

        if head in _POWERSHELL_DESTRUCTIVE_HEADS:
            destructive_reason = f"PowerShell {head}"
            continue

        if opaque:
            level = _max_level(level, "mutating")
            permission_level = "high"
            best_reason = f"opaque PowerShell stage invoking {head!r}"
        elif head in _POWERSHELL_READ_ONLY_HEADS:
            continue
        elif head in _POWERSHELL_SCOPED_MUTATING_HEADS:
            level = _max_level(level, "mutating")
            if _has_dynamic_powershell_argument(arguments):
                permission_level = "high"
                best_reason = f"PowerShell {head} uses dynamic mutation arguments"
            elif any(_is_protected_windows_path(arg) for arg in arguments):
                permission_level = "high"
                best_reason = f"PowerShell {head} targets a protected system path"
            elif permission_level == "low":
                permission_level = "medium"
                best_reason = f"PowerShell {head} mutates local state"
        else:
            level = _max_level(level, "mutating")
            permission_level = "high"
            best_reason = f"unknown PowerShell command {head!r}"

    if destructive_reason is not None:
        return _PowerShellAnalysis(
            grade=CommandGrade("destructive", destructive_reason),
            permission_level="destructive",
            removes_root=removes_root,
        )
    return _PowerShellAnalysis(
        grade=CommandGrade(level, best_reason),
        permission_level=permission_level,
        removes_root=removes_root,
    )


def classify_powershell_command(command: str) -> CommandGrade:
    """Classify a PowerShell command for the tool's destructive guard."""
    return _analyze_powershell(command).grade


def powershell_removes_root(command: str) -> bool:
    """Return whether a literal PowerShell removal targets a filesystem root."""
    return _analyze_powershell(command).removes_root


def classify_powershell_for_permission(
    arguments: dict[str, Any],
) -> ClassificationResult:
    """Classify PowerShell conservatively for permission prompting.

    Only explicitly known read-only cmdlets are ``LOW``. Known scoped file
    mutations are ``MEDIUM``. Unknown, dynamic, installer, persistence, and
    system-control commands are ``HIGH``. Obvious destructive commands remain
    ``DESTRUCTIVE``.
    """
    from magi_plugin_sdk.permissions import ClassificationResult, RiskSignal
    from magi_plugin_sdk.permissions import RiskLevel as PermissionRiskLevel

    command = ""
    for key in ("command", "cmd", "script", "input"):
        value = arguments.get(key)
        if isinstance(value, str):
            command = value
            break

    analysis = _analyze_powershell(command)
    preview = command.strip().splitlines()[0][:200] if command.strip() else None
    signals = [
        RiskSignal(
            key=f"powershell_{analysis.permission_level}",
            description=analysis.grade.reason,
        )
    ]
    permission_levels = {
        "low": PermissionRiskLevel.LOW,
        "medium": PermissionRiskLevel.MEDIUM,
        "high": PermissionRiskLevel.HIGH,
        "destructive": PermissionRiskLevel.DESTRUCTIVE,
    }
    return ClassificationResult(
        level=permission_levels[analysis.permission_level],
        signals=signals,
        preview=preview,
    )


__all__ = [
    "CommandGrade",
    "RiskLevel",
    "classify_command",
    "classify_for_permission",
    "classify_powershell_command",
    "classify_powershell_for_permission",
    "powershell_removes_root",
]
