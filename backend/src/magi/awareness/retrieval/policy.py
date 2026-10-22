"""Deterministic source selection, coverage and freshness rules."""
from __future__ import annotations

from magi_plugin_sdk.runtime import SourceCoverage, SourceCoverageScope
from magi_plugin_sdk.source_query import SourceScope




def covers(available: SourceCoverageScope, requested: SourceCoverageScope) -> bool:
    """An unrestricted snapshot contains a narrower scope; search phrases must match."""
    if available.query and available.query != requested.query:
        return False
    if available.containers and set(available.containers) != set(requested.containers):
        return False
    if available.object_ids and not (requested.object_ids and set(requested.object_ids) <= set(available.object_ids)):
        return False
    if available.start is not None and (requested.start is None or available.start > requested.start):
        return False
    if available.end is not None and (requested.end is None or available.end < requested.end):
        return False
    return True


def assess_coverage(
    coverage: SourceCoverage | None, scope: SourceCoverageScope, fields: list[str],
    *, now: float, current: bool, require_checked_after: float | None = None,
    max_age_seconds: float = 0,
) -> dict[str, object]:
    """Keep scope completeness, freshness and snapshot consistency independent."""
    reasons: list[str] = []
    if coverage is None:
        return {"satisfied": False, "complete": False, "fresh": False, "reason": "coverage_unknown"}
    if not covers(coverage.scope, scope):
        reasons.append("scope_not_covered")
    if not set(fields) <= set(coverage.fields):
        reasons.append("fields_not_covered")
    if coverage.completeness != "complete" or coverage.gaps:
        reasons.append("coverage_incomplete")
    complete = not reasons
    # Provider wall clocks cannot establish observations in the future.
    fresh = coverage.checked_at <= now + 1
    observed_at = coverage.snapshot_as_of if coverage.snapshot_as_of is not None else coverage.checked_at
    if current:
        minimum = require_checked_after if require_checked_after is not None else now - max_age_seconds
        fresh = fresh and observed_at >= minimum
    if not fresh:
        reasons.append("observation_stale")
    return {
        "satisfied": complete and fresh, "complete": complete, "fresh": fresh,
        "checked_at": coverage.checked_at, "snapshot_as_of": coverage.snapshot_as_of,
        "consistency": coverage.consistency, "reason": ",".join(reasons) or "satisfied",
    }
