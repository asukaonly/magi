"""Portable persistence values and deterministic row normalization."""

from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field


@dataclass(slots=True)
class EmbeddingProfile:
    """Stable identifier for one embedding configuration."""

    profile_id: str
    provider_name: str
    model_name: str
    dimension: int | None
    text_builder_version: str
    identity_kind: str = "remote"
    identity_key: str = ""
    provenance: dict[str, str | None] = field(default_factory=dict)

    @classmethod
    def build(
        cls,
        *,
        provider_name: str,
        model_name: str,
        dimension: int | None,
        text_builder_version: str,
        identity_kind: str = "remote",
        identity_key: str | None = None,
        provenance: dict[str, str | None] | None = None,
    ) -> "EmbeddingProfile":
        normalized_provider_name = str(provider_name).strip() or "unknown"
        normalized_model_name = str(model_name).strip() or "embedding"
        normalized_identity_kind = str(identity_kind).strip().lower() or "remote"
        normalized_identity_key = str(identity_key or normalized_model_name).strip()
        normalized_text_builder_version = str(text_builder_version).strip() or "v1"
        normalized_dimension = int(dimension) if dimension is not None else None
        payload = {
            "identity_kind": normalized_identity_kind,
            "identity_key": normalized_identity_key,
            "model_name": normalized_model_name if normalized_identity_kind == "remote" else None,
            "dimension": normalized_dimension,
            "text_builder_version": normalized_text_builder_version,
        }
        digest = hashlib.sha1(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:12]
        return cls(
            profile_id=digest,
            provider_name=normalized_provider_name,
            model_name=normalized_model_name,
            dimension=normalized_dimension,
            text_builder_version=normalized_text_builder_version,
            identity_kind=normalized_identity_kind,
            identity_key=normalized_identity_key,
            provenance=dict(provenance or {}),
        )
