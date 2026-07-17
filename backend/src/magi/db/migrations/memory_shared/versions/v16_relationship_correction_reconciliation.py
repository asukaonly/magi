"""Reconcile reversible effects for legacy relationship corrections.

Revision ID: v16_relationship_correction_reconciliation
Revises: v15_correction_evidence_fail_closed
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from alembic import op

revision = "v16_relationship_correction_reconciliation"
down_revision = "v15_correction_evidence_fail_closed"
branch_labels = None
depends_on = None


class _ConflictRule:
    def __init__(
        self,
        *,
        opposite_predicates: tuple[str, ...] = (),
        opposite_resolution: str = "mark_deprecated",
        exclusive_group: str | None = None,
        exclusive_resolution: str = "mark_deprecated",
    ) -> None:
        self.opposite_predicates = opposite_predicates
        self.opposite_resolution = opposite_resolution
        self.exclusive_group = exclusive_group
        self.exclusive_resolution = exclusive_resolution


_DEFAULT_CONFLICT_RULES = {
    "LIKES": _ConflictRule(opposite_predicates=("DISLIKES",)),
    "DISLIKES": _ConflictRule(opposite_predicates=("LIKES",)),
    "CURRENT_WORKS_AT": _ConflictRule(exclusive_group="current_work"),
    "CURRENT_LIVES_IN": _ConflictRule(exclusive_group="current_residence"),
    "CURRENT_RELATIONSHIP_WITH": _ConflictRule(exclusive_group="current_relationship"),
}
_RECONCILED_EFFECT_PREFIX = "relationship_conflict_effect_reconciled_"


def upgrade() -> None:
    connection = op.get_bind().connection
    connection.execute("SAVEPOINT v16_relationship_correction_reconciliation")
    try:
        reconcile_legacy_relationship_corrections(connection, now=time.time())
    except Exception:
        connection.execute("ROLLBACK TO SAVEPOINT v16_relationship_correction_reconciliation")
        connection.execute("RELEASE SAVEPOINT v16_relationship_correction_reconciliation")
        raise
    connection.execute("RELEASE SAVEPOINT v16_relationship_correction_reconciliation")


def schema_sql_for_fresh_database() -> str:
    """Return no schema changes because this revision only repairs existing data."""
    return ""


def downgrade() -> None:
    raise RuntimeError("Relationship correction reconciliation cannot be downgraded safely")


def reconcile_legacy_relationship_corrections(
    connection: Any,
    *,
    now: float,
) -> None:
    """Replay active legacy corrections in their historical effective order."""
    rules = _load_conflict_rules(connection)
    exclusive_groups = _exclusive_group_index(rules)
    affected: dict[str, dict[str, set[str]]] = {}
    corrections = _row_dicts(
        connection,
        """
        SELECT correction_id, correction_kind, effective_at, created_at,
               replacement_target_id,
               CASE
                   WHEN correction_kind = 'situation_changed'
                       THEN COALESCE(effective_at, created_at)
                   ELSE created_at
               END AS replay_at
        FROM memory_corrections
        WHERE target_kind = 'edge'
          AND state = 'active'
          AND replacement_target_id IS NOT NULL
          AND replacement_target_id != ''
          AND (
              correction_kind != 'situation_changed'
              OR transition_applied_at IS NOT NULL
          )
        ORDER BY replay_at, created_at, correction_id
        """,
    )
    version_offset = _unwind_replayable_effects(
        connection,
        corrections=corrections,
        now=now,
    )
    replacement_order = {
        str(correction["replacement_target_id"]): index
        for index, correction in enumerate(corrections)
    }
    for correction_index, correction in enumerate(corrections):
        correction_id = str(correction["correction_id"])
        replacement_id = str(correction["replacement_target_id"])
        replacement = _row_dict(
            connection,
            "SELECT * FROM knowledge_graph WHERE triple_id = ?",
            (replacement_id,),
        )
        if replacement is None or str(replacement.get("status")) != "active":
            continue
        predicate = str(replacement["predicate"]).strip().upper()
        rule = rules.get(predicate)
        if rule is None:
            continue
        replay_at = float(correction["replay_at"])
        victims = _conflicting_relationships(
            connection,
            replacement=replacement,
            rule=rule,
            exclusive_groups=exclusive_groups,
            effective_at=replay_at,
        )
        for victim in victims:
            victim_id = str(victim["triple_id"])
            victim_correction_index = replacement_order.get(victim_id)
            if victim_correction_index is not None and victim_correction_index > correction_index:
                continue
            created_at = now + (version_offset * 0.000004)
            inserted = _record_conflict_effect(
                connection,
                correction_id=correction_id,
                victim=victim,
                replacement_id=replacement_id,
                effective_at=replay_at,
                created_at=created_at,
            )
            if not inserted:
                continue
            _append_relationship_version(
                connection,
                triple_id=victim_id,
                correction_id=correction_id,
                created_at=created_at + 0.000001,
            )
            valid_from = float(victim.get("valid_from") or replay_at)
            closure_at = max(replay_at, valid_from)
            if victim.get("valid_to") is not None:
                closure_at = min(closure_at, float(victim["valid_to"]))
            updated = connection.execute(
                """
                UPDATE knowledge_graph
                SET status = ?, status_reason = ?, deprecated_by = ?,
                    deprecated_at = ?, valid_to = ?, updated_at = ?
                WHERE triple_id = ? AND status = 'active'
                """,
                (
                    _status_from_action(
                        rule.opposite_resolution
                        if str(victim["predicate"]).strip().upper() in rule.opposite_predicates
                        else rule.exclusive_resolution
                    ),
                    f"user_correction_conflict:{correction_id}",
                    replacement_id,
                    replay_at,
                    closure_at,
                    now,
                    victim_id,
                ),
            )
            if int(updated.rowcount or 0) != 1:
                raise RuntimeError(
                    f"Relationship changed during correction reconciliation: {victim_id}"
                )
            _append_relationship_version(
                connection,
                triple_id=victim_id,
                correction_id=correction_id,
                created_at=created_at + 0.000002,
            )
            _record_affected_derivations(
                affected,
                correction_id=correction_id,
                replacement=replacement,
                victim=victim,
            )
            version_offset += 1
    _invalidate_affected_derivations(connection, affected=affected, now=now)


def _record_affected_derivations(
    affected: dict[str, dict[str, set[str]]],
    *,
    correction_id: str,
    replacement: dict[str, Any],
    victim: dict[str, Any],
) -> None:
    entry = affected.setdefault(
        correction_id,
        {"edge_ids": set(), "subject_keys": set()},
    )
    entry["edge_ids"].update((str(replacement["triple_id"]), str(victim["triple_id"])))
    for row in (replacement, victim):
        subject_id = str(row.get("subject_id") or "").strip()
        object_id = str(row.get("object_id") or "").strip()
        if subject_id:
            entry["subject_keys"].add(subject_id)
        if ":" in object_id:
            entry["subject_keys"].add(object_id)


def _invalidate_affected_derivations(
    connection: Any,
    *,
    affected: dict[str, dict[str, set[str]]],
    now: float,
) -> None:
    if not affected:
        return
    source_owner: dict[str, str] = {}
    subject_owner: dict[str, str] = {}
    for correction_id, entry in affected.items():
        for edge_id in sorted(entry["edge_ids"]):
            source_owner[edge_id] = correction_id
        for subject_key in sorted(entry["subject_keys"]):
            subject_owner[subject_key] = correction_id

    l3_subjects: set[str] = set()
    dependency_clauses: list[str] = []
    dependency_args: list[str] = []
    source_ids = tuple(sorted(source_owner))
    if source_ids:
        dependency_clauses.append(
            "(dependencies.source_kind = 'edge' "
            "AND dependencies.source_id IN ("
            "SELECT CAST(value AS TEXT) FROM json_each(?)"
            "))"
        )
        dependency_args.append(_json_array(source_ids))
    subject_keys = tuple(sorted(subject_owner))
    if subject_keys:
        dependency_clauses.append(
            "dependencies.subject_key IN (SELECT CAST(value AS TEXT) FROM json_each(?))"
        )
        dependency_args.append(_json_array(subject_keys))
    if dependency_clauses:
        dependent_rows = _row_dicts(
            connection,
            f"""
            SELECT DISTINCT dependencies.artifact_id,
                            dependencies.subject_key,
                            dependencies.source_id
            FROM memory_derivation_dependencies AS dependencies
            JOIN summaries ON summaries.summary_id = dependencies.artifact_id
            WHERE dependencies.artifact_kind = 'l3_insight'
              AND ({' OR '.join(dependency_clauses)})
            ORDER BY dependencies.artifact_id, dependencies.subject_key,
                     dependencies.source_id
            """,
            tuple(dependency_args),
        )
        artifact_ids = tuple(dict.fromkeys(str(row["artifact_id"]) for row in dependent_rows))
        if artifact_ids:
            artifact_ids_json = _json_array(artifact_ids)
            connection.execute(
                """
                UPDATE summaries
                SET derivation_state = 'stale', updated_at = ?
                WHERE summary_id IN (
                    SELECT CAST(value AS TEXT) FROM json_each(?)
                )
                  AND summary_type = 'insight'
                """,
                (now, artifact_ids_json),
            )
            connection.execute(
                """
                DELETE FROM l3_summaries_fts
                WHERE summary_id IN (
                    SELECT CAST(value AS TEXT) FROM json_each(?)
                )
                """,
                (artifact_ids_json,),
            )
        for row in dependent_rows:
            subject_key = str(row.get("subject_key") or "").strip()
            source_id = str(row.get("source_id") or "").strip()
            if not subject_key:
                continue
            l3_subjects.add(subject_key)
            subject_owner.setdefault(
                subject_key,
                source_owner.get(source_id, next(reversed(affected))),
            )

    for subject_key, correction_id in sorted(subject_owner.items()):
        connection.execute(
            """
            INSERT INTO memory_subject_revisions(subject_key, revision, updated_at)
            VALUES (?, 1, ?)
            ON CONFLICT(subject_key) DO UPDATE SET
                revision = memory_subject_revisions.revision + 1,
                updated_at = excluded.updated_at
            """,
            (subject_key, now),
        )
        revision_row = connection.execute(
            "SELECT revision FROM memory_subject_revisions WHERE subject_key = ?",
            (subject_key,),
        ).fetchone()
        assert revision_row is not None
        revision = int(revision_row[0])
        job_kinds = ["snapshot"]
        if subject_key.startswith("user:"):
            job_kinds.extend(("profile", "portrait"))
        if subject_key in l3_subjects:
            job_kinds.append("l3_insight")
        for job_kind in job_kinds:
            connection.execute(
                """
                UPDATE memory_derivation_jobs
                SET status = 'completed', next_retry_at = NULL,
                    last_error = ?, updated_at = ?
                WHERE job_kind = ? AND target_key = ?
                  AND target_revision < ? AND status IN ('pending', 'failed')
                """,
                (
                    f"Superseded by revision {revision}",
                    now,
                    job_kind,
                    subject_key,
                    revision,
                ),
            )
            job_key = uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"v16:{correction_id}:{job_kind}:{subject_key}:{revision}",
            ).hex
            connection.execute(
                """
                INSERT INTO memory_derivation_jobs(
                    job_id, correction_id, job_kind, target_key,
                    target_revision, status, attempt_count, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?)
                ON CONFLICT(correction_id, job_kind, target_key, target_revision)
                DO NOTHING
                """,
                (
                    f"correction_job_{job_key}",
                    correction_id,
                    job_kind,
                    subject_key,
                    revision,
                    now,
                    now,
                ),
            )


def _unwind_replayable_effects(
    connection: Any,
    *,
    corrections: list[dict[str, Any]],
    now: float,
) -> int:
    """Remove transitive legacy ownership before chronological replay."""
    if not corrections:
        return 0
    by_id = {str(correction["correction_id"]): correction for correction in corrections}
    correction_ids_json = _json_array(tuple(by_id))
    effects = _row_dicts(
        connection,
        """
        SELECT effects.*, graph.status AS current_status,
               graph.deprecated_by AS current_deprecated_by,
               graph.valid_from AS victim_valid_from
        FROM memory_relationship_conflict_effects AS effects
        JOIN knowledge_graph AS graph
          ON graph.triple_id = effects.victim_triple_id
        WHERE effects.correction_id IN (
            SELECT CAST(value AS TEXT) FROM json_each(?)
        )
          AND effects.restored_at IS NULL
          AND substr(effects.effect_id, 1, ?) != ?
        ORDER BY effects.effective_at DESC, effects.created_at DESC,
                 effects.effect_id DESC
        """,
        (correction_ids_json, len(_RECONCILED_EFFECT_PREFIX), _RECONCILED_EFFECT_PREFIX),
    )
    version_offset = 0
    for effect in effects:
        correction = by_id[str(effect["correction_id"])]
        replay_at = float(correction["replay_at"])
        victim_valid_from = effect.get("victim_valid_from")
        if victim_valid_from is not None and float(victim_valid_from) > replay_at:
            continue
        replacement_id = str(effect["replacement_triple_id"])
        still_owned = (
            str(effect.get("current_status") or "") in {"deprecated", "conflicted"}
            and str(effect.get("current_deprecated_by") or "") == replacement_id
        )
        if not still_owned:
            continue
        triple_id = str(effect["victim_triple_id"])
        version_at = now + (version_offset * 0.000004)
        _append_relationship_version(
            connection,
            triple_id=triple_id,
            correction_id=str(effect["correction_id"]),
            created_at=version_at,
        )
        updated = connection.execute(
            """
            UPDATE knowledge_graph
            SET status = ?, status_reason = ?, deprecated_by = ?,
                deprecated_at = ?, valid_to = ?, updated_at = ?
            WHERE triple_id = ? AND deprecated_by = ?
              AND status IN ('deprecated', 'conflicted')
            """,
            (
                effect["pre_status"],
                effect["pre_status_reason"],
                effect["pre_deprecated_by"],
                effect["pre_deprecated_at"],
                effect["pre_valid_to"],
                now,
                triple_id,
                replacement_id,
            ),
        )
        if int(updated.rowcount or 0) != 1:
            raise RuntimeError(
                f"Relationship changed during correction reconciliation: {triple_id}"
            )
        _append_relationship_version(
            connection,
            triple_id=triple_id,
            correction_id=str(effect["correction_id"]),
            created_at=version_at + 0.000001,
        )
        connection.execute(
            "DELETE FROM memory_relationship_conflict_effects WHERE effect_id = ?",
            (str(effect["effect_id"]),),
        )
        version_offset += 1
    return version_offset


def _load_conflict_rules(connection: Any) -> dict[str, _ConflictRule]:
    rules = dict(_DEFAULT_CONFLICT_RULES)
    for row in _row_dicts(
        connection,
        """
        SELECT predicate, opposite_predicates, opposite_resolution,
               exclusive_group, exclusive_resolution
        FROM graph_conflict_rules
        ORDER BY predicate
        """,
    ):
        predicate = str(row["predicate"]).strip().upper()
        if not predicate:
            continue
        rules[predicate] = _ConflictRule(
            opposite_predicates=_parse_predicates(row.get("opposite_predicates")),
            opposite_resolution=_normalized_resolution(row.get("opposite_resolution")),
            exclusive_group=str(row.get("exclusive_group") or "").strip() or None,
            exclusive_resolution=_normalized_resolution(row.get("exclusive_resolution")),
        )
    return rules


def _parse_predicates(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            decoded = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        decoded = value
    else:
        decoded = ()
    if not isinstance(decoded, (list, tuple, set)):
        decoded = (decoded,)
    return tuple(
        dict.fromkeys(
            predicate for item in decoded if (predicate := str(item or "").strip().upper())
        )
    )


def _json_array(values: tuple[str, ...]) -> str:
    return json.dumps(values, ensure_ascii=False, separators=(",", ":"))


def _normalized_resolution(value: Any) -> str:
    return "mark_conflicted" if str(value or "").strip() == "mark_conflicted" else "mark_deprecated"


def _exclusive_group_index(
    rules: dict[str, _ConflictRule],
) -> dict[str, tuple[str, ...]]:
    grouped: dict[str, list[str]] = {}
    for predicate, rule in rules.items():
        if rule.exclusive_group:
            grouped.setdefault(rule.exclusive_group, []).append(predicate)
    return {group: tuple(sorted(set(predicates))) for group, predicates in grouped.items()}


def _conflicting_relationships(
    connection: Any,
    *,
    replacement: dict[str, Any],
    rule: _ConflictRule,
    exclusive_groups: dict[str, tuple[str, ...]],
    effective_at: float,
) -> list[dict[str, Any]]:
    victims: dict[str, dict[str, Any]] = {}
    for opposite in rule.opposite_predicates:
        for row in _row_dicts(
            connection,
            """
            SELECT * FROM knowledge_graph
            WHERE subject_id = ? AND object_id = ? AND predicate = ?
              AND scope_key = ? AND triple_id != ? AND status = 'active'
              AND (valid_from IS NULL OR valid_from <= ?)
              AND (valid_to IS NULL OR valid_to > ?)
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY created_at, triple_id
            """,
            (
                str(replacement["subject_id"]),
                str(replacement["object_id"]),
                opposite,
                str(replacement.get("scope_key") or "global"),
                str(replacement["triple_id"]),
                effective_at,
                effective_at,
                effective_at,
            ),
        ):
            victims[str(row["triple_id"])] = row

    if rule.exclusive_group:
        predicates = exclusive_groups.get(rule.exclusive_group, ())
        if predicates:
            placeholders = ", ".join("?" for _ in predicates)
            for row in _row_dicts(
                connection,
                f"""
                SELECT * FROM knowledge_graph
                WHERE subject_id = ? AND predicate IN ({placeholders})
                  AND scope_key = ? AND triple_id != ? AND status = 'active'
                  AND (predicate != ? OR object_id != ?)
                  AND (valid_from IS NULL OR valid_from <= ?)
                  AND (valid_to IS NULL OR valid_to > ?)
                  AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY created_at, triple_id
                """,
                (
                    str(replacement["subject_id"]),
                    *predicates,
                    str(replacement.get("scope_key") or "global"),
                    str(replacement["triple_id"]),
                    str(replacement["predicate"]),
                    str(replacement["object_id"]),
                    effective_at,
                    effective_at,
                    effective_at,
                ),
            ):
                victims[str(row["triple_id"])] = row
    return list(victims.values())


def _record_conflict_effect(
    connection: Any,
    *,
    correction_id: str,
    victim: dict[str, Any],
    replacement_id: str,
    effective_at: float,
    created_at: float,
) -> bool:
    victim_id = str(victim["triple_id"])
    effect_key = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"{correction_id}:{victim_id}",
    ).hex
    cursor = connection.execute(
        """
        INSERT INTO memory_relationship_conflict_effects(
            effect_id, correction_id, victim_triple_id, replacement_triple_id,
            pre_status, pre_status_reason, pre_deprecated_by, pre_deprecated_at,
            pre_valid_to, effective_at, created_at, restored_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(correction_id, victim_triple_id) DO NOTHING
        """,
        (
            f"{_RECONCILED_EFFECT_PREFIX}{effect_key}",
            correction_id,
            victim_id,
            replacement_id,
            str(victim.get("status") or "active"),
            victim.get("status_reason"),
            victim.get("deprecated_by"),
            victim.get("deprecated_at"),
            victim.get("valid_to"),
            effective_at,
            created_at,
        ),
    )
    return int(cursor.rowcount or 0) == 1


def _append_relationship_version(
    connection: Any,
    *,
    triple_id: str,
    correction_id: str,
    created_at: float,
) -> None:
    connection.execute(
        """
        INSERT INTO knowledge_graph_versions(
            version_id, triple_id, previous_version_id, slot_key, claim_fingerprint,
            subject_id, subject_type, predicate, object_id, object_type, fact_kind,
            confidence, evidence_event_ids, evidence_text, status, valid_from, valid_to,
            scope_key, scope_json, authority_ref, correction_id, created_at,
            natural_summary, observation_count, first_observed_at, last_observed_at,
            last_confirmed_at, source_type, extraction_method, expires_at,
            evidence_class, edge_created_at, governance_complete
        )
        SELECT ?, graph.triple_id,
               (
                   SELECT version_id FROM knowledge_graph_versions
                   WHERE triple_id = graph.triple_id
                   ORDER BY created_at DESC, version_id DESC LIMIT 1
               ),
               graph.slot_key, graph.claim_fingerprint, graph.subject_id,
               graph.subject_type, graph.predicate, graph.object_id, graph.object_type,
               graph.fact_kind, graph.confidence, graph.evidence_event_ids,
               COALESCE(graph.evidence_text, ''), graph.status, graph.valid_from,
               graph.valid_to, graph.scope_key, graph.scope_json, graph.authority_ref,
               ?, ?, COALESCE(graph.natural_summary, ''), graph.observation_count,
               graph.first_observed_at, graph.last_observed_at, graph.last_confirmed_at,
               COALESCE(graph.source_type, ''), COALESCE(graph.extraction_method, ''),
               graph.expires_at, graph.evidence_class, graph.created_at, 1
        FROM knowledge_graph AS graph
        WHERE graph.triple_id = ?
        """,
        (f"kgv_{uuid.uuid4().hex}", correction_id, created_at, triple_id),
    )


def _status_from_action(action: str) -> str:
    return "conflicted" if action == "mark_conflicted" else "deprecated"


def _row_dict(
    connection: Any,
    query: str,
    args: tuple[Any, ...] = (),
) -> dict[str, Any] | None:
    rows = _row_dicts(connection, query, args)
    return rows[0] if rows else None


def _row_dicts(
    connection: Any,
    query: str,
    args: tuple[Any, ...] = (),
) -> list[dict[str, Any]]:
    cursor = connection.execute(query, args)
    columns = [str(item[0]) for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


__all__ = [
    "downgrade",
    "reconcile_legacy_relationship_corrections",
    "schema_sql_for_fresh_database",
    "upgrade",
]
