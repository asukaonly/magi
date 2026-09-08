"""Read literal assertion values according to their field contract."""

from __future__ import annotations

import json
from typing import Any


def decode_assertion_literal(trait_name: str, value: Any) -> Any:
    """Decode the address-list union without interpreting arbitrary user text.

    Disallowed addresses accept a single Claim literal or the string list written
    by Personal Profile. Other literal fields retain their exact text.
    """
    if trait_name != "communication.address.disallowed" or not isinstance(value, str):
        return value
    try:
        decoded = json.loads(value)
    except (ValueError, TypeError):
        return value
    if isinstance(decoded, list) and all(isinstance(item, str) for item in decoded):
        return decoded
    return value
