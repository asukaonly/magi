"""Canonical logical snapshot digest, independent of row order."""
import hashlib
import json
from typing import Any

def snapshot_digest(snapshot: Any) -> str:
    payload = snapshot.model_dump(mode="json")
    for records in payload.values():
        if isinstance(records, list):
            records.sort(key=lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False))
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()
