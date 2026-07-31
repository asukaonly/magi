"""Host-owned fingerprints for plugin registry consent and provenance."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .contracts import PluginRegistryIndex


def _canonical_fingerprint(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def registry_install_fingerprint(
    index: PluginRegistryIndex,
    *,
    registry_url: str,
    repo_url: str,
) -> str:
    """Bind user consent to the complete registry snapshot and source."""

    return _canonical_fingerprint(
        {
            "registry_url": registry_url,
            "repo_url": repo_url,
            "index": index.model_dump(mode="json"),
        }
    )


__all__ = ["registry_install_fingerprint"]
