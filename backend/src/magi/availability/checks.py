"""Check-kind implementations for AvailabilityResolver.

Each check returns a (ok, detail) tuple — ok is True if the requirement
passes on the current device; detail is a human-readable explanation when ok=False.
"""

from __future__ import annotations

import os
import ntpath
import re
import shutil
import subprocess
import sys
from pathlib import Path, PureWindowsPath

from magi_plugin_sdk.contracts import (
    LocalRequirementAppInstalled,
    LocalRequirementExecutableInPath,
    LocalRequirementFileExists,
)
from magi_plugin_sdk.subprocess import hidden_process_kwargs


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


_EXECUTABLE_BASENAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_MACOS_BUNDLE_ID_RE = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9-]{0,62}(?:\.[A-Za-z0-9][A-Za-z0-9-]{0,62})+"
)
_LINUX_DESKTOP_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_WINDOWS_URI_RE = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*:")
_WINDOWS_RESERVED_COMPONENT_RE = re.compile(
    r"(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?",
    re.IGNORECASE,
)
_WINDOWS_LOCAL_DRIVE_TYPES = {2, 3, 5, 6}


def _windows_drive_is_local(drive: str) -> bool:
    """Return whether a Windows drive is backed by a local device."""

    if sys.platform != "win32":
        return True
    try:
        import ctypes

        drive_type = ctypes.windll.kernel32.GetDriveTypeW(f"{drive}\\")
    except (AttributeError, OSError):
        return False
    return drive_type in _WINDOWS_LOCAL_DRIVE_TYPES


def _validate_windows_local_path(path: str) -> str | None:
    """Reject path forms that can touch devices or remote hosts."""

    if not path or len(path) > 4096 or "\x00" in path:
        return "invalid Windows path"
    normalized = path.replace("/", "\\")
    lowered = normalized.lower()
    if lowered.startswith(("\\\\", "\\??\\", "\\\\?\\", "\\\\.\\")):
        return "Windows network and device paths are not allowed"
    if _WINDOWS_URI_RE.match(normalized):
        drive, _tail = ntpath.splitdrive(normalized)
        if not re.fullmatch(r"[A-Za-z]:", drive):
            return "Windows URI and non-local paths are not allowed"
    if not ntpath.isabs(normalized):
        return "Windows availability paths must be absolute and local"
    drive, _tail = ntpath.splitdrive(normalized)
    if not re.fullmatch(r"[A-Za-z]:", drive) or not _windows_drive_is_local(drive):
        return "Windows availability paths must use a local drive"
    for part in PureWindowsPath(normalized).parts[1:]:
        component = part.rstrip(" .")
        if ":" in component or _WINDOWS_RESERVED_COMPONENT_RE.fullmatch(component):
            return "Windows device path components are not allowed"
    return None


def check_file_exists(req: LocalRequirementFileExists) -> tuple[bool, str | None]:
    platform = _current_platform_key()
    raw_path = req.paths_per_platform.get(platform)
    if raw_path is None:
        return False, f"no path declared for platform {platform!r}"
    expanded = _expand_path(raw_path)
    if platform == "win32" and (rejection_reason := _validate_windows_local_path(expanded)):
        return False, rejection_reason
    if Path(expanded).exists():
        return True, None
    return False, f"path missing: {expanded}"


def check_executable_in_path(
    req: LocalRequirementExecutableInPath,
) -> tuple[bool, str | None]:
    valid_names = [
        name
        for name in req.names
        if isinstance(name, str) and _EXECUTABLE_BASENAME_RE.fullmatch(name)
    ]
    if not valid_names:
        return False, "no valid executable basename declared"
    for name in valid_names:
        if shutil.which(name) is not None:
            return True, None
    names = ", ".join(valid_names)
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
        if len(identifier) > 255 or not _MACOS_BUNDLE_ID_RE.fullmatch(identifier):
            return False, "invalid macOS bundle identifier"
        return _check_macos_app(identifier)
    if platform == "linux":
        if not _LINUX_DESKTOP_ID_RE.fullmatch(identifier):
            return False, "invalid Linux desktop identifier"
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
            **hidden_process_kwargs(),
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
