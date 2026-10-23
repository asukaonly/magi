"""Typed answer-shape contract for coverage-sensitive retrieval."""
from __future__ import annotations
from dataclasses import asdict, dataclass
from typing import Literal, cast

RecallDomain = Literal["photo", "browser", "music", "mail", "calendar", "notes", "unknown"]
RecallOperation = Literal["search", "existence", "count", "enumerate", "aggregate"]
RecallCoverage = Literal["sample", "exhaustive", "unknown"]

@dataclass(frozen=True)
class RecallShape:
    """Requested coverage is intent, never proof of exhaustive source coverage."""
    domain_hint: RecallDomain = "unknown"
    operation: RecallOperation = "search"
    desired_coverage: RecallCoverage = "unknown"
    freshness: Literal["retained", "current"] = "retained"
    search_query: str = ""
    provider_hint: str = ""
    account_hint: str = ""
    required_fields: tuple[str, ...] = ("content",)

    def to_dict(self) -> dict[str, object]:
        return {**asdict(self), "required_fields": list(self.required_fields)}


def parse_recall_shape(raw: object) -> RecallShape:
    """Validate semantic output without inferring intent from query substrings."""
    if not isinstance(raw, dict):
        return RecallShape()
    domain = raw.get("domain_hint")
    operation = raw.get("operation")
    if not isinstance(domain, str) or domain not in {"photo", "browser", "music", "mail", "calendar", "notes", "unknown"}:
        return RecallShape()
    if not isinstance(operation, str) or operation not in {"search", "existence", "count", "enumerate", "aggregate"}:
        return RecallShape()
    raw_fields = raw.get("required_fields")
    requested_fields = raw_fields if isinstance(raw_fields, (list, tuple)) else ["content"]
    return RecallShape(
        domain_hint=cast(RecallDomain, domain),
        operation=cast(RecallOperation, operation),
        freshness="current" if raw.get("freshness") == "current" else "retained",
        search_query=str(raw.get("search_query") or "")[:4096],
        provider_hint=str(raw.get("provider_hint") or "")[:128],
        account_hint=str(raw.get("account_hint") or "")[:256],
        required_fields=tuple(x for x in requested_fields if isinstance(x, str) and x in {"content", "labels", "thread", "attachments", "attachment_content"}) or ("content",),
        desired_coverage="exhaustive" if operation in {"count", "enumerate", "aggregate"} else "sample",
    )
