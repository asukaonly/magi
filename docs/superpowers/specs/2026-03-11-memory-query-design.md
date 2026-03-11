# Memory Query Design

## Overview

This document describes the design for a memory retrieval system that enables the AI agent to query and analyze user memories across L1-L5 layers, supporting both passive tool invocation and proactive context injection.

## Goals

- Enable users to query their historical data (browser history, chats, notes, etc.)
- Support intelligent routing across memory layers (L1-L5) based on query intent
- Provide privacy controls for sensitive data types
- Integrate with existing ContextDecider for proactive memory suggestions

## Architecture

```
User Message
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│                      ContextDecider                              │
│  - Evaluates if memory retrieval is needed                       │
│  - Injects system prompt guidance                                │
│  - Recommends memory_query tool with parameter suggestions       │
└─────────────────────────────────────────────────────────────────┘
     │
     ▼
┌─────────────────────────────────────────────────────────────────┐
│                        Core Agent                                │
│                   (Decides whether to call tool)                 │
└─────────────────────────────────────────────────────────────────┘
     │
     ├──────────────┬──────────────┐
     ▼              ▼              ▼
┌─────────┐   ┌──────────┐   Direct Response
│  Other  │   │ memory_  │
│  Tools  │   │  query   │
└─────────┘   └──────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                    MemoryQueryTool                               │
│  (tools/memory_query.py)                                         │
└─────────────────────────────────────────────────────────────────┘
                   │
                   ▼
┌─────────────────────────────────────────────────────────────────┐
│                  MemoryQueryService                              │
│  (memory/query/service.py)                                       │
│                                                                  │
│  Pipeline:                                                       │
│  1. Validate time_range (required)                              │
│  2. PrivacyGuard check                                          │
│  3. IntentRouter analyze & route                                │
│  4. Parallel layer queries (L1-L5)                              │
│  5. TypeHandler extraction                                       │
│  6. Return formatted results                                    │
└─────────────────────────────────────────────────────────────────┘
     │
     ├──────────┬──────────┬──────────┬──────────┐
     ▼          ▼          ▼          ▼          ▼
   L1         L2         L3         L4         L5
 Handler    Handler    Handler    Handler    Handler
```

## Components

### 1. MemoryQueryTool

**Location:** `backend/src/magi/tools/memory_query.py`

Tool interface invoked by the LLM agent.

```python
class MemoryQueryTool(Tool):
    """Tool for querying memories across L1-L5 layers."""

    def __init__(self):
        self.service = MemoryQueryService()

    async def execute(self, request: MemoryQueryRequest) -> MemoryQueryResult:
        return await self.service.query(request)
```

**Tool Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| query | str | Yes | Query content/description |
| time_range | dict | Yes | Time range for search |
| time_range.start | datetime | No | Absolute start time |
| time_range.end | datetime | No | Absolute end time |
| time_range.relative | str | No | Relative range (e.g., "7d", "1h", "1M") |
| data_types | list[str] | No | Filter by data types |
| limit | int | No | Max results to return |

**Tool Response:**

```python
{
    "status": "success" | "confirm_required" | "empty" | "denied",
    "confirm_prompt": str | None,  # Prompt when user confirmation needed
    "data": [
        {
            "id": str,
            "type": str,           # "browser_history" | "chat" | "note" | ...
            "timestamp": datetime,
            "source": str,
            "content": Any,        # TypeHandler-processed content
        }
    ],
    "query_meta": {
        "layer": str,              # Primary layer queried
        "secondary_layers": list,  # Additional layers if parallel query
        "confidence": float,       # Routing confidence
        "total_count": int
    }
}
```

### 2. MemoryQueryService

**Location:** `backend/src/magi/memory/query/service.py`

Orchestrates the complete query pipeline.

```python
class MemoryQueryService:
    """Main service for memory retrieval."""

    def __init__(self):
        self.router = IntentRouter()
        self.privacy_guard = PrivacyGuard()
        self.type_handlers = TypeHandlerRegistry()
        self.layer_query_handlers = {
            "L1": L1QueryHandler(),
            "L2": L2QueryHandler(),
            "L3": L3QueryHandler(),
            "L4": L4QueryHandler(),
            "L5": L5QueryHandler(),
        }

    async def query(self, request: MemoryQueryRequest) -> MemoryQueryResult:
        # Pipeline implementation
        ...
```

### 3. IntentRouter

**Location:** `backend/src/magi/memory/query/router.py`

Lightweight model-based intent analyzer with multi-layer parallel query support.

**Routing Strategy by Query Type:**

| Layer | Use Case | Example Queries |
|-------|----------|-----------------|
| L1 | Factual verification, exact time/numbers | "What time did I leave yesterday?" |
| L2 | Multi-hop reasoning, relationship analysis | "Who is connected to my former colleague?" |
| L3 | Concept retrieval, fuzzy matching | "Find my scattered thoughts on AI agents" |
| L4 | Macro trends, periodic review | "Summarize my job search mindset over 6 months" |
| L5 | Self-planning, tool chain routing | "What approach worked for similar tasks before?" |

```python
@dataclass
class RoutingPlan:
    primary_layer: str              # Main layer to query
    secondary_layers: list[str]     # Fallback layers
    confidence: float               # Prediction confidence (0-1)
    reasoning: str                  # Why this routing was chosen


class IntentRouter:
    """Lightweight model-based intent analyzer."""

    def analyze(self, query: str, time_range: dict) -> RoutingPlan:
        """
        Use lightweight model to analyze query intent.
        Returns routing plan with primary/secondary layers.
        """
        ...

    async def execute(self, plan: RoutingPlan, request: MemoryQueryRequest) -> list[dict]:
        """
        Execute parallel queries across layers when confidence is low.
        Merge and deduplicate results by relevance.
        """
        layers_to_query = [plan.primary_layer]
        if plan.confidence < 0.8:
            layers_to_query.extend(plan.secondary_layers)

        results = await asyncio.gather(*[
            self.query_layer(layer, request)
            for layer in layers_to_query
        ])

        return self.merge_results(results)
```

### 4. PrivacyGuard

**Location:** `backend/src/magi/memory/query/privacy.py`

Handles sensitivity classification and user confirmation requirements.

**Sensitivity Levels:**

| Level | Behavior | Examples |
|-------|----------|----------|
| PUBLIC | No restrictions | - |
| INTERNAL | Default, no confirmation | browser_history, chat, note |
| SENSITIVE | Requires user confirmation | private_diary, health_data, financial |
| RESTRICTED | Never retrievable | password, credential |

```python
class SensitivityLevel(Enum):
    PUBLIC = "public"
    INTERNAL = "internal"
    SENSITIVE = "sensitive"
    RESTRICTED = "restricted"


class PrivacyGuard:
    """Guard for memory retrieval privacy controls."""

    def check(self, data_types: list[str], query_context: dict) -> PrivacyCheckResult:
        """
        Check if memory retrieval is allowed.
        Returns permission status and confirmation requirements.
        """
        ...
```

### 5. TypeHandler

**Location:** `backend/src/magi/memory/query/handlers.py`

Extracts core content from different memory types.

```python
class TypeHandler(ABC):
    """Base handler for extracting core content."""

    @property
    @abstractmethod
    def supported_types(self) -> list[str]:
        pass

    @abstractmethod
    def extract(self, raw_data: dict) -> dict:
        pass


class TextHandler(TypeHandler):
    """Handler for text-based memories."""
    supported_types = ["chat", "note", "document"]


class BrowserHistoryHandler(TypeHandler):
    """Handler for browser history."""
    supported_types = ["browser_history"]


class ImageHandler(TypeHandler):
    """Handler for images."""
    supported_types = ["image", "screenshot"]


class AudioHandler(TypeHandler):
    """Handler for audio."""
    supported_types = ["audio", "voice_note"]


class TypeHandlerRegistry:
    """Registry for all type handlers."""

    def get_handler(self, memory_type: str) -> TypeHandler | None:
        ...

    def register(self, handler: TypeHandler):
        """Register custom handler."""
        ...
```

### 6. ContextDecider Extension

**Location:** Existing ContextDecider location

Adds memory retrieval guidance to the decision flow.

```python
MEMORY_RETRIEVAL_CONDITIONS = {
    "triggers": [
        "user asks about past events or activities",
        "user references previous conversations",
        "user requests analysis of browsing/productivity patterns",
        "user asks what they were doing/reading/watching",
        "user mentions time-based queries (recently, yesterday, last week)",
    ],
    "system_prompt_injection": (
        "Based on the user's query, memory retrieval may be helpful. "
        "Consider using the memory_query tool to access relevant historical data."
    ),
}


class ContextDecider:
    def evaluate_memory_need(self, user_message: str, context: dict) -> MemoryGuidance | None:
        """
        Evaluate if memory retrieval would help.
        Returns guidance with injection prompts and tool recommendations.
        """
        ...
```

## File Structure

```
backend/src/magi/
├── memory/
│   ├── __init__.py
│   ├── models.py                    # Existing
│   ├── prompt_context_schema.py     # Existing
│   ├── prompt_context_assembler.py  # Existing
│   ├── l5_capabilities.py           # Existing
│   └── query/                       # NEW
│       ├── __init__.py
│       ├── models.py                # MemoryQueryRequest, MemoryQueryResult
│       ├── service.py               # MemoryQueryService
│       ├── router.py                # IntentRouter, RoutingPlan
│       ├── privacy.py               # PrivacyGuard, SensitivityLevel
│       └── handlers.py              # TypeHandler, TypeHandlerRegistry
│
└── tools/
    └── memory_query.py              # NEW: MemoryQueryTool
```

## Data Flow

```
1. User sends message
        │
2. ContextDecider evaluates if memory retrieval is relevant
        │
3. If relevant, inject system prompt + tool recommendations
        │
4. Core Agent decides whether to invoke memory_query tool
        │
5. If invoked, MemoryQueryTool.execute() is called
        │
6. MemoryQueryService.query() pipeline:
   ├─ 6a. Validate time_range (require if missing)
   ├─ 6b. PrivacyGuard.check() - may return confirm_required
   ├─ 6c. IntentRouter.analyze() - determine layers
   ├─ 6d. Parallel layer queries via router.execute()
   └─ 6e. TypeHandler.extract() for each result
        │
7. Return MemoryQueryResult to Agent
        │
8. Agent processes results and responds to user
```

## Key Design Decisions

1. **Hybrid Mode**: Proactive injection (ContextDecider) + passive invocation (LLM decides)
2. **Time Required**: Time parameter is mandatory; trigger user confirmation if missing
3. **Internal Routing**: Lightweight model determines intent + parallel multi-layer queries
4. **Layer Strategy**: L1 facts / L2 relations / L3 fuzzy / L4 trends / L5 planning
5. **Privacy Control**: Sensitivity levels with user confirmation for sensitive data
6. **Type Handlers**: Extensible handlers for different memory content types

## Implementation Phases

### Phase 1: Core Infrastructure
- [ ] Create `memory/query/` module structure
- [ ] Implement MemoryQueryRequest/Result models
- [ ] Implement TypeHandler base and registry
- [ ] Implement basic MemoryQueryService skeleton

### Phase 2: Routing & Privacy
- [ ] Implement IntentRouter with keyword-based routing (MVP)
- [ ] Implement PrivacyGuard with sensitivity rules
- [ ] Add lightweight model integration for routing

### Phase 3: Tool Integration
- [ ] Implement MemoryQueryTool
- [ ] Register tool in tool registry
- [ ] Add ContextDecider extension for memory guidance

### Phase 4: Layer Handlers
- [ ] Implement L1QueryHandler
- [ ] Implement L2QueryHandler
- [ ] Implement L3QueryHandler (embedding-based)
- [ ] Implement L4QueryHandler
- [ ] Implement L5QueryHandler

### Phase 5: Testing & Polish
- [ ] Unit tests for each component
- [ ] Integration tests for full pipeline
- [ ] Performance optimization for parallel queries

## Open Questions

1. **Lightweight Model Choice**: Which model to use for intent classification? Options:
   - Local embedding similarity
   - Small classification model (e.g., distilbert)
   - Rule-based + embedding hybrid

2. **L3 Embedding Integration**: How to integrate with existing ChromaDB setup?

3. **Caching Strategy**: Should frequent queries be cached? What's the invalidation policy?

---

**Created**: 2026-03-11
**Status**: Design Approved
