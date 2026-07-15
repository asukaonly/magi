"""Fast write-time evaluation of durable user correction rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

import aiosqlite

from .models import CorrectionRuleKind, CorrectionTargetKind


class CorrectionPolicyAction(str, Enum):
    ACCEPT_ACTIVE = "accept_active"
    ACCEPT_HISTORICAL = "accept_historical"
    CREATE_SHADOW = "create_shadow"
    BLOCKED_BY_CORRECTION = "blocked_by_correction"
    REQUIRES_SCOPE = "requires_scope"


@dataclass(frozen=True)
class CorrectionPolicyDecision:
    action: CorrectionPolicyAction
    correction_id: str | None = None
    target_id: str | None = None
    authoritative_target_id: str | None = None


class CorrectionPolicyEvaluator:
    """Resolve materialized correction rules without reinterpreting history."""

    async def evaluate_assertion(
        self,
        db: aiosqlite.Connection,
        candidate: Mapping[str, Any],
    ) -> CorrectionPolicyDecision:
        return await self._evaluate(
            db,
            candidate,
            target_kind=CorrectionTargetKind.ASSERTION,
        )

    async def evaluate_relationship(
        self,
        db: aiosqlite.Connection,
        candidate: Mapping[str, Any],
    ) -> CorrectionPolicyDecision:
        """Evaluate correction rules for one normalized relationship write."""
        return await self._evaluate(
            db,
            candidate,
            target_kind=CorrectionTargetKind.EDGE,
        )

    async def _evaluate(
        self,
        db: aiosqlite.Connection,
        candidate: Mapping[str, Any],
        *,
        target_kind: CorrectionTargetKind,
    ) -> CorrectionPolicyDecision:
        slot_key = str(candidate["slot_key"])
        claim_fingerprint = str(candidate["claim_fingerprint"])
        scope_key = str(candidate.get("scope_key") or "global")
        observed_at = float(candidate.get("last_validated_at") or 0.0)
        rules = await _active_rules_for_slot(
            db,
            target_kind=target_kind,
            slot_key=slot_key,
        )

        for rule in rules:
            if (
                rule["rule_kind"] == CorrectionRuleKind.BLOCK_CLAIM.value
                and rule["claim_fingerprint"] == claim_fingerprint
            ):
                return _decision(
                    CorrectionPolicyAction.BLOCKED_BY_CORRECTION,
                    rule,
                )

        if scope_key == "global":
            scope_rule = next(
                (
                    rule
                    for rule in rules
                    if rule["rule_kind"] == CorrectionRuleKind.SCOPE_ONLY.value
                ),
                None,
            )
            if scope_rule is not None:
                return _decision(CorrectionPolicyAction.REQUIRES_SCOPE, scope_rule)

        for rule in rules:
            if rule["rule_kind"] != CorrectionRuleKind.CLOSE_BEFORE.value:
                continue
            if rule["claim_fingerprint"] != claim_fingerprint:
                continue
            effective_to = rule["effective_to"]
            if effective_to is not None and observed_at <= float(effective_to):
                return _decision(CorrectionPolicyAction.ACCEPT_HISTORICAL, rule)

        authoritative_rule = next(
            (
                rule
                for rule in rules
                if rule["rule_kind"] == CorrectionRuleKind.AUTHORITATIVE_SLOT.value
                and str(rule["scope_key"] or "global") == scope_key
            ),
            None,
        )
        if authoritative_rule is None:
            return CorrectionPolicyDecision(CorrectionPolicyAction.ACCEPT_ACTIVE)
        if authoritative_rule["claim_fingerprint"] == claim_fingerprint:
            return _decision(CorrectionPolicyAction.ACCEPT_ACTIVE, authoritative_rule)
        return _decision(CorrectionPolicyAction.CREATE_SHADOW, authoritative_rule)


async def _active_rules_for_slot(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    slot_key: str,
) -> list[dict[str, Any]]:
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """
        SELECT rules.*, corrections.target_id, corrections.replacement_target_id
        FROM memory_correction_rules AS rules
        JOIN memory_corrections AS corrections
          ON corrections.correction_id = rules.correction_id
        WHERE rules.target_kind = ? AND rules.slot_key = ? AND rules.active = 1
          AND corrections.state = 'active'
        ORDER BY rules.created_at DESC, rules.rule_id DESC
        """,
        (target_kind.value, slot_key),
    ) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


def _decision(
    action: CorrectionPolicyAction,
    rule: Mapping[str, Any],
) -> CorrectionPolicyDecision:
    return CorrectionPolicyDecision(
        action=action,
        correction_id=str(rule["correction_id"]),
        target_id=str(rule["target_id"]),
        authoritative_target_id=(
            str(rule["replacement_target_id"]) if rule.get("replacement_target_id") else None
        ),
    )


__all__ = [
    "CorrectionPolicyAction",
    "CorrectionPolicyDecision",
    "CorrectionPolicyEvaluator",
]
