"""Deterministic identities for grounded Claims and projection outcomes."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any


def canonical_json(value: Any) -> str:
    """Serialize identity material without order or whitespace ambiguity."""

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def derive_claim_identity_key(
    *,
    extractor_contract_version: int,
    evidence_rule_version: int,
    user_id: str | None,
    subject_ref: str,
    subject_type: str,
    canonical_predicate: str,
    fact_kind: str,
    object_type: str,
    polarity: str,
    specificity: str,
    temporal_cue: str,
    fact_valid_from: float | None,
    fact_valid_to: float | None,
    target_from: float | None,
    target_to: float | None,
    raw_time_frame: Mapping[str, Any] | None,
    evidence_mode: str,
    object_surface: str | None,
    object_value: Any | None,
    supporting_event_ids: Iterable[str],
    antecedent_event_ids: Iterable[str],
) -> str:
    """Hash semantic Claim material and its normalized evidence occurrence set."""

    payload = {
        "extractor_contract_version": int(extractor_contract_version),
        "evidence_rule_version": int(evidence_rule_version),
        "user_id": str(user_id or ""),
        "subject_ref": str(subject_ref),
        "subject_type": str(subject_type),
        "canonical_predicate": str(canonical_predicate),
        "fact_kind": str(fact_kind),
        "object_type": str(object_type),
        "polarity": str(polarity),
        "specificity": str(specificity),
        "temporal_cue": str(temporal_cue),
        "fact_valid_from": fact_valid_from,
        "fact_valid_to": fact_valid_to,
        "target_from": target_from,
        "target_to": target_to,
        "raw_time_frame": raw_time_frame,
        "evidence_mode": str(evidence_mode),
        "object_surface": str(object_surface or ""),
        "object_value": object_value,
        "supporting_event_ids": sorted(
            {
                str(event_id).strip()
                for event_id in supporting_event_ids
                if str(event_id).strip()
            }
        ),
        "antecedent_event_ids": sorted(
            {
                str(event_id).strip()
                for event_id in antecedent_event_ids
                if str(event_id).strip()
            }
        ),
    }
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def projection_outcome_id(
    *,
    claim_id: str,
    attempt_key: str,
    target_kind: str,
    target_id: str,
) -> str:
    """Derive an idempotent identity for one target attempt result."""

    material: Mapping[str, str] = {
        "claim_id": str(claim_id),
        "attempt_key": str(attempt_key),
        "target_kind": str(target_kind),
        "target_id": str(target_id),
    }
    digest = hashlib.sha256(canonical_json(material).encode("utf-8")).hexdigest()
    return f"clo_{digest[:32]}"


__all__ = [
    "canonical_json",
    "derive_claim_identity_key",
    "projection_outcome_id",
]
