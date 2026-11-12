"""Storage-neutral publication and hydration records for event embeddings."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

from ..embedding.chunking import ChunkedText
from ..embedding.embedding_service import EmbeddingProfile
from ..embedding.embedding_text_builders import build_l1_embedding_text
from ..event_contracts import MemoryDomain, MemoryEvent


from magi_plugin_sdk.storage_models.event_embeddings import (
    EventEmbeddingSource,
    EventEmbeddingPublication,
    EventChunkRecord,
)
