"""Bounded serialization of validated shared post-turn analysis."""

from dataclasses import asdict
import json
from typing import Any

from magi.memory.l0.attention_update_scheduler import AttentionBatch
from .interaction_batch_analyzer import BatchInteractionAnalysis, parse_interaction_batch


def encode_interaction_analysis(analysis: BatchInteractionAnalysis, *, snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "attention_revision": int(snapshot.get("revision") or 0),
        "attention_base": list(snapshot.get("items") or []),
        "analysis": {
            "turns": [
                {"turn_id": key, "sentiment": value.sentiment, "engagement": value.engagement.value,
                 "complexity": value.complexity, "outcome": value.outcome_str,
                 "satisfaction": value.satisfaction.value, "trigger_type": value.trigger_type,
                 "milestone_keys": value.milestone_keys,
                 "memory_observations": [asdict(item) for item in value.memory_observations]}
                for key, value in analysis.turn_analyses.items()
            ],
            "attention_actions": [asdict(action) for action in analysis.attention_actions],
        },
    }


def decode_interaction_analysis(payload: dict[str, Any], *, batch: AttentionBatch) -> BatchInteractionAnalysis:
    raw = payload.get("analysis")
    base = payload.get("attention_base")
    if not isinstance(raw, dict) or not isinstance(base, list):
        raise ValueError("Stored post-turn analysis has an invalid shape")
    rows = raw.get("turns")
    if not isinstance(rows, list) or {row.get("turn_id") for row in rows if isinstance(row, dict)} != {turn.turn_id for turn in batch}:
        raise ValueError("Stored post-turn analysis does not match its frozen batch")
    result = parse_interaction_batch(json.dumps(raw), batch=batch, current_attention=base)
    if result is None:
        raise ValueError("Stored post-turn analysis could not be decoded")
    return result
