"""Type handlers for extracting core content from different memory types."""
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class TypeHandler(ABC):
    """Base handler for extracting core content from different memory types."""

    @property
    @abstractmethod
    def supported_types(self) -> List[str]:
        """Return list of memory types this handler supports."""
        pass

    @abstractmethod
    def extract(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Extract core content from raw memory data."""
        pass


class TextHandler(TypeHandler):
    """Handler for text-based memories (chat, notes, etc.)."""

    @property
    def supported_types(self) -> List[str]:
        return ["chat", "note", "document"]

    def extract(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "content": raw_data.get("content", ""),
            "summary": raw_data.get("summary"),
        }


class BrowserHistoryHandler(TypeHandler):
    """Handler for browser history entries."""

    @property
    def supported_types(self) -> List[str]:
        return ["browser_history"]

    def extract(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        page_content = raw_data.get("page_content", "")
        snippet = page_content[:500] if page_content else None

        return {
            "url": raw_data.get("url"),
            "title": raw_data.get("title"),
            "visit_time": raw_data.get("visit_time"),
            "snippet": snippet,
        }


class ImageHandler(TypeHandler):
    """Handler for image memories."""

    @property
    def supported_types(self) -> List[str]:
        return ["image", "screenshot"]

    def extract(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "path": raw_data.get("path"),
            "summary": raw_data.get("ai_description"),
            "exif": raw_data.get("exif", {}),
            "dimensions": raw_data.get("dimensions"),
        }


class AudioHandler(TypeHandler):
    """Handler for audio memories."""

    @property
    def supported_types(self) -> List[str]:
        return ["audio", "voice_note"]

    def extract(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "path": raw_data.get("path"),
            "transcript": raw_data.get("transcript"),
            "duration": raw_data.get("duration"),
        }


class TypeHandlerRegistry:
    """Registry for all type handlers."""

    def __init__(self):
        self._handlers: Dict[str, TypeHandler] = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        """Register default handlers."""
        default_handlers = [
            TextHandler(),
            BrowserHistoryHandler(),
            ImageHandler(),
            AudioHandler(),
        ]
        for handler in default_handlers:
            self.register(handler)

    def get_handler(self, memory_type: str) -> Optional[TypeHandler]:
        """Get handler for a specific memory type."""
        return self._handlers.get(memory_type)

    def register(self, handler: TypeHandler) -> None:
        """Register a handler for its supported types."""
        for type_name in handler.supported_types:
            self._handlers[type_name] = handler
