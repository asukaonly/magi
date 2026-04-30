"""Compatibility facade for hybrid memory retrieval layer handlers."""

from __future__ import annotations

import logging
from typing import Any, Optional

from .handler_base import RRFSearchHandler, rrf_fuse
from .l1_handler import L1Handler
from .l2_handler import L2Handler
from .l3_handler import L3Handler
from .l4_handler import L4Handler
from .models import (
    L1Conditions,
    L2Conditions,
    L3Conditions,
    L4Conditions,
    LayerQueryPlan,
)

logger = logging.getLogger(__name__)


async def execute_plan(
    plan: LayerQueryPlan,
    *,
    l1: Optional[L1Handler] = None,
    l2: Optional[L2Handler] = None,
    l3: Optional[L3Handler] = None,
    l4: Optional[L4Handler] = None,
    session_id: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Any:
    """Dispatch a single LayerQueryPlan to the appropriate handler."""
    time_range = plan.time_range

    if plan.layer == "L1" and l1 is not None:
        assert isinstance(plan.conditions, L1Conditions)
        return await l1.execute(plan.conditions, time_range, session_id=session_id, user_id=user_id)
    if plan.layer == "L2" and l2 is not None:
        assert isinstance(plan.conditions, L2Conditions)
        return await l2.execute(plan.conditions, time_range, user_id=user_id)
    if plan.layer == "L3" and l3 is not None:
        assert isinstance(plan.conditions, L3Conditions)
        return await l3.execute(plan.conditions, time_range)
    if plan.layer == "L4" and l4 is not None:
        assert isinstance(plan.conditions, L4Conditions)
        return await l4.execute(plan.conditions, time_range)

    logger.warning("No handler available for layer %s", plan.layer)
    return [] if plan.layer != "L2" else {"entity_cards": [], "relationships": []}


__all__ = [
    "L1Handler",
    "L2Handler",
    "L3Handler",
    "L4Handler",
    "RRFSearchHandler",
    "execute_plan",
    "rrf_fuse",
]