"""Current personality selection state access."""

from __future__ import annotations

from ..core.logger import get_logger
from ..utils.runtime import get_runtime_paths

logger = get_logger(__name__)

DEFAULT_PERSONALITY = "default"
CURRENT_PERSONALITY_FILE = "current"


def get_current_personality() -> str:
    """Get current personality name from runtime state."""

    runtime_paths = get_runtime_paths()
    current_file = runtime_paths.personalities_dir / CURRENT_PERSONALITY_FILE
    if current_file.exists():
        return current_file.read_text().strip()
    return DEFAULT_PERSONALITY


def set_current_personality(name: str) -> bool:
    """Set current personality name in runtime state."""

    runtime_paths = get_runtime_paths()
    current_file = runtime_paths.personalities_dir / CURRENT_PERSONALITY_FILE
    try:
        current_file.write_text(name)
        return True
    except Exception as exc:
        logger.error("Failed to set current personality: %s", exc)
        return False
