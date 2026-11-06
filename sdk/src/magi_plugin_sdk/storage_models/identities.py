"""Shared chat persistence contracts and value codecs."""

import hashlib
import json


def identity_key(*values: str) -> str:
    """Index complete identities without truncation or collation-dependent equality."""
    return hashlib.sha256(
        json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
