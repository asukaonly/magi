"""Frontmost application reader for macOS."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys

from .types import FrontmostAppSample

_BUNDLE_ID_RE = re.compile(r'"CFBundleIdentifier"="([^"]+)"')
_DISPLAY_NAME_RE = re.compile(r'"LSDisplayName"="([^"]+)"')


class FrontmostAppReader:
    """Read the current frontmost app via ``lsappinfo``."""

    def is_available(self) -> bool:
        return sys.platform == "darwin" and shutil.which("lsappinfo") is not None

    def read_frontmost_app(self) -> FrontmostAppSample | None:
        """Return the current frontmost app, if it can be resolved."""
        if not self.is_available():
            return None

        try:
            front = subprocess.check_output(
                ["lsappinfo", "front"],
                text=True,
            ).strip()
            if not front:
                return None

            info = subprocess.check_output(
                ["lsappinfo", "info", "-only", "bundleID,name", front],
                text=True,
            )
        except Exception:
            return None

        bundle_match = _BUNDLE_ID_RE.search(info)
        if bundle_match is None:
            return None
        name_match = _DISPLAY_NAME_RE.search(info)
        bundle_id = bundle_match.group(1)
        app_name = name_match.group(1) if name_match is not None else bundle_id
        return FrontmostAppSample(bundle_id=bundle_id, app_name=app_name)
