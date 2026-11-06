"""Bounded review results for temporal-summary evidence claims."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TemporalStructureReview:
    summary_overrides: dict[str, object]
    issues: list[dict[str, object]] = field(default_factory=list)
    checked: bool = False
    invalid: bool = False


def _draft_quote(claim: str, content: str) -> str | None:
    """Resolve an exact quotation even when inline Markdown markers were omitted."""
    if claim in content:
        return claim
    positions = [index for index, char in enumerate(content) if char not in "`*"]
    plain = "".join(content[index] for index in positions)
    needle = "".join(char for char in claim if char not in "`*")
    if not needle.strip():
        return None
    start = plain.find(needle)
    if start < 0:
        return None
    return content[positions[start] : positions[start + len(needle) - 1] + 1]


def parse_prose_issues(
    payload: dict[str, object],
    *,
    content: str,
    event_ids: list[str],
) -> tuple[list[dict[str, object]], bool]:
    """Accept only bounded quotations from the draft and known evidence ids."""
    raw = payload.get("unsupported_claims")
    if raw is None:
        return [], False
    if not isinstance(raw, list) or len(raw) > 12:
        raise ValueError("Temporal evidence review requires at most twelve issues")
    known_ids = set(event_ids)
    issues: list[dict[str, object]] = []
    for issue in raw:
        if not isinstance(issue, dict):
            raise ValueError("Temporal evidence review issue must be an object")
        claim, reason, refs = issue.get("claim"), issue.get("reason"), issue.get("event_ids")
        if not isinstance(claim, str) or not claim.strip() or len(claim) > 2000:
            raise ValueError("Temporal evidence review must quote the draft")
        quote = _draft_quote(claim, content)
        if quote is None:
            raise ValueError("Temporal evidence review must quote the draft")
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 1200:
            raise ValueError("Temporal evidence review requires a bounded reason")
        if not isinstance(refs, list) or any(
            not isinstance(ref, str) or ref not in known_ids for ref in refs
        ):
            raise ValueError("Temporal evidence review references unknown events")
        issues.append({"claim": quote, "reason": reason, "event_ids": list(dict.fromkeys(refs))})
    return issues, True
