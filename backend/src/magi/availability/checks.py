"""Check-kind implementations for AvailabilityResolver.

Each check returns a (ok, detail) tuple — ok is True if the requirement
passes on the current device; detail is a human-readable explanation when ok=False.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

from magi_plugin_sdk.contracts import (
    LocalRequirementExecutableInPath,
    LocalRequirementFileExists,
)


def _current_platform_key() -> str:
    """Return the platform key used in descriptor maps.

    Aligns with sys.platform values: 'darwin', 'win32', 'linux'.
    """
    if sys.platform == "win32":
        return "win32"
    if sys.platform == "darwin":
        return "darwin"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def _expand_path(raw: str) -> str:
    """Expand ~ and environment variables (both $VAR and %VAR%)."""
    expanded = os.path.expanduser(raw)
    expanded = os.path.expandvars(expanded)
    # Windows-style %VAR% — os.path.expandvars handles this on Windows but
    # not on POSIX. Do it manually so the same path string works cross-platform.
    if "%" in expanded:
        def repl(match: re.Match[str]) -> str:
            return os.environ.get(match.group(1), match.group(0))
        expanded = re.sub(r"%([^%]+)%", repl, expanded)
    return expanded


def check_file_exists(req: LocalRequirementFileExists) -> tuple[bool, str | None]:
    platform = _current_platform_key()
    raw_path = req.paths_per_platform.get(platform)
    if raw_path is None:
        return False, f"no path declared for platform {platform!r}"
    expanded = _expand_path(raw_path)
    if Path(expanded).exists():
        return True, None
    return False, f"path missing: {expanded}"


def check_executable_in_path(
    req: LocalRequirementExecutableInPath,
) -> tuple[bool, str | None]:
    for name in req.names:
        if shutil.which(name) is not None:
            return True, None
    names = ", ".join(req.names)
    return False, f"no executable found for any of: {names}"
