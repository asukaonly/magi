"""Embedding text and profile persistence helpers for L1 events."""

from __future__ import annotations

from typing import Any, cast

from ...embedding.embedding_service import EmbeddingProfile
from ...embedding.embedding_text_builders import build_l1_embedding_text
from ...event_contracts import MemoryEvent
from .common import (
    EMBEDDING_TEXT_BUILDER_VERSION,
    L1EventEmbeddingHostProtocol,
)


class L1EventEmbeddingProfileMixin:
    """Own embedding text construction and embedding profile rows."""

    def get_embedding_text(self, event: MemoryEvent) -> str:
        return cast(str, build_l1_embedding_text(event))

    def get_active_embedding_profile_id(self) -> str | None:
        host = cast(L1EventEmbeddingHostProtocol, self)
        profile_id, _ = host._resolve_active_embedding_profile_id()
        return profile_id

    def _profile_from_embedding_result(self, embedding: Any) -> EmbeddingProfile:
        host = cast(L1EventEmbeddingHostProtocol, self)
        if host._embedding_service is not None and hasattr(
            host._embedding_service, "profile_from_result"
        ):
            return host._embedding_service.profile_from_result(
                embedding,
                text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
            )
        return EmbeddingProfile.build(
            provider_name="unknown",
            model_name=str(getattr(embedding, "model_name", "embedding")),
            dimension=int(getattr(embedding, "dimension", 0) or 0),
            text_builder_version=EMBEDDING_TEXT_BUILDER_VERSION,
        )
