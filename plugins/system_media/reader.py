"""Cross-platform media reader dispatcher."""
from __future__ import annotations

import sys
from typing import Optional

from .models import MediaState


async def get_current_media() -> Optional[MediaState]:
    """Return the current OS media state, or *None* if nothing is playing."""
    if sys.platform == "win32":
        from ._windows import get_current_media as _read
    elif sys.platform == "darwin":
        from ._macos import get_current_media as _read
    else:
        return None
    return await _read()
