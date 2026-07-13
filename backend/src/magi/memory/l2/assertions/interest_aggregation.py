"""Aggregate repeated INTERESTED_IN graph edges into recent interest assertions.

This fills the gap where ``INTERESTED_IN`` edges (produced by behavioral
sensors such as chrome_history) never reached the snapshot, whereas
``LIKES``/``DISLIKES`` do via ``_add_relation_preferences``.

Design:
- Reads profile-worthy ``INTERESTED_IN`` edges for ``entity_id`` with enough
  predicate-bound evidence across multiple original L1 occurrence days.
- Looks up canonical names for all qualifying topic objects in one batch.
- Builds one assertion candidate per topic and persists each via
  ``store.upsert_assertion_candidate``, the same public entry that the L2
  pipeline uses for phase2 assertion candidates.  This means:
    * source-aware safety is automatic: ``source_domain="external_activity"``
      classifies as ``source_tier="inferred"``, so an inferred interest can
      never overwrite a user's self-stated preference.
    * snapshot ``source_tier="inferred"`` tagging is inherited.
- ``trait_name="interest.<slug>"`` (slug = object_id with ``topic:`` stripped)
  avoids the ``preference.`` prefix that ``_add_assertion_preferences``
  explicitly skips.
- The resulting ``interest_profile`` assertion is recent and expiring. Passive
  browsing never becomes durable through this fallback rule.
- Idempotent: calling twice merges evidence and keeps a single live row.
"""

from __future__ import annotations

from typing import Any

from ....core.logger import get_logger
from ....identity.defaults import CANONICAL_LOCAL_USER
from .derived_rules import builtin_interest_rule, evaluate_graph_derived_assertion_rule

logger = get_logger(__name__)
_DEFAULT_USER_ENTITY_ID = f"user:{CANONICAL_LOCAL_USER}"


async def aggregate_interests(
    store: Any,
    *,
    l1_store: Any,
    entity_id: str = _DEFAULT_USER_ENTITY_ID,
    entity_type: str = "user",
    min_observations: int = 3,
) -> dict[str, int]:
    """Aggregate repeated INTERESTED_IN edges into recent profile assertions.

    Idempotent — safe to call on a schedule or as a maintenance step.

    Args:
        store: An ``L2CognitionStore`` instance.
        l1_store: Canonical L1 store used to load original evidence timestamps.
        entity_id: Subject of the INTERESTED_IN edges.
        entity_type: Entity type for the written assertion (default: ``"user"``).
        min_observations: Minimum edge observation count to qualify. Edges with
            fewer than this many observations are skipped.

    Returns:
        Stats dict with keys:
            - ``edges_seen``: total INTERESTED_IN edges found (any count)
            - ``topics_aggregated``: edges that met min_observations threshold
    """
    stats = await evaluate_graph_derived_assertion_rule(
        store,
        builtin_interest_rule(min_observations=min_observations),
        l1_store=l1_store,
        entity_id=entity_id,
        entity_type=entity_type,
    )
    topics_aggregated = stats.get("assertions_written", 0)
    logger.info(
        "aggregate_interests: completed",
        entity_id=entity_id,
        edges_seen=stats.get("edges_seen", 0),
        topics_aggregated=topics_aggregated,
        min_observations=min_observations,
    )
    return {"edges_seen": stats.get("edges_seen", 0), "topics_aggregated": topics_aggregated}
