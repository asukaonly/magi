"""Fast write-time evaluation of durable user correction rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping

import aiosqlite

from .forget_governance import matching_forget_rule_id
from .models import CorrectionRuleKind, CorrectionTargetKind


class CorrectionPolicyAction(str, Enum):
    ACCEPT_ACTIVE = "accept_active"
    ACCEPT_HISTORICAL = "accept_historical"
    CREATE_SHADOW = "create_shadow"
    BLOCKED_BY_CORRECTION = "blocked_by_correction"
    BLOCKED_BY_FORGET = "blocked_by_forget"
    REQUIRES_SCOPE = "requires_scope"


CORRECTION_GOVERNED_EVIDENCE_ACTIONS = frozenset(
    {
        CorrectionPolicyAction.ACCEPT_HISTORICAL,
        CorrectionPolicyAction.BLOCKED_BY_CORRECTION,
        CorrectionPolicyAction.CREATE_SHADOW,
        CorrectionPolicyAction.REQUIRES_SCOPE,
    }
)


@dataclass(frozen=True)
class CorrectionPolicyDecision:
    action: CorrectionPolicyAction
    correction_id: str | None = None
    target_id: str | None = None
    authoritative_target_id: str | None = None
    forget_rule_id: str | None = None


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
        semantic_fingerprint = str(candidate.get("forget_fingerprint") or claim_fingerprint)
        scope_key = str(candidate.get("scope_key") or "global")
        observed_at = float(candidate.get("last_validated_at") or 0.0)
        forget_rule_id = None
        if not bool(candidate.get("forget_prechecked")):
            forget_rule_id = await matching_forget_rule_id(
                db,
                target_kind=target_kind,
                semantic_fingerprint=semantic_fingerprint,
                observed_at=observed_at,
            )
        if forget_rule_id is not None:
            return CorrectionPolicyDecision(
                CorrectionPolicyAction.BLOCKED_BY_FORGET,
                forget_rule_id=forget_rule_id,
            )
        all_rules = await _active_rules_for_slot(
            db,
            target_kind=target_kind,
            slot_key=slot_key,
        )
        rules = [rule for rule in all_rules if _rule_applies_at(rule, observed_at)]

        blocking_rule = next(
            (
                rule
                for rule in rules
                if rule["rule_kind"] == CorrectionRuleKind.BLOCK_CLAIM.value
                and rule["claim_fingerprint"] == claim_fingerprint
            ),
            None,
        )
        authoritative_rule = next(
            (
                rule
                for rule in rules
                if rule["rule_kind"] == CorrectionRuleKind.AUTHORITATIVE_SLOT.value
                and str(rule["scope_key"] or "global") == scope_key
            ),
            None,
        )
        if blocking_rule is not None:
            if (
                authoritative_rule is not None
                and authoritative_rule["claim_fingerprint"] == claim_fingerprint
                and _correction_precedes(authoritative_rule, blocking_rule)
            ):
                return _decision(
                    CorrectionPolicyAction.ACCEPT_ACTIVE,
                    authoritative_rule,
                )
            return _decision(
                CorrectionPolicyAction.BLOCKED_BY_CORRECTION,
                blocking_rule,
            )

        scope_rule = next(
            (
                rule
                for rule in rules
                if rule["rule_kind"] == CorrectionRuleKind.SCOPE_ONLY.value
                and rule["claim_fingerprint"] == claim_fingerprint
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
            return _decision(CorrectionPolicyAction.ACCEPT_HISTORICAL, rule)

        if authoritative_rule is None:
            scheduled_authority = next(
                (
                    rule
                    for rule in all_rules
                    if rule["correction_kind"] == "situation_changed"
                    and rule["rule_kind"] == CorrectionRuleKind.AUTHORITATIVE_SLOT.value
                    and str(rule["scope_key"] or "global") == scope_key
                    and rule["effective_from"] is not None
                    and observed_at < float(rule["effective_from"])
                ),
                None,
            )
            if scheduled_authority is not None:
                if scheduled_authority["claim_fingerprint"] == claim_fingerprint:
                    return _decision(
                        CorrectionPolicyAction.BLOCKED_BY_CORRECTION,
                        scheduled_authority,
                    )
                if target_kind == CorrectionTargetKind.ASSERTION:
                    return _decision(
                        CorrectionPolicyAction.BLOCKED_BY_CORRECTION,
                        scheduled_authority,
                    )
                return CorrectionPolicyDecision(CorrectionPolicyAction.ACCEPT_ACTIVE)
            return CorrectionPolicyDecision(CorrectionPolicyAction.ACCEPT_ACTIVE)
        if authoritative_rule["claim_fingerprint"] == claim_fingerprint:
            return _decision(CorrectionPolicyAction.ACCEPT_ACTIVE, authoritative_rule)
        return _decision(CorrectionPolicyAction.CREATE_SHADOW, authoritative_rule)


def _rule_applies_at(rule: Mapping[str, Any], observed_at: float) -> bool:
    effective_from = rule.get("effective_from")
    if effective_from is not None and observed_at < float(effective_from):
        return False
    effective_to = rule.get("effective_to")
    if effective_to is not None and observed_at >= float(effective_to):
        return False
    return True


async def _active_rules_for_slot(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    slot_key: str,
) -> list[dict[str, Any]]:
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """
        SELECT rules.*, corrections.target_id, corrections.replacement_target_id,
               corrections.correction_kind,
               corrections.created_at AS correction_created_at
        FROM memory_correction_rules AS rules
        JOIN memory_corrections AS corrections
          ON corrections.correction_id = rules.correction_id
        WHERE rules.target_kind = ? AND rules.slot_key = ? AND rules.active = 1
          AND corrections.state = 'active'
          AND corrections.transition_cancelled_at IS NULL
        ORDER BY corrections.created_at DESC, corrections.correction_id DESC,
                 rules.created_at DESC, rules.rule_id DESC
        """,
        (target_kind.value, slot_key),
    ) as cursor:
        return [dict(row) for row in await cursor.fetchall()]


def _correction_precedes(
    newer: Mapping[str, Any],
    older: Mapping[str, Any],
) -> bool:
    """Return whether one correction has durable precedence over another."""
    newer_key = (
        float(newer["correction_created_at"]),
        str(newer["correction_id"]),
    )
    older_key = (
        float(older["correction_created_at"]),
        str(older["correction_id"]),
    )
    return newer_key > older_key


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
    "CORRECTION_GOVERNED_EVIDENCE_ACTIONS",
    "CorrectionPolicyAction",
    "CorrectionPolicyDecision",
    "CorrectionPolicyEvaluator",
]
