"""Fail-closed native confinement for external Python workers.

macOS Seatbelt is the supported restricted backend. Other platforms reject
restricted_process until a tested native backend is available. Process isolation
alone is never reported as filesystem or network confinement.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import sys
from typing import Sequence


class ConfinementUnavailable(RuntimeError):
    """Requested operating-system confinement cannot be enforced."""


@dataclass(frozen=True)
class ConfinementPlan:
    command: tuple[str, ...]
    mechanism: str
    filesystem_confined: bool
    network_confined: bool
    description: str


def plan_confinement(
    command: Sequence[str],
    *,
    mode: str,
    read_roots: Sequence[Path],
    state_dir: Path,
    resources_dir: Path,
    platform: str | None = None,
) -> ConfinementPlan:
    platform = platform or sys.platform
    if mode == "trusted_process":
        return ConfinementPlan(
            tuple(command),
            "none",
            False,
            False,
            "Trusted worker has the current user's operating-system authority",
        )
    if mode != "restricted_process":
        raise ConfinementUnavailable("Unknown plugin execution mode")
    sandbox = Path("/usr/bin/sandbox-exec")
    if platform != "darwin" or not sandbox.is_file():
        raise ConfinementUnavailable(f"Restricted plugin execution is unsupported on {platform}")

    def quote(path: str | Path) -> str:
        return json.dumps(str(Path(path).resolve()))

    reads = sorted({str(p.resolve()) for p in read_roots})
    writes = sorted({str(state_dir.resolve()), str(resources_dir.resolve())})
    # Default deny also blocks network, Mach service access and unrelated files.
    # The initial exec is allowed; creating additional processes is denied.
    executable = Path(shutil.which(command[0]) or command[0]).resolve()
    profile = "\n".join(
        [
            "(version 1)",
            "(deny default)",
            f"(allow process-exec (literal {quote(executable)}))",
            "(allow signal (target self))",
            "(allow sysctl-read)",
            '(allow file-read* (subpath "/System/Library") (subpath "/usr/lib") (literal "/dev/null") (literal "/dev/urandom") (literal "/dev/random") (literal "/private/etc/localtime"))',
            '(allow file-write* (literal "/dev/null"))',
            "(allow file-read-metadata)",
            '(allow file-read-data (literal "/"))',
            *(f"(allow file-read* (subpath {quote(p)}))" for p in reads),
            *(f"(allow file-read* file-write* (subpath {quote(p)}))" for p in writes),
        ]
    )
    return ConfinementPlan(
        (str(sandbox), "-p", profile, *command),
        "macos-seatbelt",
        True,
        True,
        "Seatbelt limits file access to worker runtime and connection directories; direct network is denied",
    )
