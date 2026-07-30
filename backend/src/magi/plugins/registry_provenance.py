"""Host-owned fingerprints for plugin registry consent and provenance."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from .contracts import PluginManifest, PluginRegistryEntry, PluginRegistryIndex


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


def registry_entry_fingerprint(
    entry: PluginRegistryEntry,
    *,
    registry_url: str,
    repo_url: str,
) -> str:
    """Bind an installed package to its registry source and exact entry."""

    return _canonical_fingerprint(
        {
            "registry_url": registry_url,
            "repo_url": repo_url,
            "entry": entry.model_dump(mode="json"),
        }
    )


def plugin_manifest_fingerprint(manifest: PluginManifest) -> str:
    """Fingerprint immutable manifest declarations without runtime paths."""

    return _canonical_fingerprint(
        manifest.model_dump(
            mode="json",
            by_alias=True,
            exclude={"manifest_path", "plugin_dir", "source"},
        )
    )


__all__ = [
    "plugin_manifest_fingerprint",
    "registry_entry_fingerprint",
    "registry_install_fingerprint",
]
