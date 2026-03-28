"""Normalization helpers for Chrome history timeline ingestion."""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse, urlunparse

WINDOWS_TO_UNIX_EPOCH_SECONDS = 11644473600
BURST_WINDOW_SECONDS = 60.0
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


def normalize_title(value: str | None) -> str:
    """Return a whitespace-normalized title string."""

    return " ".join(str(value or "").split()).strip()


def normalize_domain(url: str) -> str:
    """Return a normalized hostname for a URL."""

    parsed = urlparse(str(url or ""))
    hostname = (parsed.hostname or parsed.netloc or "").strip().lower()
    if hostname.startswith("www."):
        return hostname[4:]
    return hostname


def canonicalize_url(url: str) -> str:
    """Return a stable URL used for display and burst grouping.

    The canonical form intentionally drops fragments so client-side state churn
    does not create a new timeline item for every in-page update.
    """

    parsed = urlparse(str(url or "").strip())
    hostname = normalize_domain(url)
    if not hostname:
        return str(url or "").strip()
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    query = parsed.query
    return urlunparse(("https", hostname, path, "", query, ""))


def burst_merge_key(url: str, title: str | None) -> str:
    """Return the semantic merge key used for burst grouping.

    This intentionally ignores query-string churn and relies on the stable
    host/path shape plus the normalized title. Search result pages and similar
    navigation surfaces often mutate query parameters while remaining the same
    user-visible page.
    """

    parsed = urlparse(str(url or "").strip())
    hostname = normalize_domain(url)
    if not hostname:
        return ""
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"
    normalized_title = normalize_title(title)
    if not normalized_title:
        return ""
    return f"https://{hostname}{path}|{normalized_title.lower()}"


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
    """Return whether a visit is strong enough to emit a VIEWED relation."""

    url = str(item.get("canonical_url") or item.get("url") or "")
    title = normalize_title(str(item.get("title") or ""))
    visit_count = max(
        int(item.get("visit_count") or 0),
        int(item.get("merged_visit_count") or 0),
    )
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
    if not should_mark_viewed(item):
        return []
    return [
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
    ]


def should_merge_visit(
    current: dict[str, Any],
    candidate: dict[str, Any],
    *,
    burst_window_seconds: float = BURST_WINDOW_SECONDS,
) -> bool:
    """Return whether two visits should collapse into one timeline item."""

    current_key = str(
        current.get("burst_merge_key")
        or burst_merge_key(str(current.get("url") or ""), current.get("title"))
    )
    candidate_key = str(
        candidate.get("burst_merge_key")
        or burst_merge_key(str(candidate.get("url") or ""), candidate.get("title"))
    )
    if not current_key or current_key != candidate_key:
        return False
    current_domain = str(current.get("domain") or "")
    candidate_domain = str(candidate.get("domain") or "")
    if current_domain != candidate_domain:
        return False
    current_time = float(current.get("visit_time") or 0.0)
    candidate_time = float(candidate.get("visit_time") or 0.0)
    if candidate_time - current_time > burst_window_seconds:
        return False
    current_title = normalize_title(current.get("title"))
    candidate_title = normalize_title(candidate.get("title"))
    if current_title and candidate_title and current_title != candidate_title:
        return False
    return True
