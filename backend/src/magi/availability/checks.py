"""Check-kind implementations for AvailabilityResolver.

Each check returns a (ok, detail) tuple — ok is True if the requirement
passes on the current device; detail is a human-readable explanation when ok=False.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from magi_plugin_sdk.contracts import (
    LocalRequirementAppInstalled,
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


_LINUX_DESKTOP_DIRS = [
    Path("/usr/share/applications"),
    Path("/usr/local/share/applications"),
    Path.home() / ".local/share/applications",
]

try:
    import winreg  # noqa: F401 — present only on Windows

    _WINDOWS_REGISTRY_AVAILABLE = sys.platform == "win32"
except ImportError:
    _WINDOWS_REGISTRY_AVAILABLE = False


def check_app_installed(
    req: LocalRequirementAppInstalled,
) -> tuple[bool, str | None]:
    platform = _current_platform_key()
    identifier = req.identifier_per_platform.get(platform)
    if identifier is None:
        return False, f"no identifier declared for platform {platform!r}"

    if platform == "darwin":
        return _check_macos_app(identifier)
    if platform == "linux":
        return _check_linux_app(identifier)
    if platform == "win32":
        return _check_windows_app(identifier)
    return False, f"app_installed check not supported on {platform}"


def _check_macos_app(bundle_id: str) -> tuple[bool, str | None]:
    try:
        result = subprocess.run(
            ["mdfind", f"kMDItemCFBundleIdentifier == '{bundle_id}'"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError) as exc:
        return False, f"mdfind failed: {exc}"
    if result.returncode != 0:
        return False, f"mdfind exit {result.returncode}"
    if result.stdout.strip():
        return True, None
    return False, f"bundle id not installed: {bundle_id}"


def _check_linux_app(desktop_basename: str) -> tuple[bool, str | None]:
    # Match desktop_basename against any installed .desktop file's stem.
    for directory in _LINUX_DESKTOP_DIRS:
        if not directory.exists():
            continue
        candidate = directory / f"{desktop_basename}.desktop"
        if candidate.exists():
            return True, None
    return False, f"no .desktop file matching {desktop_basename}"


def _check_windows_app(display_name_fragment: str) -> tuple[bool, str | None]:
    if not _WINDOWS_REGISTRY_AVAILABLE:
        return False, "windows app detection not yet implemented"
    # Plan 1 ships a stub. Plan 4 (or a follow-on) implements full winreg scan.
    # When you implement: scan HKLM\Software\Microsoft\Windows\CurrentVersion\Uninstall
    # plus the WOW6432Node sibling, read DisplayName values, match fragment case-insensitive.
    return False, "windows app detection not yet implemented"
