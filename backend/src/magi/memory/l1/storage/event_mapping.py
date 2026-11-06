"""Decode relational event records before crossing the repository boundary."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ...event_contracts import (
    IngestTarget, MemoryDomain, MemoryEvent, RetentionClass, TomDepth,
    author_type_label, content_type_label,
)
from ...evidence import EvidenceClass, EvidenceStatus, L1RetrievalScope
from ..embeddings.common import embedding_status_label
from ..ports import EventEvidence, MemoryEventRecord


from magi_plugin_sdk.storage_models.event_mapping import (
    decode_event_metadata,
    event_record_from_mapping,
)
