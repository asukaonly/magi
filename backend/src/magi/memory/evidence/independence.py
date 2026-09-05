"""Stable evidence groups independent of ingestion attempts and repeated exposure."""

from __future__ import annotations

import hashlib
import json
import unicodedata
from typing import Any, Mapping
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


def independent_evidence_key(event: Mapping[str, Any]) -> str:
    """Group copied content and repeated exposures without changing occurrence lineage."""
    metadata = event.get("metadata_json") or {}
    source = str(event.get("source") or "")
    kind = str(event.get("event_type") or "")
    author = str(event.get("author_type") or "")
    content = " ".join(unicodedata.normalize("NFKC", str(event.get("content") or "")).split())
    imported = source == "history_import" or kind.startswith("history_import.")
    if source == "chat" and not imported:
        identity = ["chat_message", str(event.get("source_item_id") or event.get("event_id") or "")]
    elif imported and content:
        identity = ["imported_content", author, content]
    else:
        raw_url = metadata.get("canonical_url") or metadata.get("url")
        if raw_url:
            parts = urlsplit(str(raw_url))
            query = [(key, value) for key, value in parse_qsl(parts.query, keep_blank_values=True) if not key.casefold().startswith("utm_") and key.casefold() not in {"fbclid", "gclid"}]
            identity = ["resource", urlunsplit((parts.scheme.casefold(), parts.netloc.casefold(), parts.path, urlencode(sorted(query)), ""))]
        else:
            resource_key = metadata.get("content_id") or metadata.get("article_id") or metadata.get("track_id")
            entity_keys = sorted(str(hint["source_entity_key"]) for hint in metadata.get("structured_entity_hints", []) if isinstance(hint, dict) and hint.get("source_entity_key"))
            if resource_key or entity_keys:
                identity = ["source_resource", source, str(resource_key) if resource_key else entity_keys]
            elif content:
                identity = ["observed_content", content]
            else:
                identity = ["source_item", source, str(event.get("source_item_id") or event.get("event_id") or "")]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
