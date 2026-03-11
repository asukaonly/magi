# Memory Query Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a memory retrieval system that enables querying user memories across L1-L5 layers with intelligent routing, privacy controls, and proactive context injection.

**Architecture:** MemoryQueryTool (tools layer) delegates to MemoryQueryService (memory/query module), which orchestrates IntentRouter for layer selection, PrivacyGuard for access control, and TypeHandler for content extraction. ContextDecider is extended to proactively suggest memory retrieval.

**Tech Stack:** Python 3.10+, Pydantic v2, aiosqlite, asyncio

---

## File Structure

```
backend/src/magi/
├── memory/
│   └── query/                       # NEW MODULE
│       ├── __init__.py              # Module exports
│       ├── models.py                # Request/Result dataclasses
│       ├── service.py               # MemoryQueryService
│       ├── router.py                # IntentRouter, RoutingPlan
│       ├── privacy.py               # PrivacyGuard, SensitivityLevel
│       └── handlers.py              # TypeHandler, TypeHandlerRegistry
│
├── tools/
│   └── memory_query.py              # NEW: MemoryQueryTool
│
└── tools/context_decider.py         # MODIFY: Add memory guidance

backend/tests/
└── memory/
    └── test_memory_query.py         # NEW: Unit tests
```

---

## Chunk 1: Core Models and Type Handlers

### Task 1.1: Create query module models

**Files:**
- Create: `backend/src/magi/memory/query/__init__.py`
- Create: `backend/src/magi/memory/query/models.py`
- Create: `backend/tests/memory/test_memory_query.py`

- [ ] **Step 1: Write the failing test for MemoryQueryRequest**

```python
# backend/tests/memory/test_memory_query.py
"""Unit tests for memory query module."""
import pytest
from datetime import datetime


class TestMemoryQueryRequest:
    """Tests for MemoryQueryRequest model."""

    def test_create_request_with_required_fields(self):
        """Should create request with query and time_range."""
        from magi.memory.query.models import MemoryQueryRequest

        request = MemoryQueryRequest(
            query="what did I browse yesterday",
            time_range={"relative": "1d"}
        )

        assert request.query == "what did I browse yesterday"
        assert request.time_range == {"relative": "1d"}
        assert request.data_types is None
        assert request.limit is None

    def test_create_request_with_all_fields(self):
        """Should create request with all optional fields."""
        from magi.memory.query.models import MemoryQueryRequest

        request = MemoryQueryRequest(
            query="find my notes",
            time_range={"start": 1700000000.0, "end": 1700100000.0},
            data_types=["note", "chat"],
            limit=10
        )

        assert request.query == "find my notes"
        assert request.data_types == ["note", "chat"]
        assert request.limit == 10


class TestMemoryQueryResult:
    """Tests for MemoryQueryResult model."""

    def test_success_result(self):
        """Should create successful result with data."""
        from magi.memory.query.models import MemoryQueryResult

        result = MemoryQueryResult(
            status="success",
            data=[{"id": "1", "type": "browser_history", "content": {}}],
            query_meta={"layer": "L1", "total_count": 1}
        )

        assert result.status == "success"
        assert len(result.data) == 1
        assert result.confirm_prompt is None

    def test_confirm_required_result(self):
        """Should create result requiring user confirmation."""
        from magi.memory.query.models import MemoryQueryResult

        result = MemoryQueryResult(
            status="confirm_required",
            confirm_prompt="Please specify a time range for the search."
        )

        assert result.status == "confirm_required"
        assert result.confirm_prompt is not None
        assert result.data is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/memory/test_memory_query.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'magi.memory.query'"

- [ ] **Step 3: Create module directory structure**

```bash
mkdir -p backend/src/magi/memory/query
mkdir -p backend/tests/memory
```

- [ ] **Step 4: Implement models.py**

```python
# backend/src/magi/memory/query/models.py
"""Data models for memory query requests and results."""
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class MemoryQueryRequest:
    """Request to query memories across L1-L5 layers."""

    query: str
    time_range: Dict[str, Any]
    data_types: Optional[List[str]] = None
    limit: Optional[int] = None


@dataclass
class MemoryQueryResult:
    """Result from memory query execution."""

    status: str  # "success" | "confirm_required" | "empty" | "denied"
    confirm_prompt: Optional[str] = None
    data: Optional[List[Dict[str, Any]]] = None
    query_meta: Optional[Dict[str, Any]] = None
```

- [ ] **Step 5: Create __init__.py with exports**

```python
# backend/src/magi/memory/query/__init__.py
"""Memory query module for retrieving memories across L1-L5 layers."""
from .models import MemoryQueryRequest, MemoryQueryResult
from .handlers import TypeHandler, TypeHandlerRegistry
from .privacy import PrivacyGuard, SensitivityLevel, PrivacyCheckResult
from .router import IntentRouter, RoutingPlan
from .service import MemoryQueryService

__all__ = [
    "MemoryQueryRequest",
    "MemoryQueryResult",
    "TypeHandler",
    "TypeHandlerRegistry",
    "PrivacyGuard",
    "SensitivityLevel",
    "PrivacyCheckResult",
    "IntentRouter",
    "RoutingPlan",
    "MemoryQueryService",
]
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd backend && pytest tests/memory/test_memory_query.py::TestMemoryQueryRequest -v && pytest tests/memory/test_memory_query.py::TestMemoryQueryResult -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add backend/src/magi/memory/query/__init__.py backend/src/magi/memory/query/models.py backend/tests/memory/test_memory_query.py
git commit -m "feat(memory): add memory query request/result models"
```

---

### Task 1.2: Implement TypeHandler base and registry

**Files:**
- Create: `backend/src/magi/memory/query/handlers.py`
- Modify: `backend/tests/memory/test_memory_query.py`

- [ ] **Step 1: Write the failing tests for TypeHandler**

```python
# Add to backend/tests/memory/test_memory_query.py

class TestTypeHandler:
    """Tests for TypeHandler base class and registry."""

    def test_text_handler_extract(self):
        """Should extract content from text-based memories."""
        from magi.memory.query.handlers import TextHandler

        handler = TextHandler()
        result = handler.extract({
            "content": "Hello world",
            "summary": "A greeting"
        })

        assert result["content"] == "Hello world"
        assert result["summary"] == "A greeting"

    def test_browser_history_handler_extract(self):
        """Should extract core fields from browser history."""
        from magi.memory.query.handlers import BrowserHistoryHandler

        handler = BrowserHistoryHandler()
        result = handler.extract({
            "url": "https://example.com",
            "title": "Example Site",
            "visit_time": 1700000000.0,
            "page_content": "A" * 1000  # Long content
        })

        assert result["url"] == "https://example.com"
        assert result["title"] == "Example Site"
        assert len(result["snippet"]) <= 500  # Snippet is truncated

    def test_type_handler_registry_get_handler(self):
        """Should return correct handler for memory type."""
        from magi.memory.query.handlers import TypeHandlerRegistry

        registry = TypeHandlerRegistry()

        handler = registry.get_handler("browser_history")
        assert handler is not None
        assert "browser_history" in handler.supported_types

        handler = registry.get_handler("chat")
        assert handler is not None
        assert "chat" in handler.supported_types

    def test_type_handler_registry_unknown_type(self):
        """Should return None for unknown memory type."""
        from magi.memory.query.handlers import TypeHandlerRegistry

        registry = TypeHandlerRegistry()
        handler = registry.get_handler("unknown_type")
        assert handler is None

    def test_type_handler_registry_custom_handler(self):
        """Should register and retrieve custom handler."""
        from magi.memory.query.handlers import TypeHandler, TypeHandlerRegistry

        class CustomHandler(TypeHandler):
            @property
            def supported_types(self):
                return ["custom"]

            def extract(self, raw_data):
                return {"custom_field": raw_data.get("value")}

        registry = TypeHandlerRegistry()
        registry.register(CustomHandler())

        handler = registry.get_handler("custom")
        assert handler is not None
        result = handler.extract({"value": "test"})
        assert result["custom_field"] == "test"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/memory/test_memory_query.py::TestTypeHandler -v`
Expected: FAIL with "cannot import name 'TypeHandler'"

- [ ] **Step 3: Implement handlers.py**

```python
# backend/src/magi/memory/query/handlers.py
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/memory/test_memory_query.py::TestTypeHandler -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/query/handlers.py backend/tests/memory/test_memory_query.py
git commit -m "feat(memory): add TypeHandler base and registry with default handlers"
```

---

## Chunk 2: Privacy Guard and Intent Router

### Task 2.1: Implement PrivacyGuard

**Files:**
- Create: `backend/src/magi/memory/query/privacy.py`
- Modify: `backend/tests/memory/test_memory_query.py`

- [ ] **Step 1: Write the failing tests for PrivacyGuard**

```python
# Add to backend/tests/memory/test_memory_query.py

class TestPrivacyGuard:
    """Tests for PrivacyGuard sensitivity checks."""

    def test_internal_data_allowed(self):
        """Should allow internal data types without confirmation."""
        from magi.memory.query.privacy import PrivacyGuard, PrivacyCheckResult

        guard = PrivacyGuard()
        result = guard.check(["browser_history", "chat"], {"query": "test"})

        assert result.allowed is True
        assert result.requires_confirmation is False
        assert result.blocked_types == []

    def test_sensitive_data_requires_confirmation(self):
        """Should require confirmation for sensitive data."""
        from magi.memory.query.privacy import PrivacyGuard

        guard = PrivacyGuard()
        result = guard.check(["private_diary"], {"query": "test"})

        assert result.allowed is True
        assert result.requires_confirmation is True
        assert result.confirm_prompt is not None

    def test_restricted_data_denied(self):
        """Should deny access to restricted data types."""
        from magi.memory.query.privacy import PrivacyGuard

        guard = PrivacyGuard()
        result = guard.check(["password"], {"query": "test"})

        assert result.allowed is False
        assert "password" in result.blocked_types

    def test_mixed_data_partial_block(self):
        """Should allow non-sensitive data while blocking restricted."""
        from magi.memory.query.privacy import PrivacyGuard

        guard = PrivacyGuard()
        result = guard.check(["browser_history", "password"], {"query": "test"})

        assert result.allowed is False
        assert "password" in result.blocked_types
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/memory/test_memory_query.py::TestPrivacyGuard -v`
Expected: FAIL with "cannot import name 'PrivacyGuard'"

- [ ] **Step 3: Implement privacy.py**

```python
# backend/src/magi/memory/query/privacy.py
"""Privacy controls for memory retrieval."""
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class SensitivityLevel(Enum):
    """Data sensitivity classification."""
    PUBLIC = "public"           # No confirmation needed
    INTERNAL = "internal"       # General usage, no confirmation
    SENSITIVE = "sensitive"     # Requires user confirmation
    RESTRICTED = "restricted"   # Never retrievable via tool


SENSITIVITY_RULES: Dict[str, SensitivityLevel] = {
    "browser_history": SensitivityLevel.INTERNAL,
    "chat": SensitivityLevel.INTERNAL,
    "note": SensitivityLevel.INTERNAL,
    "document": SensitivityLevel.INTERNAL,
    "password": SensitivityLevel.RESTRICTED,
    "credential": SensitivityLevel.RESTRICTED,
    "private_diary": SensitivityLevel.SENSITIVE,
    "health_data": SensitivityLevel.SENSITIVE,
    "financial": SensitivityLevel.SENSITIVE,
}


@dataclass
class PrivacyCheckResult:
    """Result of privacy sensitivity check."""
    allowed: bool
    requires_confirmation: bool
    confirmation_prompt: Optional[str]
    blocked_types: List[str]


class PrivacyGuard:
    """Guard for memory retrieval privacy controls."""

    def __init__(self, user_preferences: Optional[Dict[str, Any]] = None):
        self.user_preferences = user_preferences or {}
        self._sensitivity_rules = SENSITIVITY_RULES

    def check(
        self,
        data_types: List[str],
        query_context: Dict[str, Any]
    ) -> PrivacyCheckResult:
        """
        Check if memory retrieval is allowed for given data types.

        Args:
            data_types: List of memory types to retrieve
            query_context: Context about the query (who, when, purpose)

        Returns:
            PrivacyCheckResult with permission status and confirmation requirements.
        """
        blocked: List[str] = []
        needs_confirmation: List[str] = []

        for dtype in data_types:
            level = self._sensitivity_rules.get(dtype, SensitivityLevel.INTERNAL)

            if level == SensitivityLevel.RESTRICTED:
                blocked.append(dtype)
            elif level == SensitivityLevel.SENSITIVE:
                needs_confirmation.append(dtype)

        if blocked:
            return PrivacyCheckResult(
                allowed=False,
                requires_confirmation=False,
                confirmation_prompt=None,
                blocked_types=blocked
            )

        if needs_confirmation:
            prompt = self._build_confirmation_prompt(needs_confirmation, query_context)
            return PrivacyCheckResult(
                allowed=True,
                requires_confirmation=True,
                confirmation_prompt=prompt,
                blocked_types=[]
            )

        return PrivacyCheckResult(
            allowed=True,
            requires_confirmation=False,
            confirmation_prompt=None,
            blocked_types=[]
        )

    def _build_confirmation_prompt(
        self,
        sensitive_types: List[str],
        context: Dict[str, Any]
    ) -> str:
        """Build user-friendly confirmation prompt."""
        type_list = ", ".join(sensitive_types)
        return (
            f"This query will access sensitive data types: {type_list}. "
            f"Do you want to proceed with the retrieval?"
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/memory/test_memory_query.py::TestPrivacyGuard -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/query/privacy.py backend/tests/memory/test_memory_query.py
git commit -m "feat(memory): add PrivacyGuard with sensitivity level checks"
```

---

### Task 2.2: Implement IntentRouter

**Files:**
- Create: `backend/src/magi/memory/query/router.py`
- Modify: `backend/tests/memory/test_memory_query.py`

- [ ] **Step 1: Write the failing tests for IntentRouter**

```python
# Add to backend/tests/memory/test_memory_query.py

class TestIntentRouter:
    """Tests for IntentRouter query routing."""

    def test_route_factual_query_to_l1(self):
        """Should route factual queries to L1."""
        from magi.memory.query.router import IntentRouter

        router = IntentRouter()
        plan = router.analyze("What time did I leave yesterday?", {"relative": "1d"})

        assert plan.primary_layer == "L1"
        assert plan.confidence > 0

    def test_route_concept_query_to_l3(self):
        """Should route concept/fuzzy queries to L3."""
        from magi.memory.query.router import IntentRouter

        router = IntentRouter()
        plan = router.analyze("Find my scattered thoughts on AI agents", {"relative": "7d"})

        # L3 is primary for concept retrieval
        assert plan.primary_layer == "L3"

    def test_route_trend_query_to_l4(self):
        """Should route trend/summary queries to L4."""
        from magi.memory.query.router import IntentRouter

        router = IntentRouter()
        plan = router.analyze("Summarize my job search over the past 6 months", {"relative": "180d"})

        assert plan.primary_layer == "L4"

    def test_low_confidence_includes_secondary_layers(self):
        """Should include secondary layers when confidence is low."""
        from magi.memory.query.router import IntentRouter

        router = IntentRouter()
        # Ambiguous query that might need multiple layers
        plan = router.analyze("What was I working on recently?", {"relative": "7d"})

        # Either confidence is low OR secondary layers are populated
        assert plan.confidence < 0.8 or len(plan.secondary_layers) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/memory/test_memory_query.py::TestIntentRouter -v`
Expected: FAIL with "cannot import name 'IntentRouter'"

- [ ] **Step 3: Implement router.py with keyword-based MVP**

```python
# backend/src/magi/memory/query/router.py
"""Intent router for determining which memory layer to query."""
import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class RoutingPlan:
    """Routing plan for memory query execution."""
    primary_layer: str              # Main layer to query (L1-L5)
    secondary_layers: List[str]     # Fallback layers for parallel query
    confidence: float               # Prediction confidence (0-1)
    reasoning: str                  # Why this routing was chosen


# Layer routing keywords
LAYER_KEYWORDS = {
    "L1": ["几点", "哪天", "具体数值", "确切时间", "原始记录", "审计",
           "what time", "exactly", "when did", "specific"],
    "L2": ["关系", "关联", "谁和谁", "归属", "网络", "连接",
           "relation", "connected", "who is", "belongs to"],
    "L3": ["相关", "类似", "关于", "模糊", "零散", "继续之前",
           "related", "similar", "about", "scattered", "continue"],
    "L4": ["总结", "趋势", "变化", "过去", "回顾", "长期",
           "summarize", "trend", "change", "past", "review", "overview"],
    "L5": ["怎么处理", "之前成功", "异常", "失败原因", "方案",
           "how to handle", "worked before", "error", "failed", "approach"],
}


class IntentRouter:
    """Lightweight intent analyzer for memory layer routing."""

    def analyze(self, query: str, time_range: Dict[str, Any]) -> RoutingPlan:
        """
        Analyze query intent and determine routing plan.

        Args:
            query: User's query string
            time_range: Time range for the query

        Returns:
            RoutingPlan with primary/secondary layers and confidence.
        """
        query_lower = query.lower()
        scores: Dict[str, float] = {}

        # Score each layer based on keyword matches
        for layer, keywords in LAYER_KEYWORDS.items():
            score = sum(1.0 for kw in keywords if kw in query_lower)
            scores[layer] = score

        # Find primary layer (highest score)
        if max(scores.values()) == 0:
            # No keyword match, default to L3 (concept retrieval)
            primary = "L3"
            confidence = 0.3
        else:
            primary = max(scores, key=scores.get)
            total_matches = sum(scores.values())
            confidence = min(0.9, scores[primary] / max(total_matches, 1) + 0.4)

        # Determine secondary layers
        secondary: List[str] = []
        sorted_layers = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        for layer, score in sorted_layers[1:3]:  # Take next 2 candidates
            if score > 0:
                secondary.append(layer)

        # Add time-based adjustment
        relative = time_range.get("relative", "")
        if relative and any(x in relative for x in ["30d", "90d", "180d", "1M", "6M"]):
            # Long time range suggests L4 (trends)
            if primary != "L4":
                secondary.append("L4")

        reasoning = f"Primary: {primary} (score: {scores[primary]}), " \
                    f"secondary: {secondary}, confidence: {confidence:.2f}"

        return RoutingPlan(
            primary_layer=primary,
            secondary_layers=secondary,
            confidence=confidence,
            reasoning=reasoning
        )

    async def execute(
        self,
        plan: RoutingPlan,
        request: "MemoryQueryRequest",
        layer_handlers: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        Execute parallel queries across layers based on routing plan.

        Args:
            plan: Routing plan with layer selection
            request: Original query request
            layer_handlers: Dict mapping layer names to query handlers

        Returns:
            Merged and deduplicated results from all layers.
        """
        layers_to_query = [plan.primary_layer]
        if plan.confidence < 0.8:
            layers_to_query.extend(plan.secondary_layers)

        # Remove duplicates while preserving order
        layers_to_query = list(dict.fromkeys(layers_to_query))

        # Execute queries in parallel
        tasks = []
        for layer in layers_to_query:
            handler = layer_handlers.get(layer)
            if handler:
                tasks.append(self._query_layer(layer, request, handler))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Merge and flatten results
        merged: List[Dict[str, Any]] = []
        seen_ids: set = set()

        for result in results:
            if isinstance(result, Exception):
                continue
            if isinstance(result, list):
                for item in result:
                    item_id = item.get("id")
                    if item_id and item_id not in seen_ids:
                        seen_ids.add(item_id)
                        merged.append(item)

        return merged

    async def _query_layer(
        self,
        layer: str,
        request: "MemoryQueryRequest",
        handler: Any
    ) -> List[Dict[str, Any]]:
        """Query a single layer using its handler."""
        try:
            # Handler interface: async def query(request) -> List[Dict]
            if hasattr(handler, 'query'):
                return await handler.query(request)
            return []
        except Exception:
            return []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/memory/test_memory_query.py::TestIntentRouter -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/memory/query/router.py backend/tests/memory/test_memory_query.py
git commit -m "feat(memory): add IntentRouter with keyword-based layer routing"
```

---

## Chunk 3: MemoryQueryService and Tool

### Task 3.1: Implement MemoryQueryService

**Files:**
- Create: `backend/src/magi/memory/query/service.py`
- Modify: `backend/tests/memory/test_memory_query.py`

- [ ] **Step 1: Write the failing tests for MemoryQueryService**

```python
# Add to backend/tests/memory/test_memory_query.py
from unittest.mock import AsyncMock, MagicMock

class TestMemoryQueryService:
    """Tests for MemoryQueryService orchestration."""

    @pytest.fixture
    def mock_layer_handlers(self):
        """Create mock layer handlers."""
        l1_handler = MagicMock()
        l1_handler.query = AsyncMock(return_value=[
            {"id": "1", "type": "browser_history", "timestamp": 1700000000.0, "data": {"url": "https://example.com"}}
        ])

        l3_handler = MagicMock()
        l3_handler.query = AsyncMock(return_value=[
            {"id": "2", "type": "chat", "timestamp": 1700001000.0, "data": {"content": "Hello"}}
        ])

        return {"L1": l1_handler, "L3": l3_handler}

    def test_missing_time_range_requires_confirmation(self):
        """Should return confirm_required when time_range is missing."""
        from magi.memory.query.service import MemoryQueryService
        from magi.memory.query.models import MemoryQueryRequest

        service = MemoryQueryService()
        request = MemoryQueryRequest(
            query="test query",
            time_range={}  # Empty time range
        )

        result = asyncio.get_event_loop().run_until_complete(service.query(request))

        assert result.status == "confirm_required"
        assert "time range" in result.confirm_prompt.lower()

    def test_empty_results(self, mock_layer_handlers):
        """Should return empty status when no results found."""
        from magi.memory.query.service import MemoryQueryService
        from magi.memory.query.models import MemoryQueryRequest

        # Handlers return empty
        for handler in mock_layer_handlers.values():
            handler.query = AsyncMock(return_value=[])

        service = MemoryQueryService(layer_handlers=mock_layer_handlers)
        request = MemoryQueryRequest(
            query="nonexistent",
            time_range={"relative": "1d"}
        )

        result = asyncio.get_event_loop().run_until_complete(service.query(request))

        assert result.status == "empty"

    def test_successful_query(self, mock_layer_handlers):
        """Should return success with processed results."""
        from magi.memory.query.service import MemoryQueryService
        from magi.memory.query.models import MemoryQueryRequest

        service = MemoryQueryService(layer_handlers=mock_layer_handlers)
        request = MemoryQueryRequest(
            query="What did I browse yesterday?",
            time_range={"relative": "1d"}
        )

        result = asyncio.get_event_loop().run_until_complete(service.query(request))

        assert result.status == "success"
        assert len(result.data) >= 1
        assert result.query_meta is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/memory/test_memory_query.py::TestMemoryQueryService -v`
Expected: FAIL with "cannot import name 'MemoryQueryService'"

- [ ] **Step 3: Implement service.py**

```python
# backend/src/magi/memory/query/service.py
"""Memory query service for orchestrating retrieval across L1-L5 layers."""
import asyncio
from typing import Any, Dict, List, Optional

from .models import MemoryQueryRequest, MemoryQueryResult
from .handlers import TypeHandlerRegistry
from .privacy import PrivacyGuard
from .router import IntentRouter


class MemoryQueryService:
    """
    Main service for memory retrieval.
    Orchestrates routing, privacy, querying, and formatting.
    """

    def __init__(
        self,
        layer_handlers: Optional[Dict[str, Any]] = None,
        type_handlers: Optional[TypeHandlerRegistry] = None,
        privacy_guard: Optional[PrivacyGuard] = None,
    ):
        self.router = IntentRouter()
        self.privacy_guard = privacy_guard or PrivacyGuard()
        self.type_handlers = type_handlers or TypeHandlerRegistry()
        self.layer_handlers = layer_handlers or {}

    async def query(self, request: MemoryQueryRequest) -> MemoryQueryResult:
        """
        Execute memory query with full pipeline.

        Pipeline:
        1. Validate time_range (require if missing)
        2. Privacy check
        3. Intent routing
        4. Parallel layer queries
        5. TypeHandler extraction
        6. Return formatted results

        Args:
            request: MemoryQueryRequest with query parameters

        Returns:
            MemoryQueryResult with status and data
        """
        # Step 1: Validate time range
        if not self._validate_time_range(request.time_range):
            return MemoryQueryResult(
                status="confirm_required",
                confirm_prompt="Please specify a time range for the search (e.g., 'yesterday', 'last week')."
            )

        # Step 2: Determine data types to query
        data_types = request.data_types or self._infer_data_types(request.query)

        # Step 3: Privacy check
        privacy_result = self.privacy_guard.check(data_types, {"query": request.query})
        if not privacy_result.allowed:
            return MemoryQueryResult(
                status="denied",
                confirm_prompt=f"Access to {', '.join(privacy_result.blocked_types)} is restricted."
            )
        if privacy_result.requires_confirmation:
            return MemoryQueryResult(
                status="confirm_required",
                confirm_prompt=privacy_result.confirmation_prompt
            )

        # Step 4: Intent routing
        routing_plan = self.router.analyze(request.query, request.time_range)

        # Step 5: Execute parallel queries
        raw_results = await self.router.execute(
            routing_plan,
            request,
            self.layer_handlers
        )

        # Step 6: Apply type handlers
        processed_results: List[Dict[str, Any]] = []
        for item in raw_results:
            memory_type = item.get("type")
            handler = self.type_handlers.get_handler(memory_type)

            if handler:
                raw_data = item.get("data", item)
                processed_results.append({
                    "id": item.get("id"),
                    "type": memory_type,
                    "timestamp": item.get("timestamp"),
                    "source": item.get("source"),
                    "content": handler.extract(raw_data),
                })
            else:
                # Fallback: return raw data
                processed_results.append(item)

        # Apply limit
        if request.limit and request.limit > 0:
            processed_results = processed_results[:request.limit]

        # Build query metadata
        query_meta = {
            "layer": routing_plan.primary_layer,
            "secondary_layers": routing_plan.secondary_layers,
            "confidence": routing_plan.confidence,
            "total_count": len(processed_results),
        }

        return MemoryQueryResult(
            status="success" if processed_results else "empty",
            data=processed_results if processed_results else None,
            query_meta=query_meta
        )

    def _validate_time_range(self, time_range: Dict[str, Any]) -> bool:
        """Check if time range is specified."""
        if not time_range:
            return False
        return bool(
            time_range.get("start") or
            time_range.get("end") or
            time_range.get("relative")
        )

    def _infer_data_types(self, query: str) -> List[str]:
        """Infer relevant data types from query context."""
        query_lower = query.lower()
        types: List[str] = []

        if any(kw in query_lower for kw in ["browse", "website", "page", "url", "浏览", "网页"]):
            types.append("browser_history")
        if any(kw in query_lower for kw in ["chat", "conversation", "talk", "对话", "聊天"]):
            types.append("chat")
        if any(kw in query_lower for kw in ["note", "笔记", "记录"]):
            types.append("note")

        # Default to common types if no specific inference
        if not types:
            types = ["browser_history", "chat", "note"]

        return types
```

- [ ] **Step 4: Update test file imports**

```python
# Add at top of backend/tests/memory/test_memory_query.py
import asyncio
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd backend && pytest tests/memory/test_memory_query.py::TestMemoryQueryService -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add backend/src/magi/memory/query/service.py backend/tests/memory/test_memory_query.py
git commit -m "feat(memory): add MemoryQueryService with full query pipeline"
```

---

### Task 3.2: Implement MemoryQueryTool

**Files:**
- Create: `backend/src/magi/tools/memory_query.py`
- Create: `backend/tests/test_memory_query_tool.py`

- [ ] **Step 1: Write the failing test for MemoryQueryTool**

```python
# backend/tests/test_memory_query_tool.py
"""Unit tests for MemoryQueryTool."""
import pytest
from unittest.mock import AsyncMock, MagicMock


class TestMemoryQueryTool:
    """Tests for MemoryQueryTool."""

    def test_tool_schema_definition(self):
        """Should have proper schema definition."""
        from magi.tools.memory_query import MemoryQueryTool

        tool = MemoryQueryTool()
        schema = tool.get_schema()

        assert schema.name == "memory_query"
        assert "memory" in schema.category.lower()
        assert len(schema.parameters) >= 2  # query + time_range at minimum

    def test_tool_parameters(self):
        """Should have required query and time_range parameters."""
        from magi.tools.memory_query import MemoryQueryTool

        tool = MemoryQueryTool()
        schema = tool.get_schema()

        param_names = [p.name for p in schema.parameters]
        assert "query" in param_names
        assert "time_range" in param_names

        # query should be required
        query_param = next(p for p in schema.parameters if p.name == "query")
        assert query_param.required is True

    @pytest.mark.asyncio
    async def test_tool_execution(self):
        """Should execute query and return ToolResult."""
        from magi.tools.memory_query import MemoryQueryTool
        from magi.tools.schema import ToolExecutionContext

        tool = MemoryQueryTool()
        context = ToolExecutionContext(
            agent_id="test",
            task_id="test-task"
        )

        result = await tool.execute(
            {
                "query": "test query",
                "time_range": {"relative": "1d"}
            },
            context
        )

        # Result should be a ToolResult
        assert hasattr(result, "success")
        assert hasattr(result, "data")

    @pytest.mark.asyncio
    async def test_tool_to_claude_format(self):
        """Should export to Claude tool format."""
        from magi.tools.memory_query import MemoryQueryTool

        tool = MemoryQueryTool()
        claude_format = tool.to_claude_format()

        assert claude_format["name"] == "memory_query"
        assert "input_schema" in claude_format
        assert "properties" in claude_format["input_schema"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_memory_query_tool.py -v`
Expected: FAIL with "No module named 'magi.tools.memory_query'"

- [ ] **Step 3: Implement memory_query.py tool**

```python
# backend/src/magi/tools/memory_query.py
"""Memory query tool for retrieving memories across L1-L5 layers."""
from typing import Any, Dict, List

from .schema import Tool, ToolParameter, ParameterType, ToolResult, ToolExecutionContext
from ..memory.query import MemoryQueryService, MemoryQueryRequest


class MemoryQueryTool(Tool):
    """Tool for querying memories across L1-L5 layers."""

    def _init_schema(self) -> None:
        """Initialize tool schema."""
        from .schema import ToolSchema

        self.schema = ToolSchema(
            name="memory_query",
            description="Retrieve memories from L1-L5 layers. Use this tool when the user asks about their past activities, browsing history, conversations, or any historical data. Supports intelligent routing across memory layers.",
            category="memory",
            parameters=[
                ToolParameter(
                    name="query",
                    type=ParameterType.STRING,
                    description="The search query describing what memories to retrieve (e.g., 'what I browsed yesterday', 'my notes about AI')",
                    required=True,
                ),
                ToolParameter(
                    name="time_range",
                    type=ParameterType.OBJECT,
                    description="Time range for the search. Must include 'relative' (e.g., '1d', '7d', '1M') or 'start'/'end' timestamps.",
                    required=True,
                ),
                ToolParameter(
                    name="data_types",
                    type=ParameterType.ARRAY,
                    description="Optional filter for memory types (e.g., ['browser_history', 'chat', 'note'])",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type=ParameterType.INTEGER,
                    description="Maximum number of results to return",
                    required=False,
                    default=20,
                    min_value=1,
                    max_value=100,
                ),
            ],
            examples=[
                {
                    "query": "What websites did I visit yesterday?",
                    "time_range": {"relative": "1d"},
                    "data_types": ["browser_history"]
                },
                {
                    "query": "Find my notes about machine learning from last week",
                    "time_range": {"relative": "7d"},
                    "data_types": ["note"]
                }
            ],
            tags=["memory", "search", "history"],
            timeout=30,
        )

        self._service = MemoryQueryService()

    async def execute(
        self,
        parameters: Dict[str, Any],
        context: ToolExecutionContext
    ) -> ToolResult:
        """Execute memory query."""
        try:
            request = MemoryQueryRequest(
                query=parameters["query"],
                time_range=parameters.get("time_range", {}),
                data_types=parameters.get("data_types"),
                limit=parameters.get("limit"),
            )

            result = await self._service.query(request)

            if result.status == "success":
                return ToolResult(
                    success=True,
                    data={
                        "results": result.data,
                        "meta": result.query_meta,
                    }
                )
            elif result.status == "confirm_required":
                return ToolResult(
                    success=False,
                    error=result.confirm_prompt,
                    error_code="CONFIRM_REQUIRED",
                )
            elif result.status == "empty":
                return ToolResult(
                    success=True,
                    data={"results": [], "meta": result.query_meta},
                )
            else:  # denied
                return ToolResult(
                    success=False,
                    error=result.confirm_prompt,
                    error_code="ACCESS_DENIED",
                )

        except Exception as e:
            return ToolResult(
                success=False,
                error=str(e),
                error_code="EXECUTION_ERROR",
            )

    def is_ready(self) -> bool:
        """Check if tool is ready to use."""
        # Memory query is always available
        return True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_memory_query_tool.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/tools/memory_query.py backend/tests/test_memory_query_tool.py
git commit -m "feat(tools): add MemoryQueryTool for LLM invocation"
```

---

### Task 3.3: Register MemoryQueryTool

**Files:**
- Modify: `backend/src/magi/tools/__init__.py`

- [ ] **Step 1: Check current tool registration pattern**

Run: `cat backend/src/magi/tools/__init__.py`

- [ ] **Step 2: Add MemoryQueryTool to tool exports**

```python
# Add to backend/src/magi/tools/__init__.py
from .memory_query import MemoryQueryTool

# Add to __all__ list if present
```

- [ ] **Step 3: Verify tool can be imported**

Run: `cd backend && python -c "from magi.tools.memory_query import MemoryQueryTool; print('OK')"`
Expected: "OK"

- [ ] **Step 4: Commit**

```bash
git add backend/src/magi/tools/__init__.py
git commit -m "feat(tools): register MemoryQueryTool in module exports"
```

---

## Chunk 4: ContextDecider Extension

### Task 4.1: Add memory retrieval guidance to ContextDecider

**Files:**
- Modify: `backend/src/magi/tools/context_decider.py`
- Create: `backend/tests/test_context_decider_memory.py`

- [ ] **Step 1: Write the failing test for memory guidance**

```python
# backend/tests/test_context_decider_memory.py
"""Tests for ContextDecider memory retrieval guidance."""
import pytest
from unittest.mock import MagicMock, AsyncMock


class TestContextDeciderMemoryGuidance:
    """Tests for memory retrieval guidance in ContextDecider."""

    def test_evaluate_memory_need_time_based_query(self):
        """Should detect memory retrieval need for time-based queries."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        llm_adapter = MagicMock()
        decider = ContextDecider(tool_registry, llm_adapter)

        guidance = decider.evaluate_memory_need(
            "What did I browse yesterday?",
            {"current_date": "2024-01-15"}
        )

        assert guidance is not None
        assert guidance.inject_prompt is True
        assert "memory_query" in [t.name for t in guidance.recommended_tools]

    def test_evaluate_memory_need_browsing_pattern(self):
        """Should detect memory retrieval for browsing pattern queries."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        llm_adapter = MagicMock()
        decider = ContextDecider(tool_registry, llm_adapter)

        guidance = decider.evaluate_memory_need(
            "Analyze my browsing patterns this week",
            {"current_date": "2024-01-15"}
        )

        assert guidance is not None
        assert "memory_query" in [t.name for t in guidance.recommended_tools]

    def test_evaluate_memory_need_no_need(self):
        """Should not trigger for queries that don't need memory."""
        from magi.tools.context_decider import ContextDecider

        tool_registry = MagicMock()
        llm_adapter = MagicMock()
        decider = ContextDecider(tool_registry, llm_adapter)

        guidance = decider.evaluate_memory_need(
            "What is the weather in Tokyo?",
            {}
        )

        # Weather query doesn't need personal memory
        assert guidance is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && pytest tests/test_context_decider_memory.py -v`
Expected: FAIL with "'ContextDecider' object has no attribute 'evaluate_memory_need'"

- [ ] **Step 3: Add memory guidance to ContextDecider**

```python
# Add to backend/src/magi/tools/context_decider.py after the class definition

from dataclasses import dataclass
from typing import List as TypingList


@dataclass
class ToolRecommendation:
    """Tool recommendation with suggested parameters."""
    name: str
    description: str
    suggested_params: dict


@dataclass
class MemoryGuidance:
    """Memory retrieval guidance from ContextDecider."""
    inject_prompt: bool
    system_prompt: str
    recommended_tools: TypingList[ToolRecommendation]


# Add to ContextDecider class:
MEMORY_RETRIEVAL_TRIGGERS = [
    "what did i", "what was i", "what have i",
    "yesterday", "last week", "last month", "recently",
    "browsing", "browse", "visited", "watched", "read",
    "my history", "my activity", "my notes", "my chat",
    "browse yesterday", "最近", "浏览", "看", "读",
]


class ContextDecider:
    # ... existing code ...

    def evaluate_memory_need(
        self,
        user_message: str,
        context: dict
    ) -> MemoryGuidance | None:
        """
        Evaluate if memory retrieval would help answer the user's query.

        Args:
            user_message: User's message
            context: Current context (date, etc.)

        Returns:
            MemoryGuidance if memory retrieval is recommended, None otherwise.
        """
        message_lower = user_message.lower()

        # Check for memory-related triggers
        trigger_matched = any(
            trigger in message_lower
            for trigger in self.MEMORY_RETRIEVAL_TRIGGERS
        )

        if not trigger_matched:
            return None

        # Infer time range from message
        time_range = self._infer_time_range(message_lower)

        # Build tool recommendation
        suggested_params = {
            "query": user_message,
            "time_range": time_range,
        }

        # Infer data types from message
        data_types = self._infer_memory_types(message_lower)
        if data_types:
            suggested_params["data_types"] = data_types

        return MemoryGuidance(
            inject_prompt=True,
            system_prompt=(
                "Based on the user's query, memory retrieval may be helpful. "
                "Consider using the memory_query tool to access relevant historical data."
            ),
            recommended_tools=[
                ToolRecommendation(
                    name="memory_query",
                    description="Retrieve memories from L1-L5 layers",
                    suggested_params=suggested_params,
                )
            ]
        )

    def _infer_time_range(self, message_lower: str) -> dict:
        """Infer time range from message content."""
        if "yesterday" in message_lower or "昨天" in message_lower:
            return {"relative": "1d"}
        elif "last week" in message_lower or "上周" in message_lower:
            return {"relative": "7d"}
        elif "last month" in message_lower or "上个月" in message_lower:
            return {"relative": "30d"}
        elif "recently" in message_lower or "最近" in message_lower:
            return {"relative": "7d"}
        else:
            return {"relative": "7d"}  # Default to last week

    def _infer_memory_types(self, message_lower: str) -> list[str] | None:
        """Infer memory types from message content."""
        types = []
        if any(kw in message_lower for kw in ["browse", "visit", "website", "浏览", "网页"]):
            types.append("browser_history")
        if any(kw in message_lower for kw in ["chat", "conversation", "对话", "聊天"]):
            types.append("chat")
        if any(kw in message_lower for kw in ["note", "笔记", "记录"]):
            types.append("note")
        return types if types else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && pytest tests/test_context_decider_memory.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/src/magi/tools/context_decider.py backend/tests/test_context_decider_memory.py
git commit -m "feat(context-decider): add memory retrieval guidance evaluation"
```

---

## Chunk 5: Integration and Documentation

### Task 5.1: Run full test suite

- [ ] **Step 1: Run all memory query tests**

Run: `cd backend && pytest tests/memory/test_memory_query.py tests/test_memory_query_tool.py tests/test_context_decider_memory.py -v`
Expected: All PASS

- [ ] **Step 2: Run full test suite to check for regressions**

Run: `cd backend && pytest -x -q`
Expected: No failures

- [ ] **Step 3: Commit any fixes if needed**

---

### Task 5.2: Update module documentation

**Files:**
- Modify: `backend/src/magi/memory/query/__init__.py`

- [ ] **Step 1: Add comprehensive docstrings**

```python
# Update backend/src/magi/memory/query/__init__.py
"""Memory query module for retrieving memories across L1-L5 layers.

This module provides a unified interface for querying user memories stored
across different memory layers:

- L1: Raw events and timeline data (factual verification)
- L2: Relations and connections (relationship analysis)
- L3: Semantic embeddings (concept retrieval)
- L4: Summaries (trend analysis)
- L5: Capabilities (planning context)

Usage:
    from magi.memory.query import MemoryQueryService, MemoryQueryRequest

    service = MemoryQueryService()
    request = MemoryQueryRequest(
        query="What did I browse yesterday?",
        time_range={"relative": "1d"}
    )
    result = await service.query(request)

The service automatically:
1. Validates time range requirements
2. Checks privacy sensitivity
3. Routes to appropriate memory layers
4. Formats results using type handlers
"""

from .models import MemoryQueryRequest, MemoryQueryResult
from .handlers import TypeHandler, TypeHandlerRegistry
from .privacy import PrivacyGuard, SensitivityLevel, PrivacyCheckResult
from .router import IntentRouter, RoutingPlan
from .service import MemoryQueryService

__all__ = [
    "MemoryQueryRequest",
    "MemoryQueryResult",
    "TypeHandler",
    "TypeHandlerRegistry",
    "PrivacyGuard",
    "SensitivityLevel",
    "PrivacyCheckResult",
    "IntentRouter",
    "RoutingPlan",
    "MemoryQueryService",
]
```

- [ ] **Step 2: Commit**

```bash
git add backend/src/magi/memory/query/__init__.py
git commit -m "docs(memory): add comprehensive module docstring"
```

---

## Summary

This implementation plan creates a complete memory query system with:

1. **Core Models** - Request/Result dataclasses for type-safe API
2. **Type Handlers** - Extensible content extraction for different memory types
3. **Privacy Guard** - Sensitivity-based access control
4. **Intent Router** - Keyword-based layer selection (MVP) with parallel query support
5. **Memory Query Service** - Orchestrates the full query pipeline
6. **Memory Query Tool** - Tool interface for LLM invocation
7. **ContextDecider Extension** - Proactive memory retrieval suggestions

Each task follows TDD with failing tests first, minimal implementation, and verification before commit.
