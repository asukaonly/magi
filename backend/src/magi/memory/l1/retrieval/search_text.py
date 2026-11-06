"""Canonical event text used by lexical and semantic retrieval."""

from __future__ import annotations

from ...embedding.embedding_text_builders import build_l1_retrieval_terms_text
from ...event_contracts import MemoryEvent


from magi_plugin_sdk.storage_models.event_search_text import (
    get_search_text,
    compose_search_text,
)
