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
