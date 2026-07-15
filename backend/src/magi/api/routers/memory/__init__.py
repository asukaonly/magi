"""Memory API for the rewritten L0-L4 memory system."""

from __future__ import annotations

from .dependencies import (
    _resolve_hybrid_retrieval_service,
    _resolve_memory_integration,
    _resolve_scenario_llm_pool,
    _resolve_unified_memory,
    _synthesize_eval_answer,
    get_chat_read_service,
    logger,
)
from .router import memory_router

# Import route modules for registration side effects.
from . import dashboard_routes as _dashboard_routes
from . import overview_routes as _overview_routes
from . import search_routes as _search_routes
from .eval import routes as _eval_routes
from . import embedding_routes as embedding_routes  # noqa: E402,F401
from .l0 import routes as _l0_routes
from .l1 import routes as _l1_routes
from .l2 import episodes_routes as _l2_episodes_routes
from .l2 import correction_routes as _l2_correction_routes  # noqa: F401
from .l2 import experiences_routes as _l2_experiences_routes
from .l2 import forget_routes as _l2_forget_routes
from .l2 import knowledge_routes as _l2_knowledge_routes
from .l2 import operations_routes as _l2_operations_routes
from .l2 import status_routes as _l2_status_routes
from .l3 import routes as _l3_routes
from .l4 import routes as _l4_routes
from . import manual_entries_routes as _manual_entries_routes  # noqa: F401
from .portrait_routes import build_router as _build_portrait_router
from .stories_routes import build_router as _build_stories_router
from .portrait_self_routes import build_router as _build_portrait_self_router

memory_router.include_router(_build_portrait_router())
memory_router.include_router(_build_stories_router())
memory_router.include_router(_build_portrait_self_router())

__all__ = [
    "memory_router",
    "_resolve_hybrid_retrieval_service",
    "_resolve_memory_integration",
    "_resolve_scenario_llm_pool",
    "_resolve_unified_memory",
    "_synthesize_eval_answer",
    "get_chat_read_service",
    "logger",
]
