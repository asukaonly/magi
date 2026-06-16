"""Aggregate high-frequency INTERESTED_IN knowledge-graph edges into inferred
``preference_profile`` assertions on the user portrait.

This fills the gap where ``INTERESTED_IN`` edges (produced by behavioral
sensors such as chrome_history) never reached the snapshot, whereas
``LIKES``/``DISLIKES`` do via ``_add_relation_preferences``.

Design:
- Reads ``INTERESTED_IN`` edges for ``entity_id`` with ``observation_count >=
  min_observations`` (default 3).
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
- Passing ``evidence_events=edge["evidence_event_ids"]`` allows the assertion
  state machine to advance to ``corroborated`` (≥2 events) immediately, making
  the assertion visible in ``refresh_entity_snapshot``.
- Idempotent: calling twice merges evidence and keeps a single live row.
"""

from __future__ import annotations

import re
from typing import Any

from ....core.logger import get_logger
from ..entities.catalog.lookup import get_canonical_names

logger = get_logger(__name__)

_TOPIC_PREFIX = "topic:"


def _topic_slug(object_id: str) -> str:
    """Strip the ``topic:`` prefix to get a stable, unique slug."""
    if object_id.startswith(_TOPIC_PREFIX):
        return object_id[len(_TOPIC_PREFIX):]
    return object_id


def _safe_slug(slug: str) -> str:
    """Return a filesystem/key-safe slug (lower, alnum+hyphen/underscore)."""
    return re.sub(r"[^a-z0-9_-]", "_", slug.lower())


async def aggregate_interests(
    store: Any,
    *,
    entity_id: str = "user:self",
    entity_type: str = "user",
    min_observations: int = 3,
) -> dict[str, int]:
    """Aggregate INTERESTED_IN edges (observation_count >= min_observations)
    into inferred ``preference_profile`` assertions.

    Idempotent — safe to call on a schedule or as a maintenance step.

    Args:
        store: An ``L2CognitionStore`` instance.
        entity_id: Subject of the INTERESTED_IN edges (default: ``"user:self"``).
        entity_type: Entity type for the written assertion (default: ``"user"``).
        min_observations: Minimum edge observation count to qualify. Edges with
            fewer than this many observations are skipped.

    Returns:
        Stats dict with keys:
            - ``edges_seen``: total INTERESTED_IN edges found (any count)
            - ``topics_aggregated``: edges that met min_observations threshold
    """
    await store.initialize()

    # -- 1. Fetch all active INTERESTED_IN edges for this entity --------------
    edges: list[dict[str, Any]] = await store.get_relationships(
        subject_id=entity_id,
        predicates=["INTERESTED_IN"],
        status="active",
        limit=500,
    )

    edges_seen = len(edges)

    # -- 2. Filter to high-frequency edges ------------------------------------
    qualifying = [e for e in edges if int(e.get("observation_count", 0)) >= min_observations]

    if not qualifying:
        logger.debug(
            "aggregate_interests: no qualifying edges",
            entity_id=entity_id,
            edges_seen=edges_seen,
            min_observations=min_observations,
        )
        return {"edges_seen": edges_seen, "topics_aggregated": 0}

    # -- 3. Batch-resolve canonical names from entity_catalog -----------------
    object_ids = [e["object_id"] for e in qualifying]
    canonical_names: dict[str, str] = await get_canonical_names(store.db_path, object_ids)

    # -- 4. Build and persist one assertion per qualifying topic --------------
    topics_aggregated = 0
    for edge in qualifying:
        object_id: str = edge["object_id"]
        object_type: str = edge.get("object_type") or "topic"
        raw_slug = _topic_slug(object_id)
        slug = _safe_slug(raw_slug)
        canonical_name = canonical_names.get(object_id, raw_slug)

        # Confidence derivation: base from edge confidence, boosted by
        # observation count (capped at 5 extra observations → +0.5, max 0.9).
        obs_count = int(edge.get("observation_count", 1))
        confidence_score = min(0.9, float(edge.get("confidence", 0.5)) * (1 + 0.1 * min(obs_count, 5)))

        evidence_events: list[str] = list(edge.get("evidence_event_ids") or [])

        candidate: dict[str, Any] = {
            "entity_id": entity_id,
            "entity_type": entity_type,
            "trait_family": "preference_profile",
            "trait_name": f"interest.{slug}",
            "trait_value": canonical_name,
            "confidence_score": confidence_score,
            "evidence_events": evidence_events,
            "volatility_index": 0.2,
            "source_domain": "external_activity",
            "inference_depth": "topology_only",
            "validation_state": "tentative",
            "first_inferred_at": float(edge.get("first_observed_at", 0)),
            "last_validated_at": float(edge.get("last_observed_at", 0)),
            "target_entity_id": object_id,
            "target_entity_type": object_type,
            "target_scope": "entity_bound",
            "temporal_scope": "stable",
            "decay_policy": "evidence_only",
            "natural_summary": f"Recurring interest in {canonical_name}",
        }

        await store.upsert_assertion_candidate(candidate)
        topics_aggregated += 1
        logger.debug(
            "aggregate_interests: wrote assertion",
            entity_id=entity_id,
            trait_name=candidate["trait_name"],
            canonical_name=canonical_name,
            observation_count=obs_count,
            evidence_count=len(evidence_events),
            confidence_score=round(confidence_score, 4),
        )

    logger.info(
        "aggregate_interests: completed",
        entity_id=entity_id,
        edges_seen=edges_seen,
        topics_aggregated=topics_aggregated,
        min_observations=min_observations,
    )
    return {"edges_seen": edges_seen, "topics_aggregated": topics_aggregated}
