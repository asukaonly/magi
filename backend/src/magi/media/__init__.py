"""Media layer: source registry, period selector, asset resolver.

This package lifts media-asset handling out of any single plugin so that
photo-library, chat attachments, and future sources (screen capture, etc.)
contribute through one registration path. See:
    docs/superpowers/specs/2026-05-19-timeline-immersive-redesign-design.md
    docs/unified-asset-resolver-architecture.md (forward-compatible)
"""

from .source_registry import MediaSource, MediaSourceRegistry
from .selector import MediaSelector

__all__ = ["MediaSource", "MediaSourceRegistry", "MediaSelector"]
