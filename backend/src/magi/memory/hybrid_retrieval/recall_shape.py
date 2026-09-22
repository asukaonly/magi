"""Typed answer-shape contract for coverage-sensitive retrieval."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Literal, cast

RecallDomain = Literal["photo", "browser", "music", "unknown"]
RecallOperation = Literal["search", "existence", "count", "enumerate", "aggregate"]
RecallCoverage = Literal["sample", "exhaustive", "unknown"]

@dataclass(frozen=True)
class RecallShape:
    """Requested coverage is intent, never proof of exhaustive source coverage."""
    domain_hint: RecallDomain = "unknown"
    operation: RecallOperation = "search"
    desired_coverage: RecallCoverage = "unknown"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def parse_recall_shape(raw: object) -> RecallShape:
    """Validate semantic output without inferring intent from query substrings."""
    if not isinstance(raw, dict):
        return RecallShape()
    domain = raw.get("domain_hint")
    operation = raw.get("operation")
    if not isinstance(domain, str) or domain not in {"photo", "browser", "music", "unknown"}:
        return RecallShape()
    if not isinstance(operation, str) or operation not in {"search", "existence", "count", "enumerate", "aggregate"}:
        return RecallShape()
    return RecallShape(
        domain_hint=cast(RecallDomain, domain),
        operation=cast(RecallOperation, operation),
        desired_coverage="exhaustive" if operation in {"count", "enumerate", "aggregate"} else "sample",
    )
