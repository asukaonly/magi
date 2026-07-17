"""Durable governance for user-forgotten memory claims and evidence."""

from __future__ import annotations

import json
import math
import uuid
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import aiosqlite

from .evidence_ledger import claim_evidence_event_ids, normalize_evidence_timestamp
from .models import CorrectionTargetKind
from ...source_event_governance import (
    govern_source_events_by_time_range,
    promote_source_event_entity_projection_candidates,
    source_event_entity_projection_block_ids,
    source_event_time_range_block_ids,
    source_event_tombstone_ids,
)


@dataclass(frozen=True)
class ForgottenClaim:
    """One stored claim captured before a forget operation mutates its row."""

    record_id: str
    claim_fingerprint: str
    semantic_fingerprint: str
    evidence_event_ids: tuple[str, ...]
    evidence_fail_closed: bool
    subject_keys: tuple[str, ...] = ()
    correction_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaimGovernanceIdentityRewrite:
    """Move durable governance from one claim identity to another."""

    old_claim_fingerprint: str
    new_claim_fingerprint: str
    new_semantic_fingerprint: str


@dataclass(frozen=True)
class FilteredCandidateEvidence:
    """Evidence remaining after durable forget rules are applied per event."""

    retained_event_ids: tuple[str, ...]
    forgotten_by_rule: Mapping[str, tuple[str, ...]]
    tombstoned_event_ids: tuple[str, ...]
    normalized_timestamps: Mapping[str, float]
    resolved_timestamps: Mapping[str, float]
    fallback_observed_at: float
    fallback_observed_from: float
    fallback_observed_to: float

    @property
    def blocking_rule_id(self) -> str | None:
        """Return one governing rule when the candidate lost evidence."""
        return next(iter(self.forgotten_by_rule), None)

    @property
    def has_forgotten_evidence(self) -> bool:
        """Return whether claim or global event governance removed evidence."""
        return bool(self.forgotten_by_rule or self.tombstoned_event_ids)

    @property
    def retained_observation_bounds(self) -> tuple[float, float] | None:
        """Return safe visible bounds contributed only by retained evidence."""
        timestamps = [
            self.resolved_timestamps[event_id]
            for event_id in self.retained_event_ids
            if event_id in self.resolved_timestamps
        ]
        if any(event_id not in self.resolved_timestamps for event_id in self.retained_event_ids):
            timestamps.extend((self.fallback_observed_from, self.fallback_observed_to))
        if not timestamps:
            return None
        return min(timestamps), max(timestamps)


async def filter_candidate_evidence_by_forget_rules(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    semantic_fingerprint: str,
    event_ids: Iterable[str],
    event_timestamps: Mapping[str, Any] | None,
    observed_at: float,
    observed_from: float | None = None,
    observed_to: float | None = None,
    entity_ids: Iterable[str] = (),
) -> FilteredCandidateEvidence:
    """Filter each candidate event using scope-independent durable forget rules."""
    normalized_event_ids = tuple(
        dict.fromkeys(str(event_id).strip() for event_id in event_ids if str(event_id).strip())
    )
    normalized_entity_ids = tuple(
        dict.fromkeys(str(entity_id).strip() for entity_id in entity_ids if str(entity_id).strip())
    )
    fallback_observed_at = normalize_evidence_timestamp(observed_at, fallback=0.0)
    fallback_from = normalize_evidence_timestamp(observed_from, fallback=fallback_observed_at)
    fallback_to = normalize_evidence_timestamp(observed_to, fallback=fallback_observed_at)
    fallback_interval = (min(fallback_from, fallback_to), max(fallback_from, fallback_to))
    resolved_timestamps = {
        event_id: timestamp
        for event_id in normalized_event_ids
        if (timestamp := _finite_optional_timestamp((event_timestamps or {}).get(event_id)))
        is not None
    }
    normalized_timestamps = {
        event_id: resolved_timestamps.get(event_id, fallback_observed_at)
        for event_id in normalized_event_ids
    }
    for event_id in normalized_event_ids:
        if event_id in resolved_timestamps:
            await govern_source_events_by_time_range(
                db,
                event_ids=(event_id,),
                observed_from=resolved_timestamps[event_id],
            )
        else:
            await govern_source_events_by_time_range(
                db,
                event_ids=(event_id,),
                observed_from=fallback_interval[0],
                observed_to=fallback_interval[1],
            )
    globally_blocked_event_ids = await source_event_tombstone_ids(
        db,
        normalized_event_ids,
    )
    globally_blocked_event_ids.update(
        await source_event_time_range_block_ids(db, normalized_event_ids)
    )
    await promote_source_event_entity_projection_candidates(
        db,
        normalized_event_ids,
        entity_ids=normalized_entity_ids,
    )
    globally_blocked_event_ids.update(
        await source_event_entity_projection_block_ids(
            db,
            normalized_event_ids,
            entity_ids=normalized_entity_ids,
        )
    )
    if not normalized_event_ids or not str(semantic_fingerprint).strip():
        return FilteredCandidateEvidence(
            retained_event_ids=tuple(
                event_id
                for event_id in normalized_event_ids
                if event_id not in globally_blocked_event_ids
            ),
            forgotten_by_rule={},
            tombstoned_event_ids=tuple(
                event_id
                for event_id in normalized_event_ids
                if event_id in globally_blocked_event_ids
            ),
            normalized_timestamps=normalized_timestamps,
            resolved_timestamps=resolved_timestamps,
            fallback_observed_at=fallback_observed_at,
            fallback_observed_from=fallback_interval[0],
            fallback_observed_to=fallback_interval[1],
        )

    async with db.execute(
        """
        SELECT rules.rule_id, rules.forget_kind, rules.effective_from,
               rules.effective_to,
               COALESCE((
                   SELECT json_group_array(evidence.event_id)
                   FROM memory_forget_evidence_events AS evidence
                   WHERE evidence.rule_id = rules.rule_id
               ), '[]') AS forgotten_event_ids
        FROM memory_forget_claim_rules AS rules
        WHERE rules.target_kind = ? AND rules.semantic_fingerprint = ?
        ORDER BY CASE rules.forget_kind WHEN 'entity' THEN 0 ELSE 1 END,
                 rules.created_at DESC, rules.rule_id DESC
        """,
        (target_kind.value, str(semantic_fingerprint).strip()),
    ) as cursor:
        rows = await cursor.fetchall()

    rules: list[tuple[str, str, float | None, float | None, set[str]]] = []
    for row in rows:
        try:
            forgotten_ids = {
                str(event_id)
                for event_id in json.loads(str(row[4] or "[]"))
                if str(event_id).strip()
            }
        except (TypeError, json.JSONDecodeError):
            forgotten_ids = set()
        effective_from = _finite_optional_timestamp(row[2])
        effective_to = _finite_optional_timestamp(row[3])
        rules.append((str(row[0]), str(row[1]), effective_from, effective_to, forgotten_ids))

    retained: list[str] = []
    forgotten_by_rule: dict[str, list[str]] = {}
    for event_id in normalized_event_ids:
        if event_id in globally_blocked_event_ids:
            continue
        event_time = normalized_timestamps[event_id]
        event_interval = (
            (event_time, event_time) if event_id in resolved_timestamps else fallback_interval
        )
        matched_rule_id: str | None = None
        for rule_id, forget_kind, effective_from, effective_to, forgotten_ids in rules:
            if forget_kind == "entity" or event_id in forgotten_ids:
                matched_rule_id = rule_id
                break
            if (
                forget_kind == "time_range"
                and effective_from is not None
                and effective_to is not None
                and event_interval[0] <= effective_to
                and event_interval[1] >= effective_from
            ):
                matched_rule_id = rule_id
                break
        if matched_rule_id is None:
            retained.append(event_id)
        else:
            forgotten_by_rule.setdefault(matched_rule_id, []).append(event_id)

    return FilteredCandidateEvidence(
        retained_event_ids=tuple(retained),
        forgotten_by_rule={
            rule_id: tuple(rule_event_ids) for rule_id, rule_event_ids in forgotten_by_rule.items()
        },
        tombstoned_event_ids=tuple(
            event_id for event_id in normalized_event_ids if event_id in globally_blocked_event_ids
        ),
        normalized_timestamps=normalized_timestamps,
        resolved_timestamps=resolved_timestamps,
        fallback_observed_at=fallback_observed_at,
        fallback_observed_from=fallback_interval[0],
        fallback_observed_to=fallback_interval[1],
    )


async def forgotten_evidence_event_ids_for_claims(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    claim_fingerprints: Iterable[str],
) -> set[str]:
    """Return durable forgotten event identities for a bounded claim set."""
    normalized = list(
        dict.fromkeys(
            str(fingerprint).strip()
            for fingerprint in claim_fingerprints
            if str(fingerprint).strip()
        )
    )
    if not normalized:
        return set()
    candidate_json = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    async with db.execute(
        """
        SELECT DISTINCT evidence.event_id
        FROM memory_forget_claim_rules AS rules
        JOIN memory_forget_evidence_events AS evidence
          ON evidence.rule_id = rules.rule_id
        WHERE rules.target_kind = ?
          AND rules.claim_fingerprint IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        ORDER BY evidence.event_id
        """,
        (target_kind.value, candidate_json),
    ) as cursor:
        return {str(row[0]) for row in await cursor.fetchall()}


def _finite_optional_timestamp(value: Any) -> float | None:
    if value is None:
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return timestamp if math.isfinite(timestamp) else None


def decode_evidence_event_ids(value: Any) -> tuple[tuple[str, ...], bool]:
    """Decode legacy evidence shapes without silently weakening privacy."""
    parsed = value
    for _ in range(2):
        if not isinstance(parsed, str):
            break
        try:
            parsed = json.loads(parsed)
        except json.JSONDecodeError:
            return (), True
    if parsed is None:
        return (), False
    if not isinstance(parsed, (list, tuple, set)):
        return (), True
    if any(not isinstance(event_id, str) or not event_id.strip() for event_id in parsed):
        return (), True
    return tuple(dict.fromkeys(event_id.strip() for event_id in parsed)), False


async def record_forget_claim_rules(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    claims: Mapping[str, ForgottenClaim],
    forget_kind: str,
    effective_from: float | None,
    effective_to: float | None,
    created_at: float,
    event_ids_by_record: Mapping[str, Iterable[str]] | None = None,
) -> dict[str, str]:
    """Persist claim and evidence barriers, returning record-to-rule identities."""
    if forget_kind not in {"entity", "time_range", "event"}:
        raise ValueError(f"Unsupported forget kind: {forget_kind}")
    if forget_kind == "time_range" and (
        effective_from is None
        or effective_to is None
        or float(effective_to) <= float(effective_from)
    ):
        raise ValueError("Time-range forget governance requires a valid range")
    if forget_kind == "event" and (effective_from is not None or effective_to is not None):
        raise ValueError("Event forget governance does not accept a time range")

    rule_ids: dict[str, str] = {}
    for record_id, claim in claims.items():
        fingerprint = str(claim.claim_fingerprint).strip()
        if not fingerprint:
            fingerprint = f"forgotten_record:{target_kind.value}:{record_id}"
        semantic_fingerprint = str(claim.semantic_fingerprint).strip() or fingerprint
        rule_id = forget_rule_id(
            target_kind=target_kind,
            claim_fingerprint=fingerprint,
            forget_kind=forget_kind,
            effective_from=effective_from,
            effective_to=effective_to,
        )
        await db.execute(
            """
            INSERT INTO memory_forget_claim_rules(
                rule_id, target_kind, claim_fingerprint, semantic_fingerprint, forget_kind,
                effective_from, effective_to, evidence_fail_closed, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id) DO UPDATE SET
                evidence_fail_closed = MAX(
                    memory_forget_claim_rules.evidence_fail_closed,
                    excluded.evidence_fail_closed
                ),
                created_at = MIN(memory_forget_claim_rules.created_at, excluded.created_at)
            """,
            (
                rule_id,
                target_kind.value,
                fingerprint,
                semantic_fingerprint,
                forget_kind,
                effective_from,
                effective_to,
                int(claim.evidence_fail_closed),
                created_at,
            ),
        )
        if forget_kind == "entity":
            await append_forget_evidence_event_ids(
                db,
                rule_id=rule_id,
                event_ids=claim.evidence_event_ids,
                created_at=created_at,
            )
        if forget_kind == "event":
            ledger_event_ids = tuple((event_ids_by_record or {}).get(str(record_id), ()))
        else:
            ledger_event_ids = await claim_evidence_event_ids(
                db,
                target_kind=target_kind,
                claim_fingerprint=fingerprint,
                observed_from=effective_from if forget_kind == "time_range" else None,
                observed_to=effective_to if forget_kind == "time_range" else None,
            )
        await append_forget_evidence_event_ids(
            db,
            rule_id=rule_id,
            event_ids=ledger_event_ids,
            created_at=created_at,
        )
        rule_ids[str(record_id)] = rule_id
    return rule_ids


async def append_forget_evidence_event_ids(
    db: aiosqlite.Connection,
    *,
    rule_id: str,
    event_ids: Iterable[str],
    created_at: float,
) -> None:
    """Attach replayed evidence to the forget rule that blocked it."""
    normalized = list(
        dict.fromkeys(str(event_id).strip() for event_id in event_ids if str(event_id).strip())
    )
    if not normalized:
        return
    await db.executemany(
        """
        INSERT OR IGNORE INTO memory_forget_evidence_events(
            rule_id, event_id, created_at
        ) VALUES (?, ?, ?)
        """,
        [(rule_id, event_id, created_at) for event_id in normalized],
    )


async def matching_forget_rule_id(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    semantic_fingerprint: str,
    observed_at: float,
) -> str | None:
    """Return the strongest forget rule that governs one candidate claim."""
    async with db.execute(
        """
        SELECT rule_id
        FROM memory_forget_claim_rules
        WHERE target_kind = ? AND semantic_fingerprint = ?
          AND (
              forget_kind = 'entity'
              OR (
                  forget_kind = 'time_range'
                  AND effective_from IS NOT NULL
                  AND effective_to IS NOT NULL
                  AND effective_from <= ?
                  AND effective_to >= ?
              )
          )
        ORDER BY CASE forget_kind WHEN 'entity' THEN 0 ELSE 1 END,
                 created_at DESC, rule_id DESC
        LIMIT 1
        """,
        (target_kind.value, semantic_fingerprint, observed_at, observed_at),
    ) as cursor:
        row = await cursor.fetchone()
    return str(row[0]) if row is not None else None


async def link_correction_forget_barrier(
    db: aiosqlite.Connection,
    *,
    correction_id: str,
    rule_ids: Iterable[str],
    created_at: float,
) -> None:
    """Bind a correction to immutable forget rules that touched its lineage."""
    normalized = list(dict.fromkeys(str(rule_id) for rule_id in rule_ids if str(rule_id)))
    if not normalized:
        return
    await db.executemany(
        """
        INSERT OR IGNORE INTO memory_correction_forget_barriers(
            correction_id, rule_id, created_at
        ) VALUES (?, ?, ?)
        """,
        [(correction_id, rule_id, created_at) for rule_id in normalized],
    )


async def correction_has_forget_barrier(
    db: aiosqlite.Connection,
    correction_id: str,
) -> bool:
    """Return whether reverting a correction would cross a forget boundary."""
    async with db.execute(
        """
        SELECT 1
        FROM memory_correction_forget_barriers
        WHERE correction_id = ?
        LIMIT 1
        """,
        (correction_id,),
    ) as cursor:
        return await cursor.fetchone() is not None


async def rewrite_claim_governance_identities(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    rewrites: Iterable[ClaimGovernanceIdentityRewrite],
) -> None:
    """Merge durable forget and evidence state after claim identity changes."""
    for rewrite in _normalized_identity_rewrites(rewrites):
        await _rewrite_forget_rules(
            db,
            target_kind=target_kind,
            rewrite=rewrite,
        )
        await _rewrite_claim_evidence_ledger(
            db,
            target_kind=target_kind,
            rewrite=rewrite,
        )


async def forget_rules_for_claims(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    claim_fingerprints: Iterable[str],
) -> dict[str, list[dict[str, Any]]]:
    """Load all durable forget intervals for a bounded set of claims."""
    normalized = list(
        dict.fromkeys(
            str(fingerprint).strip()
            for fingerprint in claim_fingerprints
            if str(fingerprint).strip()
        )
    )
    if not normalized:
        return {}
    candidate_json = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """
        SELECT rules.rule_id, rules.claim_fingerprint, rules.forget_kind,
               rules.effective_from, rules.effective_to, rules.created_at,
               COALESCE((
                   SELECT json_group_array(evidence.event_id)
                   FROM memory_forget_evidence_events AS evidence
                   WHERE evidence.rule_id = rules.rule_id
               ), '[]') AS forgotten_event_ids
        FROM memory_forget_claim_rules AS rules
        WHERE rules.target_kind = ?
          AND rules.claim_fingerprint IN (
              SELECT CAST(value AS TEXT) FROM json_each(?)
          )
        ORDER BY rules.created_at, rules.rule_id
        """,
        (target_kind.value, candidate_json),
    ) as cursor:
        rows = await cursor.fetchall()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        item = dict(row)
        item["forgotten_event_ids"] = tuple(
            str(event_id) for event_id in json.loads(str(item["forgotten_event_ids"] or "[]"))
        )
        grouped.setdefault(str(row["claim_fingerprint"]), []).append(item)
    return grouped


def forget_rule_id(
    *,
    target_kind: CorrectionTargetKind,
    claim_fingerprint: str,
    forget_kind: str,
    effective_from: float | None,
    effective_to: float | None,
) -> str:
    payload = json.dumps(
        {
            "target_kind": target_kind.value,
            "claim_fingerprint": claim_fingerprint,
            "forget_kind": forget_kind,
            "effective_from": effective_from,
            "effective_to": effective_to,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"forget_rule_{uuid.uuid5(uuid.NAMESPACE_URL, payload).hex}"


def _normalized_identity_rewrites(
    rewrites: Iterable[ClaimGovernanceIdentityRewrite],
) -> tuple[ClaimGovernanceIdentityRewrite, ...]:
    by_old: dict[str, ClaimGovernanceIdentityRewrite] = {}
    for rewrite in rewrites:
        old_fingerprint = str(rewrite.old_claim_fingerprint).strip()
        new_fingerprint = str(rewrite.new_claim_fingerprint).strip()
        semantic_fingerprint = str(rewrite.new_semantic_fingerprint).strip()
        if not old_fingerprint or not new_fingerprint or not semantic_fingerprint:
            continue
        normalized = ClaimGovernanceIdentityRewrite(
            old_claim_fingerprint=old_fingerprint,
            new_claim_fingerprint=new_fingerprint,
            new_semantic_fingerprint=semantic_fingerprint,
        )
        existing = by_old.get(old_fingerprint)
        if existing is not None and existing != normalized:
            raise ValueError(
                "One claim identity cannot be rewritten to multiple destinations: "
                f"{existing!r} != {normalized!r}"
            )
        by_old[old_fingerprint] = normalized

    destinations = {old: item.new_claim_fingerprint for old, item in by_old.items()}
    resolved: list[ClaimGovernanceIdentityRewrite] = []
    for old_fingerprint, rewrite in by_old.items():
        destination = rewrite.new_claim_fingerprint
        visited = {old_fingerprint}
        while destination in destinations and destinations[destination] != destination:
            if destination in visited:
                raise ValueError("Claim identity rewrites contain a cycle")
            visited.add(destination)
            destination = destinations[destination]
        terminal = by_old.get(destination)
        resolved.append(
            ClaimGovernanceIdentityRewrite(
                old_claim_fingerprint=old_fingerprint,
                new_claim_fingerprint=destination,
                new_semantic_fingerprint=(
                    terminal.new_semantic_fingerprint
                    if terminal is not None
                    else rewrite.new_semantic_fingerprint
                ),
            )
        )
    return tuple(
        sorted(
            resolved,
            key=lambda item: (
                item.old_claim_fingerprint == item.new_claim_fingerprint,
                item.old_claim_fingerprint,
            ),
        )
    )


async def _rewrite_forget_rules(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    rewrite: ClaimGovernanceIdentityRewrite,
) -> None:
    db.row_factory = aiosqlite.Row
    async with db.execute(
        """
        SELECT * FROM memory_forget_claim_rules
        WHERE target_kind = ? AND claim_fingerprint = ?
        ORDER BY created_at, rule_id
        """,
        (target_kind.value, rewrite.old_claim_fingerprint),
    ) as cursor:
        rules = await cursor.fetchall()
    for rule in rules:
        new_rule_id = forget_rule_id(
            target_kind=target_kind,
            claim_fingerprint=rewrite.new_claim_fingerprint,
            forget_kind=str(rule["forget_kind"]),
            effective_from=(
                float(rule["effective_from"]) if rule["effective_from"] is not None else None
            ),
            effective_to=(
                float(rule["effective_to"]) if rule["effective_to"] is not None else None
            ),
        )
        if str(rule["rule_id"]) == new_rule_id:
            await db.execute(
                """
                UPDATE memory_forget_claim_rules
                SET claim_fingerprint = ?, semantic_fingerprint = ?
                WHERE rule_id = ?
                """,
                (
                    rewrite.new_claim_fingerprint,
                    rewrite.new_semantic_fingerprint,
                    new_rule_id,
                ),
            )
            continue
        await db.execute(
            """
            INSERT INTO memory_forget_claim_rules(
                rule_id, target_kind, claim_fingerprint, semantic_fingerprint,
                forget_kind, effective_from, effective_to,
                evidence_fail_closed, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id) DO UPDATE SET
                semantic_fingerprint = excluded.semantic_fingerprint,
                evidence_fail_closed = MAX(
                    memory_forget_claim_rules.evidence_fail_closed,
                    excluded.evidence_fail_closed
                ),
                created_at = MIN(
                    memory_forget_claim_rules.created_at,
                    excluded.created_at
                )
            """,
            (
                new_rule_id,
                target_kind.value,
                rewrite.new_claim_fingerprint,
                rewrite.new_semantic_fingerprint,
                rule["forget_kind"],
                rule["effective_from"],
                rule["effective_to"],
                rule["evidence_fail_closed"],
                rule["created_at"],
            ),
        )
        await db.execute(
            """
            INSERT INTO memory_forget_evidence_events(rule_id, event_id, created_at)
            SELECT ?, event_id, created_at
            FROM memory_forget_evidence_events
            WHERE rule_id = ?
            ON CONFLICT(rule_id, event_id) DO UPDATE SET
                created_at = MIN(
                    memory_forget_evidence_events.created_at,
                    excluded.created_at
                )
            """,
            (new_rule_id, rule["rule_id"]),
        )
        await db.execute(
            """
            INSERT INTO memory_correction_forget_barriers(
                correction_id, rule_id, created_at
            )
            SELECT correction_id, ?, created_at
            FROM memory_correction_forget_barriers
            WHERE rule_id = ?
            ON CONFLICT(correction_id, rule_id) DO UPDATE SET
                created_at = MIN(
                    memory_correction_forget_barriers.created_at,
                    excluded.created_at
                )
            """,
            (new_rule_id, rule["rule_id"]),
        )
        await db.execute(
            "DELETE FROM memory_forget_claim_rules WHERE rule_id = ?",
            (rule["rule_id"],),
        )


async def _rewrite_claim_evidence_ledger(
    db: aiosqlite.Connection,
    *,
    target_kind: CorrectionTargetKind,
    rewrite: ClaimGovernanceIdentityRewrite,
) -> None:
    if rewrite.old_claim_fingerprint == rewrite.new_claim_fingerprint:
        return
    await db.execute(
        """
        INSERT INTO memory_claim_evidence_events(
            target_kind, claim_fingerprint, event_id, observed_at,
            observed_from, observed_to, observed_at_is_approximate, created_at
        )
        SELECT target_kind, ?, event_id, observed_at,
               observed_from, observed_to, observed_at_is_approximate, created_at
        FROM memory_claim_evidence_events
        WHERE target_kind = ? AND claim_fingerprint = ?
        ON CONFLICT(target_kind, claim_fingerprint, event_id) DO UPDATE SET
            observed_at = CASE
                WHEN memory_claim_evidence_events.observed_at_is_approximate = 1
                     AND excluded.observed_at_is_approximate = 0
                THEN excluded.observed_at
                WHEN memory_claim_evidence_events.observed_at_is_approximate = 0
                     AND excluded.observed_at_is_approximate = 1
                THEN memory_claim_evidence_events.observed_at
                ELSE MIN(memory_claim_evidence_events.observed_at, excluded.observed_at)
            END,
            observed_from = CASE
                WHEN memory_claim_evidence_events.observed_at_is_approximate = 1
                     AND excluded.observed_at_is_approximate = 0
                THEN excluded.observed_from
                WHEN memory_claim_evidence_events.observed_at_is_approximate = 0
                     AND excluded.observed_at_is_approximate = 1
                THEN memory_claim_evidence_events.observed_from
                ELSE MIN(memory_claim_evidence_events.observed_from, excluded.observed_from)
            END,
            observed_to = CASE
                WHEN memory_claim_evidence_events.observed_at_is_approximate = 1
                     AND excluded.observed_at_is_approximate = 0
                THEN excluded.observed_to
                WHEN memory_claim_evidence_events.observed_at_is_approximate = 0
                     AND excluded.observed_at_is_approximate = 1
                THEN memory_claim_evidence_events.observed_to
                ELSE MAX(memory_claim_evidence_events.observed_to, excluded.observed_to)
            END,
            observed_at_is_approximate = MIN(
                memory_claim_evidence_events.observed_at_is_approximate,
                excluded.observed_at_is_approximate
            ),
            created_at = MIN(
                memory_claim_evidence_events.created_at,
                excluded.created_at
            )
        """,
        (
            rewrite.new_claim_fingerprint,
            target_kind.value,
            rewrite.old_claim_fingerprint,
        ),
    )
    await db.execute(
        """
        DELETE FROM memory_claim_evidence_events
        WHERE target_kind = ? AND claim_fingerprint = ?
        """,
        (target_kind.value, rewrite.old_claim_fingerprint),
    )


__all__ = [
    "ClaimGovernanceIdentityRewrite",
    "FilteredCandidateEvidence",
    "ForgottenClaim",
    "append_forget_evidence_event_ids",
    "correction_has_forget_barrier",
    "decode_evidence_event_ids",
    "link_correction_forget_barrier",
    "forget_rules_for_claims",
    "forget_rule_id",
    "filter_candidate_evidence_by_forget_rules",
    "forgotten_evidence_event_ids_for_claims",
    "matching_forget_rule_id",
    "record_forget_claim_rules",
    "rewrite_claim_governance_identities",
]
