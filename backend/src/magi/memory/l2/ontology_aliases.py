"""Predicate canonicalization for L2 graph writes.

LLMs often emit slight variants of canonical predicate names (e.g. ``LISTENED``
instead of ``LISTENED_TO``). This module gives the pipeline a single place to
normalize them so the graph store does not fragment on synonyms.
"""

from __future__ import annotations

from typing import Any

from ...core.logger import get_logger
from .ontology import PREDICATE_REGISTRY, PROFILE_SIGNAL_PREDICATES

logger = get_logger(__name__)


PREDICATE_ALIASES: dict[str, str] = {
    "LISTEN_TO": "LISTENED",
    "LISTENED_TO": "LISTENED",
    "WATCHED": "VIEWED",
    "READ": "VIEWED",
    "BROWSED": "VIEWED",
    "VIEW": "VIEWED",
    "USE": "USES",
    "LIKE": "LIKES",
    "DISLIKE": "DISLIKES",
    "FOLLOW": "FOLLOWS",
    "OWN": "OWNS",
    "OWNED": "OWNS",
    "CREATED": "CREATES",
    "CREATE": "CREATES",
    "MODIFIED": "CREATES",
    "MODIFIES": "CREATES",
    "EDITED": "CREATES",
    "COMMITTED_TO": "COMMITTED",
    "INTERESTED": "INTERESTED_IN",
    "VISIT": "VISITED",
    "ATTENDED_TO": "ATTENDED",
    "WORKS_FOR": "WORKS_AT",
    "EMPLOYED_BY": "WORKS_AT",
    "MEMBER": "MEMBER_OF",
    "BELONGS_TO": "MEMBER_OF",
    "INTERACT_WITH": "INTERACTED_WITH",
    "KNOW": "KNOWS",
    "RELATED_TO": "FAMILY_OF",
    "PLAN_TO": "PLANS_TO",
    "PLANNED": "PLANS_TO",
    "WILL": "PLANS_TO",
    "SUBSCRIBED": "FOLLOWS",
    "SUBSCRIBED_TO": "FOLLOWS",
    "LOCATED": "LOCATED_IN",
    "LIVES": "LIVES_IN",
    "LOCATED_NEAR": "LIVES_IN",
    "PREFERRED_ADDRESS": "PREFERRED_FORM_OF_ADDRESS",
    "ADDRESS_PREFERRED": "PREFERRED_FORM_OF_ADDRESS",
    "PREFERRED_NAME": "PREFERRED_FORM_OF_ADDRESS",
    "CALL_ME": "PREFERRED_FORM_OF_ADDRESS",
    "DISALLOWED_ADDRESS": "DISALLOWED_FORM_OF_ADDRESS",
    "ADDRESS_DISALLOWED": "DISALLOWED_FORM_OF_ADDRESS",
    "DO_NOT_CALL_ME": "DISALLOWED_FORM_OF_ADDRESS",
    "NAME": "REAL_NAME",
    "BIRTHDAY": "BIRTH_DATE",
    "DATE_OF_BIRTH": "BIRTH_DATE",
    "BORN_ON": "BIRTH_DATE",
    "BORN_IN": "BIRTH_YEAR",
    "AGE": "STATED_AGE",
    "USER_AGE": "STATED_AGE",
    "COMMUNICATION_STYLE": "PREFERRED_COMMUNICATION_STYLE",
    "RESPONSE_STYLE": "PREFERRED_COMMUNICATION_STYLE",
}


def canonicalize_predicate(raw: Any) -> str | None:
    """Return the canonical predicate name, applying alias map.

    Unknown predicates are passed through unchanged (uppercased) so the system
    keeps long-tail signal; an info-level log is emitted so we can later
    promote frequent unknowns to either the registry or alias map.
    """
    if raw is None:
        return None
    text = str(raw).strip().replace(" ", "_")
    if not text:
        return None
    upper = text.upper()
    if upper in PREDICATE_ALIASES:
        return PREDICATE_ALIASES[upper]
    if upper in PREDICATE_REGISTRY:
        return upper
    if upper in PROFILE_SIGNAL_PREDICATES:
        return upper
    logger.info("L2 unknown predicate", predicate=upper, raw=str(raw))
    return upper


__all__ = ["PREDICATE_ALIASES", "canonicalize_predicate"]
