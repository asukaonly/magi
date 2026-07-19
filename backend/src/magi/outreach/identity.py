"""Stable identity helpers for proactive outreach."""

from __future__ import annotations

import hashlib
import json

from .contracts import OutreachIntent


OUTREACH_PAYLOAD_METADATA_KEY = "_magi_outreach"


def canonical_intent_json(intent: OutreachIntent) -> str:
    """Serialize one intent deterministically for persistence and comparison."""

    return json.dumps(
        intent.to_dict(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def intent_fingerprint(intent: OutreachIntent) -> str:
    """Return a stable content identity for one outreach intent."""

    return hashlib.sha256(canonical_intent_json(intent).encode("utf-8")).hexdigest()


def stable_desktop_message_id(correlation_id: str) -> str:
    """Derive one transcript message identity from the logical outreach ID."""

    normalized = str(correlation_id or "").strip()
    if not normalized:
        raise ValueError("Outreach correlation ID is required")
    digest = hashlib.sha256(f"outreach:{normalized}".encode("utf-8")).hexdigest()
    return f"msg_outreach_{digest[:24]}"


def normalize_channel_scope(channel_type: str) -> str:
    """Normalize the external channel dimension used by delivery identity."""

    normalized = str(channel_type or "").strip().casefold()
    if not normalized:
        raise ValueError("Outreach channel scope is required")
    return normalized
