"""Normalization helpers for Chrome history timeline ingestion."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

WINDOWS_TO_UNIX_EPOCH_SECONDS = 11644473600
NOISE_PATH_TOKENS = (
    "login",
    "signin",
    "sign-in",
    "auth",
    "oauth",
    "callback",
    "redirect",
    "payment",
    "checkout",
)
NOISE_TITLE_TOKENS = (
    "sign in",
    "login",
    "redirecting",
    "callback",
    "payment",
    "checkout",
)


def chrome_time_to_unix_seconds(value: int | float | str | None) -> float:
    """Convert Chrome/WebKit microseconds since 1601 into Unix seconds."""

    if value in (None, "", 0, "0"):
        return 0.0
    numeric = float(value)
    return max(0.0, (numeric / 1_000_000.0) - WINDOWS_TO_UNIX_EPOCH_SECONDS)


def normalize_domain(url: str) -> str:
    """Return a normalized hostname for a URL."""

    parsed = urlparse(str(url or ""))
    hostname = (parsed.hostname or parsed.netloc or "").strip().lower()
    if hostname.startswith("www."):
        return hostname[4:]
    return hostname


def site_node_id(domain: str) -> str:
    """Build the canonical site node id for L2."""

    return f"site:{domain}"


def is_noise_visit(item: dict[str, Any]) -> bool:
    """Return whether a visit looks like a navigation-only or noise page."""

    title = str(item.get("title") or "").strip().lower()
    url = str(item.get("url") or "")
    parsed = urlparse(url)
    path = parsed.path.strip("/").lower()
    if not title:
        return True
    if any(token in title for token in NOISE_TITLE_TOKENS):
        return True
    return any(token in path for token in NOISE_PATH_TOKENS)


def should_mark_viewed(item: dict[str, Any]) -> bool:
    """Return whether a visit should be promoted from VISITED to VIEWED."""

    url = str(item.get("url") or "")
    title = str(item.get("title") or "").strip()
    visit_count = int(item.get("visit_count") or 0)
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if is_noise_visit(item):
        return False
    if title and path:
        return True
    return visit_count >= 3 and bool(title)


def build_relation_candidates(item: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate conservative relation candidates for a history item."""

    domain = str(item.get("domain") or normalize_domain(str(item.get("url") or ""))).strip().lower()
    if not domain:
        return []
    observed_at = float(item.get("visit_time") or 0.0)
    object_id = site_node_id(domain)
    object_attributes = {
        "domain": domain,
        "label": domain,
        "source_kind": "site",
    }
    candidates = [
        {
            "subject_id": "user:self",
            "subject_type": "user",
            "predicate": "VISITED",
            "object_id": object_id,
            "object_type": "site",
            "confidence": 0.6,
            "observed_at": observed_at,
            "object_attributes": object_attributes,
        }
    ]
    if should_mark_viewed(item):
        candidates.append(
            {
                "subject_id": "user:self",
                "subject_type": "user",
                "predicate": "VIEWED",
                "object_id": object_id,
                "object_type": "site",
                "confidence": 0.78,
                "observed_at": observed_at,
                "object_attributes": object_attributes,
            }
        )
    return candidates
